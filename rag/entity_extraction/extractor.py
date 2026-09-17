"""
문서 본문 -> (관련성 판정, 카테고리 분류, 엔티티 리스트, 관계 리스트) LLM 추출 — LLM 호출 1번으로 다 처리.

config.LLM_PROVIDER("openai" | "anthropic")에 따라 다른 API를 호출하지만, 반환 형태는 항상 같음:
    {
        "is_relevant": bool,          # "생성형 AI와 음악 창작" 주제와 실제로 관련 있는 문서인지
        "relevance_reason": str,      # 그렇게 판단한 한 줄 이유(로그/디버깅용)
        "category": str | None,       # 저작권/창작자성/음성복제/AI작곡 중 하나(문서 실제 내용 기준) —
                                       # is_relevant=False거나 파싱 실패면 None. pipeline/ingest.py는
                                       # None이 아니면 collector가 넘긴 category를 이 값으로 덮어씀.
        "entities":  [{"name": str, "entity_type": str}, ...],
        "relations": [{"entity_name": str, "entity_type": str,
                        "relation_type": str, "confidence": float}, ...],
    }

2026-09-16: category를 LLM이 문서 "실제 내용"을 보고 분류하도록 추가함 — 원래 news_collector.py는
모든 기사에 category="음성복제"를 하드코딩(TODO로 남아있던 버그)해서 저작권/AI작곡 관련 뉴스까지
전부 음성복제로 찍히는 문제가 있었음. 다른 collector(paper/official/policy/case)도 검색쿼리나
사람이 미리 정한 category를 쓰던 거라 실제 본문과 어긋날 수 있는 건 마찬가지라, collector가 넘긴
category는 "1차 힌트"로만 쓰고 여기서 실제 내용 기준으로 재분류하는 걸 기본 동작으로 함.
entity_type / relation_type은 known_types.ENTITY_TYPES / RELATION_TYPES 안의 값만 허용 —
LLM이 그 밖의 값을 내놓으면 그 항목만 조용히 버리고(전체 실패시키지 않음) 계속 진행.

pipeline/ingest.py는 is_relevant=False면 이 문서를 아예 저장하지 않고 건너뛴다(수집 단계의
"꼭 관련된 내용으로만 수집" 요건 — LLM 판정으로 거름).
"""
from __future__ import annotations

import json
import re

from rag.config import LLM_API_KEY, LLM_MODEL, LLM_PROVIDER
from database.neo4j.known_types import CATEGORIES, ENTITY_TYPES, RELATION_TYPES

# 문서가 너무 길면 토큰 비용/처리 시간이 커지니 앞부분만 사용.
# 뉴스/논문 초록은 보통 도입부에 핵심 개체가 다 나오므로 6000자면 충분함.
MAX_CHARS = 6000

# 2026-09-16: case/policy는 6000자로 자르면 위험함을 발견 — case_collector.py는 "판시사항 +
# 판결요지 + 판례내용"을 이어붙여서 저장하는데, 실제 AI/음악 관련 언급이 판례내용 뒷부분에만
# 나오는 경우 앞 6000자(판시사항+판결요지 정도)만 보고 is_relevant=False로 잘못 걸러낼 수 있음.
# policy도 저작권위원회 공지처럼 긴 문서가 있어 동일한 위험. case/policy 자체가 원래도 데이터가
# 희소한 타입이라(case는 LAW_API_OC 없이는 0건) 이 컷오프 때문에 한 번 더 깎이는 걸 막기 위해
# 더 넉넉하게 줌 — 두 타입 다 수집량이 적어서 토큰 비용 증가분도 무시할 수준.
MAX_CHARS_LONG = 15000
_LONG_DOCUMENT_TYPES = {"case", "policy"}

_SYSTEM_PROMPT = """너는 "생성형 AI와 음악 창작"(저작권/창작자성/음성복제/AI작곡) 연구 프로젝트의
문서 수집 파이프라인에서 관련성 판정/카테고리 분류/엔티티·관계 추출을 한 번에 담당하는 도구다.

[1] 관련성 판정 (is_relevant)
이 문서가 "생성형 AI와 음악 창작" 주제와 실제로 관련 있는 내용인지 판단하라. 아래 4개 쟁점 중
하나라도 실질적으로 다루면 true:
  - 저작권: AI 생성 음악/음성의 저작권 침해, 소송, 라이선스 이슈
  - 창작자성: AI 생성물의 저작자 인정 여부, 창작 주체성 논의
  - 음성복제: AI 음성 복제/딥페이크 보이스, 음성권, 동의 없는 목소리 학습
  - AI작곡: Suno/Udio 등 AI 작곡·음악생성 서비스, 그 기술/산업 동향
단순히 "AI"나 "음악"이라는 단어가 섞여 나올 뿐 위 쟁점과 무관하면(예: AI 주식 시황, 음악 오디션
프로그램 단순 소개) false로 판정하라.

[2] is_relevant가 true일 때, 이 문서를 아래 4개 카테고리 중 가장 비중이 큰 것 딱 하나로
분류하라(category). 여러 쟁점을 같이 다루더라도 하나만 골라라:
  - "저작권": 저작권 침해, 소송, 라이선스, 권리 귀속 이슈가 핵심
  - "창작자성": AI 생성물의 저작자 인정 여부, 창작 주체성 논의가 핵심
  - "음성복제": AI 음성 복제/딥페이크 보이스, 음성권, 동의 없는 목소리 학습이 핵심
  - "AI작곡": 위 셋에 해당 안 되는, Suno/Udio 등 AI 작곡·음악생성 서비스/기술/산업 동향이 핵심

[3] is_relevant가 true일 때만 아래 엔티티/관계도 추출하라 (false면 entities/relations는
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
{"is_relevant": true, "relevance_reason": "...", "category": "저작권",
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
        return {
            "is_relevant": False,
            "relevance_reason": "LLM 응답 파싱 실패",
            "category": None,
            "entities": [],
            "relations": [],
        }

    is_relevant = bool(data.get("is_relevant", False))
    relevance_reason = str(data.get("relevance_reason") or "")

    category = data.get("category")
    if category not in CATEGORIES:  # LLM이 화이트리스트 밖 값을 내놓으면 그냥 힌트 없음으로 처리
        category = None

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
        "category": category,
        "entities": entities,
        "relations": relations,
    }


def analyze_document(text: str, document_type: str | None = None) -> dict:
    """text(문서 본문) -> {"is_relevant", "relevance_reason", "entities", "relations"}.

    document_type: "case"/"policy"면 MAX_CHARS_LONG(15000자)까지, 그 외(news/paper/...)는
    기존 MAX_CHARS(6000자)까지만 사용 — 위 _LONG_DOCUMENT_TYPES 주석 참고. 생략하면(None)
    기존 동작(6000자)과 동일 — entity_extraction/sync.extract_and_store()의 단독 테스트
    호출처럼 document_type을 모르는 경우를 위한 하위호환.

    LLM_PROVIDER가 .env에 없으면 NotImplementedError — pipeline/ingest.py는 이걸 보고
    관련성 판정/엔티티 추출 단계를 건너뛴다(수집한 문서는 그대로 신뢰하고 저장).
    """
    if not LLM_PROVIDER:
        raise NotImplementedError(
            "LLM_PROVIDER가 .env에 설정되지 않았습니다. "
            ".env(LLM_PROVIDER/LLM_MODEL/LLM_API_KEY)를 채우세요."
        )

    max_chars = MAX_CHARS_LONG if document_type in _LONG_DOCUMENT_TYPES else MAX_CHARS
    snippet = text[:max_chars]

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
