"""
중복 수집 방지. documents.content_hash(UNIQUE)를 기준으로 판단.
"""
from __future__ import annotations

import hashlib

from database.config import get_connection


def content_hash(text: str) -> str:
    """정규화된 본문의 sha256 해시. documents.content_hash에 그대로 저장."""
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_duplicate(conn, hash_value: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM documents WHERE content_hash = %s LIMIT 1;", (hash_value,))
        return cur.fetchone() is not None


if __name__ == "__main__":
    # 간단 동작 확인용
    h = content_hash("테스트 문서 본문입니다.")
    print("hash:", h)
    with get_connection() as conn:
        print("이미 존재?", is_duplicate(conn, h))
