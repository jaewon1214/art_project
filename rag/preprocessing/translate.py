"""
비한국어 문서를 한국어로 번역 — LLM_PROVIDER/LLM_MODEL/LLM_API_KEY 재사용(entity_extraction과 같은 .env 키).

pipeline/ingest.py에서 딱 한 군데서만 호출됨:
    document_type != "paper" AND language != "ko" 인 문서만 번역.
    영어 논문(arXiv/Semantic Scholar)은 원문 학술 용어 보존을 위해 절대 번역하지 않음 — 이 조건은
    ingest.py 쪽에서 검사하고, 이 모듈은 "번역해라"라고 불려온 텍스트는 무조건 번역만 한다.

관련성 판정(extractor.analyze_document)이 끝나 is_relevant=True로 확정된 문서에 대해서만 호출되므로,
주제와 무관해서 어차피 버려질 문서를 번역하는 데 비용을 쓰지 않음.

긴 문서(예: EU AI Act 원문처럼 수만 자)는 한 번의 LLM 호출로 처리하기 어려워서 CHUNK_SIZE_CHARS
단위로 나눠 각각 번역 후 이어붙인다. 문단 경계가 아니라 글자수로 자르기 때문에 chunk 경계에서
문장이 살짝 끊길 수 있지만, 이후 다시 chunking/임베딩을 거치는 중간 산출물이라 실용적으로 허용.

2026-09-16: "번역 결과에 영어 문장이 군데군데 그대로 남아있다" 문제 발견 후 두 가지 보강:
  1) CHUNK_SIZE_CHARS 3000 -> 1500 — 한 번에 넘기는 분량이 클수록(특히 목록/인용이 섞인 긴 기사)
     gpt-4o-mini가 뒷부분을 대충 넘기거나 일부 문장을 원문 그대로 남기는 경향이 있었음. 한 번에
     번역시키는 분량을 줄이면 완역 안정성이 올라감.
  2) 번역 결과에 한글이 하나도 없는 긴 문장(_count_untranslated_sentences)이 남아있으면 "다시
     번역해라" 프롬프트로 최대 2번까지 재시도. 브랜드명 몇 개가 원문 그대로 섞이는 건 정상(시스템
     프롬프트가 의도한 동작)이라, 짧은 단어 몇 개가 아니라 "문장 전체"가 원문 그대로 남은 경우만
     잡아냄(_UNTRANSLATED_SENTENCE_MIN_LEN자 이상 & 한글 0개 기준).
"""
from __future__ import annotations

import re

from rag.config import LLM_API_KEY, LLM_MODEL, LLM_PROVIDER

CHUNK_SIZE_CHARS = 1500  # 번역 1회 호출당 최대 입력 글자 수 (2026-09-16: 3000 -> 1500)

_SYSTEM_PROMPT = """너는 전문 번역가다. 아래 원문을 자연스러운 한국어로 번역하라.
- 고유명사(회사명/서비스명/인명, 예: Suno, Udio, IFPI, WIPO)는 번역하지 말고 원문 그대로 유지
- 법률/기술 용어는 정확한 한국어 대응 용어로 번역 (직역보다 의미 전달 우선)
- 원문에 있는 모든 문장을 빠짐없이 번역해야 한다 — 목록/나열형 문장이나 인용문도 예외 없이 전부
  번역할 것. 일부 문장만 번역하고 나머지를 원문 그대로 남기는 것은 절대 금지.
- 번역 결과만 출력하고, 설명/주석/원문 병기 등 다른 텍스트는 절대 추가하지 마라"""

_RETRY_SYSTEM_PROMPT = _SYSTEM_PROMPT + """

⚠️ 방금 전 시도에서 일부 문장이 번역되지 않고 원문(영어 등)이 그대로 남아있었다. 이번에는 문장
하나도 빠짐없이 전체를 한국어로 번역해서 출력하라."""

# 짧은 브랜드명/약어 몇 개가 원문 그대로 섞이는 건 정상 동작이라 "문장 전체"가 원문 그대로 남은
# 경우만 걸러내기 위한 최소 길이 기준.
_UNTRANSLATED_SENTENCE_MIN_LEN = 40
_MAX_TRANSLATE_RETRIES = 2

