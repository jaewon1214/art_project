"""
pgvector 기반 벡터(의미) 검색.
"""
from __future__ import annotations

from rag.retrieval.metadata_filter import build_filter


def vector_search(conn, query_embedding: list[float], category: str | None = None, top_k: int = 50) -> list[dict]:
    """
    query_embedding과 가장 가까운(코사인 거리) chunk를 top_k개 반환.
    반환: [{"chunk_id": ..., "document_id": ..., "content": ..., "rank": 1}, ...]  (rank는 1부터, RRF용)
    """
    embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"
    filter_sql, filter_params = build_filter(category=category)

    sql = f"""
        SELECT c.id AS chunk_id, c.document_id, c.content,
               ROW_NUMBER() OVER (ORDER BY c.embedding <=> %s::vector) AS rnk
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.embedding IS NOT NULL {filter_sql}
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s;
    """
    params = [embedding_literal, *filter_params, embedding_literal, top_k]

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {"chunk_id": r[0], "document_id": r[1], "content": r[2], "rank": r[3]}
        for r in rows
    ]
