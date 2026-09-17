"""
한국어 형태소 분석 기반 검색용 텍스트 정규화.

Postgres FTS의 to_tsvector('simple', ...)는 공백/구두점 기준으로만 쪼개고 조사/어미를 전혀
안 떼어내서, "저작권"으로 검색해도 본문에 "저작권을"만 있으면 매칭이 안 되는 문제가 있었음
(예: "저작권 침해" 쿼리가 "저작권을 침해했다는" 본문과 전혀 안 걸림 — AND 조건인 tsquery가
정확히 그 형태의 토큰을 요구하기 때문). 이 모듈은 kiwipiepy로 명사/어간만 뽑아서 조사·어미를
제거한 문자열을 만들고, 그걸 chunks.content_tokenized에 저장 -> content_tsv가 그 컬럼을
기준으로 생성되도록 스키마를 바꿨음(database/init/01_schema.sql, migrate_korean_tokenize.py
참고). 원문 표시용 content 컬럼은 그대로 두고 검색 인덱싱용 컬럼만 따로 둔 것.

keyword_search.py도 쿼리 텍스트를 같은 함수로 토큰화한 뒤 tsquery를 만들어야 양쪽 형태가
맞아떨어짐 — 한쪽만 형태소 분석하면 의미가 없음.

영어/숫자 등 비한국어 토큰은 형태소 분석이 필요 없어서 원형 그대로 살려둠(SL/SH/SN 태그).
"""
from __future__ import annotations

from functools import lru_cache

# 검색에 의미 있는 품사만 남김 — 조사(J*)/어미(E*)/구두점(SF, SP 등)은 전부 버림.
# 이게 핵심: "저작권을" -> NNG("저작권") + JKO("을") 로 쪼개지고, 조사 태그는 버려서 "저작권"만 남음.
_KEEP_TAGS = {
    "NNG", "NNP", "NNB",  # 일반명사 / 고유명사 / 의존명사
    "VV", "VA", "XR",     # 동사·형용사 어간 / 어근
    "SL", "SH", "SN",     # 외국어(영문 등) / 한자 / 숫자
}


@lru_cache(maxsize=1)
def _get_kiwi():
    """Kiwi는 초기화(사전 로딩)에 비용이 있어서 프로세스당 한 번만 만들어 재사용."""
    from kiwipiepy import Kiwi

    return Kiwi()


# 2026-09-17: kiwipiepy 자체가 죽어있으면(미설치/초기화 실패) 매 호출마다 다시 시도하느라
# (lru_cache는 예외를 캐싱하지 않음) 문서마다 비싼 초기화를 반복하게 됨 — 한 번 실패하면
# 프로세스 내내 다시 시도하지 않도록 별도로 기억해둠. tokenize() 자체가 특정 입력에서만
# 실패하는 경우(예: 드문 유니코드/혼합 스크립트)는 이 플래그를 건드리지 않음 — 그 청크
# 하나만 폴백하고 kiwi 자체는 계속 정상 사용.
_kiwi_init_failed = False


def tokenize_for_search(text: str) -> str:
    """
    text -> 검색용으로 정규화된 토큰을 공백으로 이어붙인 문자열.
    예: "인공지능이 생성한 음악의 저작권을 침해했다" -> "인공지능 생성 음악 저작권 침해"
    빈 문자열/공백만 있으면 빈 문자열 반환 — 호출부(ingest.py/keyword_search.py)에서
    빈 결과면 원문으로 폴백하는 게 안전함(전부 숫자/기호뿐인 chunk 등 예외 케이스 대비).

    2026-09-17: kiwipiepy 초기화 실패나 특정 입력에서의 tokenize() 실패도 예외를 던지지
    않고 빈 문자열로 반환하도록 바꿈 — 번역 없이 원문 그대로(영어 등 비한국어 포함) 저장하는
    정책으로 바뀌면서 이 함수가 받는 입력이 훨씬 다양해졌는데, 예전엔 여기서 예외가 나면
    build_chunk_rows()를 거쳐 ingest_document() 밖으로 그대로 전파돼 documents insert까지
    롤백되면서 문서 1건이 통째로 유실됐음(그 전에 이미 쓴 LLM 관련성판정 비용도 낭비).
    이제는 실패해도 빈 문자열을 반환해서, 호출부의 기존 "빈 결과면 원문으로 폴백" 로직
    (build_chunk_rows의 `tokenize_for_search(piece) or piece`)이 그대로 적용되게 함 —
    검색 품질은(형태소 분석 없이 원문 그대로 색인되니) 그 청크만 조금 떨어지지만, 문서 자체는
    안전하게 저장됨.
    """
    text = (text or "").strip()
    if not text:
        return ""

    global _kiwi_init_failed
    if _kiwi_init_failed:
        return ""

    try:
        kiwi = _get_kiwi()
    except Exception as e:  # noqa: BLE001 — kiwipiepy 미설치/초기화 실패. 이후 호출은 재시도 없이 바로 폴백.
        _kiwi_init_failed = True
        print(f"[korean_tokenize] kiwipiepy 초기화 실패({e}) — 이후 호출은 전부 원문 폴백으로 처리합니다.")
        return ""

    try:
        tokens = kiwi.tokenize(text)
    except Exception as e:  # noqa: BLE001 — 이 텍스트에서만 실패. kiwi 자체는 계속 정상이라 폴백은 이번만.
        print(f"[korean_tokenize] 형태소 분석 실패({e}) — 이 텍스트는 원문으로 폴백합니다.")
        return ""

    keep = [t.form for t in tokens if t.tag in _KEEP_TAGS]
    return " ".join(keep)


if __name__ == "__main__":
    sample = "인공지능이 생성한 음악의 저작권을 침해했다는 주장이 제기됐다."
    print(f"원문: {sample}")
    print(f"토큰화: {tokenize_for_search(sample)}")
