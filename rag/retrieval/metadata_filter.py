"""
category / published_at 등 metadata 필터 SQL 조각을 만드는 공용 헬퍼.
vector_search.py, keyword_search.py가 같이 사용 -> 필터 조건이 어긋나지 않게 한 곳에서 관리.
"""
from __future__ import annotations

from datetime import date


def build_filter(category: str | None = None, published_after: date | None = None) -> tuple[str, list]:
    """
    반환: (WHERE 뒤에 이어붙일 SQL 조각, 파라미터 리스트)
    조건이 없으면 ("", [])를 반환 — 호출부에서 "WHERE 1=1 {filter_sql}" 형태로 이어붙이면 편함.
    """
    clauses: list[str] = []
    params: list = []

    if category:
        clauses.append("d.category = %s")
        params.append(category)

    if published_after:
        clauses.append("d.published_at >= %s")
        params.append(published_after)

    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params
