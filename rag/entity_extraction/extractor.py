"""
문서 본문 -> (관련성 판정, 엔티티 리스트, 관계 리스트) LLM 추출 — LLM 호출 1번으로 둘 다 처리.

config.LLM_PROVIDER("openai" | "anthropic")에 따라 다른 API를 호출하지만, 반환 형태는 항상 같음:
    {
        "is_relevant": bool,          # "생성형 AI와 음악 창작" 주제와 실제로 관련 있는 문서인지
        "relevance_reason": str,      # 그렇게 판단한 한 줄 이유(로그/디버깅용)
        "entities":  [{"name": str, "entity_type": str}, ...],
        "relations": [{"entity_name": str, "entity_type": str,
                        "relation_type": str, "confidence": float}, ...],
    }
entity_type / relation_type은 known_types.ENTITY_TYPES / RELATION_TYPES 안의 값만 허용 —
LLM이 그 밖의 값을 내놓으면 그 항목만 조용히 버리고(전체 실패시키지 않음) 계속 진행.

pipeline/ingest.py는 is_relevant=False면 이 문서를 아예 저장하지 않고 건너뛴다(수집 단계의
"꼭 관련된 내용으로만 수집" 요건 — LLM 판정으로 거름).
"""
from __future__ import annotations

import json
import re

from rag.config import LLM_API_KEY, LLM_MODEL, LLM_PROVIDER
from database.neo4j.known_types import ENTITY_TYPES, RELATION_TYPES

# 문서가 너무 길면 토큰 비용/처리 시간이 커지니 앞부분만 사용.
# 뉴스/정책 기사는 보통 도입부에 핵심 개체가 다 나오므로 충분함.
MAX_CHARS = 6000

_SYSTEM_PROMPT = """너는 "생성형 AI와 음악 창작"(저작권/창작자성/음성복제/AI작곡) 연구 프로젝트의
문서 수집 파이프라인에서 두 가지를 판정하는 도구다.

[1] 관련성 판정 (is_relevant)
이 문서가 "생성형 AI와 음악 창작" 주제와 실제로 관련 있는 내용인지 판단하라. 아래 4개 쟁점 중
하나라도 실질적으로 다루면 true:
  - 저작권: AI 생성 음악/음성의 저작권 침해, 소송, 라이선스 이슈
  - 창작자성: AI 생성물의 저작자 인정 여부, 창작 주체성 논의
  - 음성복제: AI 음성 복제/딥페이크 보이스, 음성권, 동의 없는 목소리 학습
  - AI작곡: Suno/Udio 등 AI 작곡·음악생성 서비스, 그 기술/산업 동향
단순히 "AI"나 "음악"이라는 단어가 섞여 나올 뿐 위 쟁점과 무관하면(예: AI 주식 시황, 음악 오디션
프로그램 단순 소개) false로 판정하라.

[2] is_relevant가 true일 때만 아래 엔티티/관계도 추출하라 (false면 entities/relations는
빈 배열로 둬도 됨):

개체 종류(entity_type)는 반드시 다음 중 하나:
- Artist   : 실존 음악가/가수/작곡가
- Company  : 기업, 음반사, 스타트업(예: 하이브, 유니버설뮤직)
- AIModel  : AI 음악/음성 생성 모델·서비스(예: Suno, Udio, 사운드로우)
- Topic    : 이 문서가 다루는 핵심 쟁점(예: '저작권 침해', '음성 복제 동의')
- Case     : 구체적인 소송/분쟁 사건명
- Law      : 법률/제도/정책명

관계 종류(relation_type)는 반드시 다음 중 하나:
- DISCUSSES  : 문서가 이 개체를 핵심 주제로 다룸
- MENTIONS   : 문서에 이 개체가 언급만 됨
- DEVELOPS   : (Company/Artist가 AIModel을) 개발/출시함
- RELATED_TO : 개체 간 일반적 연관
- CITES      : 문서가 이 개체(Case/Law 등)를 근거로 인용함

반드시 아래 JSON 형식으로만 답하라 (설명, 코드펜스, 다른 텍스트 금지):
{"is_relevant": true, "relevance_reason": "...",
 "entities": [{"name": "...", "entity_type": "..."}],
 "relations": [{"entity_name": "...", "entity_type": "...", "relation_type": "...", "confidence": 0.0}]}

개체는 문서당 최대 10개로 추리고, 핵심적이지 않은 개체는 넣지 마라."""


def _call_openai(text: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=LLM_API_KEY)
    resp = client.chat.completions.create(
        model=LLM_MODEL or "gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or "{}"


def _call_anthropic(text: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=LLM_API_KEY)
    resp = client.messages.create(
        model=LLM_MODEL or "claude-haiku-4-5",
        max_tokens=1024,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    return "".join(block.text for block in resp.content if hasattr(block, "text"))


def _strip_code_fence(raw: str) -> str:
    """```json ... ``` 로 감싸서 응답하는 모델 대비."""
    match = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.S)
    return match.group(1).strip() if match else raw.strip()


def _parse_response(raw: str) -> dict:
    cleaned = _strip_code_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 파싱 실패 시 "관련 없음"으로 안전하게 처리 — 잘못 저장하는 것보다 건너뛰는 게 낫다.
        return {"is_relevant": False, "relevance_reason": "LLM 응답 파싱 실패", "entities": [], "relations": []}

    is_relevant = bool(data.get("is_relevant", False))
    relevance_reason = str(data.get("relevance_reason") or "")

    entities = []
    for e in data.get("entities", []):
        name = (e.get("name") or "").strip()
        entity_type = e.get("entity_type")
        if name and entity_type in ENTITY_TYPES:
            entities.append({"name": name, "entity_type": entity_type})

    relations = []
    for r in data.get("relations", []):
        entity_name = (r.get("entity_name") or "").strip()
        entity_type = r.get("entity_type")
        relation_type = r.get("relation_type")
        if entity_name and entity_type in ENTITY_TYPES and relation_type in RELATION_TYPES:
            relations.append(
                {
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "relation_type": relation_type,
                    "confidence": float(r.get("confidence") or 0.5),
                }
            )

    return {
        "is_relevant": is_relevant,
        "relevance_reason": relevance_reason,
        "entities": entities,
        "relations": relations,
    }


def analyze_document(text: str) -> dict:
    """text(문서 본문) -> {"is_relevant", "relevance_reason", "entities", "relations"}.

    LLM_PROVIDER가 .env에 없으면 NotImplementedError — pipeline/ingest.py는 이걸 보고
    관련성 판정/엔티티 추출 단계를 건너뛴다(수집한 문서는 그대로 신뢰하고 저장).
    """
    if not LLM_PROVIDER:
        raise NotImplementedError(
            "LLM_PROVIDER가 .env에 설정되지 않았습니다. "
            ".env(LLM_PROVIDER/LLM_MODEL/LLM_API_KEY)를 채우세요."
        )

    snippet = text[:MAX_CHARS]

    if LLM_PROVIDER == "openai":
        raw = _call_openai(snippet)
    elif LLM_PROVIDER == "anthropic":
        raw = _call_anthropic(snippet)
    else:
        raise NotImplementedError(f"'{LLM_PROVIDER}' provider 구현 필요 (entity_extraction/extractor.py)")

    return _parse_response(raw)


if __name__ == "__main__":
    sample = "Suno가 새 버전을 출시하며 저작권 침해 논란이 다시 불거졌다. 하이브는 이에 대응해 자체 AI 정책을 발표했다."
    print(json.dumps(analyze_document(sample), ensure_ascii=False, indent=2))
