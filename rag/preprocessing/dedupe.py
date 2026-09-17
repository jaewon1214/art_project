"""
중복 수집 방지 — 2단계로 걸러냄.
  1. 완전 중복: documents.content_hash(UNIQUE) 완전 일치 — content_hash()/is_duplicate()
  2. 근접 중복: documents.title 트라이그램 유사도(pg_trgm) — find_near_duplicate()

완전 일치만으로는 안 잡히는 게 있음 — 같은 사건("소니, Suno 제소" 등)을 여러 매체가
문구만 조금씩 다르게 보도하면 본문이 달라서 content_hash가 다르고, 그대로 다 저장되면
검색 결과가 사실상 같은 내용 반복으로 도배됨(뉴스 볼륨을 늘릴수록 심해지는 문제).
제목 트라이그램 유사도로 2차 방어선을 둠 — schema.sql에 idx_documents_title_trgm(GIN)이
이미 있었는데 실제로 쓰는 코드가 없었어서 이번에 연결함.
"""
from __future__ import annotations

import hashlib

from database.config import get_connection

# similarity()는 0.0(전혀 다름)~1.0(완전 동일). pg_trgm 기본 유사도 임계값(0.3)보다 훨씬
# 보수적으로 잡음 — 오탐(전혀 다른 기사인데 제목 구조가 비슷해서 걸리는 것)을 줄이기 위해
# "거의 확실히 같은 사건" 수준인 0.6 이상만 근접중복으로 판정.
NEAR_DUPLICATE_TITLE_THRESHOLD = 0.6


def content_hash(text: str) -> str:
    """정규화된 본문의 sha256 해시. documents.content_hash에 그대로 저장."""
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_duplicate(conn, hash_value: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM documents WHERE content_hash = %s LIMIT 1;", (hash_value,))
        return cur.fetchone() is not None


def find_near_duplicate(
    conn, title: str, document_type: str, threshold: float = NEAR_DUPLICATE_TITLE_THRESHOLD
) -> str | None:
    """title과 트라이그램 유사도가 threshold를 넘는 기존 문서(같은 document_type 안에서만 비교)가
    있으면 그 제목을 반환, 없으면 None. document_type으로 한정하는 이유: 예를 들어 뉴스 제목과
    논문 제목이 우연히 비슷한 어휘 구조를 가져도(예: "AI 음악 저작권 침해") 서로 다른 성격의
    자료라 근접중복으로 볼 이유가 없음 — 같은 성격의 자료끼리 비교해야 오탐이 줄어듦."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT title
            FROM documents
            WHERE document_type = %s
              AND similarity(title, %s) > %s
            ORDER BY similarity(title, %s) DESC
            LIMIT 1;
            """,
            (document_type, title, threshold, title),
        )
        row = cur.fetchone()
        return row[0] if row else None


if __name__ == "__main__":
    # 간단 동작 확인용
    h = content_hash("테스트 문서 본문입니다.")
    print("hash:", h)
    with get_connection() as conn:
        print("이미 존재?", is_duplicate(conn, h))
        print("근접중복?", find_near_duplicate(conn, "테스트 제목", "news"))
