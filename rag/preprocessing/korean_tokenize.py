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


def tokenize_for_search(text: str) -> str:
    """
    text -> 검색용으로 정규화된 토큰을 공백으로 이어붙인 문자열.
    예: "인공지능이 생성한 음악의 저작권을 침해했다" -> "인공지능 생성 음악 저작권 침해"
    빈 문자열/공백만 있으면 빈 문자열 반환 — 호출부(ingest.py/keyword_search.py)에서
    빈 결과면 원문으로 폴백하는 게 안전함(전부 숫자/기호뿐인 chunk 등 예외 케이스 대비).
    """
    text = (text or "").strip()
    if not text:
        return ""

    kiwi = _get_kiwi()
    tokens = kiwi.tokenize(text)
    keep = [t.form for t in tokens if t.tag in _KEEP_TAGS]
    return " ".join(keep)


if __name__ == "__main__":
    sample = "인공지능이 생성한 음악의 저작권을 침해했다는 주장이 제기됐다."
    print(f"원문: {sample}")
    print(f"토큰화: {tokenize_for_search(sample)}")
