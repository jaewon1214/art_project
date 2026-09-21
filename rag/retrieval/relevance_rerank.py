"""
검색 후보(chunk) 목록 중, 검색 주제(topic)와 실질적으로 관련 있는 것만 한 번 더 골라내는
LLM 기반 재판정.

배경: 2026-09-21 생성 논문 리뷰에서 "음악 저작권" 검색에 "게임 저작권" 기사가 섞여 들어오는
사례가 확인됨. 수집 단계(ingest.py)의 관련성판정은 "생성형 AI와 음악 창작" 전체 주제 기준이라
게임 저작권 기사도 "AI저작권 논의"로는 통과했을 수 있는데, 검색 단계의 최소 관련성 필터
(context_builder.py, score/channel_count 기준)는 "얼마나 확신 있게 매칭됐는가"만 보지 "주제
단어가 겹치는 것"과 "실제 내용이 그 주제인 것"을 구별하지 못함 — 정규식 키워드 게이트보다
정확하게 이 구별을 하려고 LLM 재판정을 추가함.

context_builder.search_context()가 최소관련성 필터를 통과한 후보(candidates)에 대해서만 이
함수를 호출 — candidate_pool 전체(최대 수십 건)가 아니라 이미 1차로 걸러진 소수에만 LLM 호출
1회를 추가하는 구조라 비용이 크지 않음(문의당 정확히 1회 호출, MAX_CANDIDATES 상한도 있음).

LLM_PROVIDER 미설정이거나 호출/파싱이 실패하거나 재판정 결과가 이상하면(전부 무관 등)
candidates를 그대로 반환(fail-open) — 다른 검색 경로들과 동일하게 "있으면 쓰고 없으면
건너뛰는" 방어적 설계를 따름. 재판정 단계 하나 때문에 검색 자체가 0건이 되는 사고를 막기
위함.
"""
from __future__ import annotations

import json
import re

from rag.config import LLM_API_KEY, LLM_MODEL, LLM_PROVIDER

MAX_SNIPPET_CHARS = 300  # 후보당 LLM에 보여줄 본문 길이 — 판정에 필요한 만큼만, 토큰 비용 절약
MAX_CANDIDATES = 20  # 이보다 후보가 많으면 상위 점수(=candidates 앞쪽)만 재판정(비용 상한)

_SYSTEM_PROMPT = """너는 "생성형 AI와 음악 창작"(저작권/창작자성/음성복제/AI작곡) 연구
프로젝트의 RAG 검색 결과 중, 검색 주제와 실질적으로 관련 있는 후보만 골라내는 재판정 도구다.

아래에 검색 주제와 번호가 매겨진 후보 문서 조각(chunk) 목록이 주어진다. 각 후보가 주제와
실질적으로 관련되어 있는지 판단하라 — 단순히 "AI"나 "저작권" 같은 단어가 겹치는 것만으로는
부족하고, 검색 주제가 구체적으로 묻는 내용과 실제로 연결되는지를 봐야 한다. 예를 들어 게임
저작권 분쟁을 다루는 기사는 "저작권"이라는 단어는 겹치지만 음악 관련 검색 주제에는 보통
관련이 없다. 다만 음악을 직접 언급하지 않아도 생성형 AI 저작권 법리를 일반적으로 다루면서
음악 사례에도 적용 가능한 논문/정책자료(예: AI 학습데이터의 공정이용 일반론)는 관련 있다고
볼 수 있다 — 완전히 다른 도메인(게임/미술/영상 등)의 구체적 사건 자체를 다루는 것과, 여러
도메인에 걸쳐 적용되는 일반 법리를 다루는 것을 구별하라.

반드시 아래 JSON 형식으로만 답하라 (설명, 코드펜스, 다른 텍스트 금지):
{"relevant_indices": [1, 3, 5]}

목록에 없는 번호를 만들어내지 말고, 관련 있는 후보가 하나도 없으면 빈 배열을 반환하라."""