_HANGUL_RE = re.compile(r"[가-힣]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _count_untranslated_sentences(text: str) -> int:
    """번역 결과 안에서 한글이 하나도 없는 긴 문장이 몇 개 남아있는지 셈."""
    count = 0
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        sentence = sentence.strip()
        if len(sentence) >= _UNTRANSLATED_SENTENCE_MIN_LEN and not _HANGUL_RE.search(sentence):
            count += 1
    return count


def _split(text: str, size: int = CHUNK_SIZE_CHARS) -> list[str]:
    pieces = [text[i : i + size] for i in range(0, len(text), size)]
    return pieces or [""]


# 2026-09-16: 번역 호출이 응답 없이 오래 걸릴 때(네트워크 지연 등) 콘솔에 아무 표시도 없이
# 멈춘 것처럼 보이는 문제가 있어서(재시도 로그만 찍히고 그 다음 API 응답을 기다리는 동안 아무
# 출력이 없었음) 명시적 타임아웃 + 호출 전 로그를 추가함. 기본 SDK 타임아웃(10분)보다 훨씬
# 짧게 잡아서, 진짜 멈춘 거면 오래 안 기다리고 바로 에러로 드러나게 함.
_LLM_TIMEOUT_SEC = 30


def _call_openai(text: str, system_prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=LLM_API_KEY, timeout=_LLM_TIMEOUT_SEC)
    resp = client.chat.completions.create(
        model=LLM_MODEL or "gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        temperature=0,
    )
    return (resp.choices[0].message.content or "").strip()


def _call_anthropic(text: str, system_prompt: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=LLM_API_KEY, timeout=_LLM_TIMEOUT_SEC)
    resp = client.messages.create(
        model=LLM_MODEL or "claude-haiku-4-5",
        max_tokens=4096,
        temperature=0,
        system=system_prompt,
        messages=[{"role": "user", "content": text}],
    )
    return "".join(block.text for block in resp.content if hasattr(block, "text")).strip()


def _call_llm(text: str, system_prompt: str) -> str:
    if LLM_PROVIDER == "openai":
        return _call_openai(text, system_prompt)
    if LLM_PROVIDER == "anthropic":
        return _call_anthropic(text, system_prompt)
    raise NotImplementedError(f"'{LLM_PROVIDER}' provider 구현 필요 (preprocessing/translate.py)")


def _translate_piece(piece: str, piece_no: int = 1, total_pieces: int = 1) -> str:
    """piece 하나를 번역하고, 결과에 원문 그대로 남은 문장이 있으면 최대 _MAX_TRANSLATE_RETRIES번
    "다시 번역해라" 프롬프트로 재시도. 그래도 남아있으면 마지막 결과를 그냥 반환(완벽하진 않아도
    최소한 대부분은 번역된 상태 — 번역 실패로 파이프라인 전체를 막지는 않음)."""
    print(f"[translate] 조각 {piece_no}/{total_pieces} 번역 요청 중... ({len(piece)}자)")
    result = _call_llm(piece, _SYSTEM_PROMPT)
    for attempt in range(_MAX_TRANSLATE_RETRIES):
        remaining = _count_untranslated_sentences(result)
        if remaining == 0:
            break
        print(
            f"[translate] 조각 {piece_no}/{total_pieces}: 번역 결과에 원문 문장 {remaining}개 잔존 — "
            f"재시도 요청 중... ({attempt + 1}/{_MAX_TRANSLATE_RETRIES})"
        )
        result = _call_llm(piece, _RETRY_SYSTEM_PROMPT)
    else:
        # for-else: 마지막 재시도까지 다 돌고도 못 벗어났으면(break 없이 루프 종료) 마지막 상태를 알려줌
        remaining = _count_untranslated_sentences(result)
        if remaining > 0:
            print(f"[translate] 조각 {piece_no}/{total_pieces}: 재시도 소진, 원문 문장 {remaining}개 남은 채로 진행")
    return result


def translate_to_korean(text: str) -> str:
    """
    text(비한국어 원문) -> 한국어 번역문.
    text가 비어있거나 LLM_PROVIDER가 .env에 없으면 원문을 그대로 반환(번역 스킵 — 파이프라인이
    번역 실패로 통째로 막히지 않게, entity_extraction과 동일한 방어적 설계).
    """
    text = (text or "").strip()
    if not text or not LLM_PROVIDER:
        return text

    pieces = [p for p in _split(text) if p.strip()]
    translated: list[str] = []
    for i, piece in enumerate(pieces, start=1):
        translated.append(_translate_piece(piece, piece_no=i, total_pieces=len(pieces)))

    return "\n\n".join(translated) if translated else text


if __name__ == "__main__":
    sample = "Suno's new terms of service raised copyright concerns among independent artists."
    print(translate_to_korean(sample))
