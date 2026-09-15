"""
PostgreSQL FTS(tsvector) 기반 키워드 검색.
"""
from __future__ import annotations

from rag.retrieval.metadata_filter import build_filter


def keyword_search(conn, query_text: str, category: str | None = None, top_k: int = 50) -> list[dict]:
    """
    query_text와 매칭되는 chunk를 ts_rank 기준 top_k개 반환.
    반환: [{"chunk_id": ..., "document_id": ..., "content": ..., "rank": 1}, ...]  (rank는 1부터, RRF용)
    """
    filter_sql, filter_params = build_filter(category=category)

    sql = f"""
        SELECT c.id AS chunk_id, c.document_id, c.content,
               ROW_NUMBER() OVER (
                   ORDER BY ts_rank(c.content_tsv, plainto_tsquery('simple', %s)) DESC
               ) AS rnk
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.content_tsv @@ plainto_tsquery('simple', %s) {filter_sql}
        ORDER BY rnk
        LIMIT %s;
    """
    params = [query_text, query_text, *filter_params, top_k]

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {"chunk_id": r[0], "document_id": r[1], "content": r[2], "rank": r[3]}
        for r in rows
    ]
