"""
PostgreSQL FTS(tsvector) 기반 키워드 검색.

2026-09-16: 쿼리 텍스트도 chunks.content_tsv를 만들 때와 동일하게 한국어 형태소 분석을
거치도록 고침(tokenize_for_search) — content_tsv가 이제 원문이 아니라 형태소 분석된
content_tokenized 기준으로 생성되므로(chunker.py/schema.sql 참고), 쿼리 쪽도 똑같이
토큰화해야 "저작권을"(본문) vs "저작권"(쿼리) 같은 조사 차이로 매칭이 안 되는 문제가 안 생김.
양쪽 다 토큰화 안 하거나 양쪽 다 토큰화해야 맞아떨어지지, 한쪽만 하면 의미가 없음.
"""
from __future__ import annotations

from rag.preprocessing.korean_tokenize import tokenize_for_search
from rag.retrieval.metadata_filter import build_filter


def keyword_search(conn, query_text: str, category: str | None = None, top_k: int = 50) -> list[dict]:
    """
    query_text와 매칭되는 chunk를 ts_rank 기준 top_k개 반환.
    반환: [{"chunk_id": ..., "document_id": ..., "content": ..., "rank": 1}, ...]  (rank는 1부터, RRF용)
    """
    filter_sql, filter_params = build_filter(category=category)

    # 형태소 분석 결과가 비면(예: 쿼리가 전부 특수문자/영문 약어뿐) 원문으로 폴백.
    tokenized_query = tokenize_for_search(query_text) or query_text

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
    params = [tokenized_query, tokenized_query, *filter_params, top_k]

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {"chunk_id": r[0], "document_id": r[1], "content": r[2], "rank": r[3]}
        for r in rows
    ]