def _call_openai(prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=LLM_API_KEY)
    resp = client.chat.completions.create(
        model=LLM_MODEL or "gpt-4o-mini",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or "{}"


def _call_anthropic(prompt: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=LLM_API_KEY)
    resp = client.messages.create(
        model=LLM_MODEL or "claude-haiku-4-5",
        max_tokens=512,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if hasattr(block, "text"))


def _strip_code_fence(raw: str) -> str:
    """```json ... ``` 로 감싸서 응답하는 모델 대비 (entity_extraction/extractor.py와 동일 패턴)."""
    match = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.S)
    return match.group(1).strip() if match else raw.strip()


def _build_prompt(topic: str, candidates: list[dict]) -> str:
    lines = [f"검색 주제: {topic}", "", "후보 목록:"]
    for i, c in enumerate(candidates, start=1):
        snippet = (c.get("content") or "")[:MAX_SNIPPET_CHARS].replace("\n", " ")
        lines.append(f"[{i}] {snippet}")
    return "\n".join(lines)


def rerank_by_relevance(topic: str, candidates: list[dict]) -> list[dict]:
    """candidates(score 내림차순으로 이미 정렬돼 있다고 가정 — context_builder.py가 그렇게 넘김)를
    받아, topic과 실질적으로 관련 있는 것만 남겨서 반환(원래 순서 유지).

    fail-open 조건: candidates가 비어있음 / LLM_PROVIDER 미설정 / 지원 안 하는 provider /
    호출 또는 JSON 파싱 실패 / 재판정 결과가 전부 "무관"인 극단적 케이스 — 이 경우 전부
    candidates를 그대로(필터링 없이) 반환한다. 재판정은 "더 정확하게 거르는" 보조 수단이지,
    검색 결과를 0건으로 만들 권한까지는 없어야 하기 때문.
    """
    if not candidates:
        return candidates
    if not LLM_PROVIDER:
        return candidates

    # 비용 상한 — 상위 MAX_CANDIDATES건만 재판정. 상한 밖으로 밀린 건 원래도 점수가 더 낮은
    # 후보들이라, 재판정 없이 그대로 뒤에 붙여서 반환(호출부의 top_k 슬라이싱이 알아서 정리함).
    to_check = candidates[:MAX_CANDIDATES]
    rest = candidates[MAX_CANDIDATES:]

    prompt = _build_prompt(topic, to_check)
    try:
        if LLM_PROVIDER == "openai":
            raw = _call_openai(prompt)
        elif LLM_PROVIDER == "anthropic":
            raw = _call_anthropic(prompt)
        else:
            return candidates  # 지원 안 하는 provider — 재판정 없이 통과(fail-open)

        data = json.loads(_strip_code_fence(raw))
        relevant_indices = {
            i for i in data.get("relevant_indices", [])
            if isinstance(i, int) and 1 <= i <= len(to_check)
        }
    except Exception as e:  # noqa: BLE001 — 재판정 실패해도 검색 자체는 계속 동작해야 함
        print(f"[relevance_rerank] LLM 재판정 실패, 필터링 없이 통과: {e}")
        return candidates

    if not relevant_indices:
        # 파싱은 됐지만 전부 무관 판정 — 모델이 과도하게 엄격했을 가능성도 있어, 검색 결과를
        # 통째로 비우기보다는 원래 후보를 그대로 반환하는 쪽이 안전함(0건보다 낫다는 원칙).
        print("[relevance_rerank] 재판정 결과 관련 후보 0건 — 필터링 없이 원본 통과")
        return candidates

    kept = [c for i, c in enumerate(to_check, start=1) if i in relevant_indices]
    return kept + rest


if __name__ == "__main__":
    sample_topic = "생성형 AI의 음악저작물 학습과 저작권 침해"
    sample_candidates = [
        {"chunk_id": "a", "document_id": "d1", "content": "Suno와 Udio는 음악을 생성하는 AI 서비스로, 저작권 침해 소송이 제기되었다."},
        {"chunk_id": "b", "document_id": "d2", "content": "엔씨소프트가 게임 캐릭터 저작권 침해로 패소한 사건을 다룬 기사."},
        {"chunk_id": "c", "document_id": "d3", "content": "생성형 AI의 저작물 학습 전반에 대한 공정이용 법리를 다루는 논문."},
    ]
    print(json.dumps(rerank_by_relevance(sample_topic, sample_candidates), ensure_ascii=False, indent=2))
