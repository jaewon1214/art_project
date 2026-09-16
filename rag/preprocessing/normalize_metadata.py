"""
documents 테이블에 넣기 전 metadata 값을 스키마가 기대하는 값으로 정규화.
"""
from __future__ import annotations

# schema.sql 주석에 정의된 허용값
ALLOWED_CATEGORIES = {"저작권", "창작자성", "음성복제", "AI작곡"}
ALLOWED_DOCUMENT_TYPES = {"news", "webpage", "policy", "official", "paper", "case"}


def normalize(doc: dict) -> dict:
    """collectors가 준 raw dict를 documents insert에 바로 쓸 수 있는 형태로 정리."""
    doc = dict(doc)  # 원본 훼손 방지

    doc["title"] = (doc.get("title") or "").strip()
    doc["content"] = (doc.get("content") or "").strip()
    doc["language"] = (doc.get("language") or "ko").strip().lower()

    category = doc.get("category")
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"허용되지 않은 category: {category!r} (허용값: {ALLOWED_CATEGORIES})")

    document_type = doc.get("document_type")
    if document_type not in ALLOWED_DOCUMENT_TYPES:
        raise ValueError(f"허용되지 않은 document_type: {document_type!r} (허용값: {ALLOWED_DOCUMENT_TYPES})")

    return doc
