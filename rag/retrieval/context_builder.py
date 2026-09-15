"""
팀 공통 인터페이스: search_context(topic) -> RAG Context

3번(backend)이 이 함수 하나만 import해서 씀. 시그니처가 바뀌면 3번 코드도 같이 깨지니
바꿀 일 있으면 미리 공유할 것.

반환 형식(공통 규약):
{
  "contexts": [
      {"chunk_id": ..., "document_id": ..., "content": ..., "score": 0.91}, ...
  ],
  "sources": [
      {"document_id": ..., "title": ..., "url": ..., "author": ...,
       "published_at": "2025-11-10", "category": "음성복제"}, ...
  ]
}
"""
from __future__ import annotations

from database.config import get_connection
from rag.embedding.embed import embed_texts
from rag.retrieval.hybrid_rrf import reciprocal_rank_fusion
from rag.retrieval.keyword_search import keyword_search
from rag.retrieval.vector_search import vector_search


def _fetch_sources(conn, document_ids: list[str]) -> list[dict]:
    if not document_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, url, author, published_at, category
            FROM documents
            WHERE id = ANY(%s);
            """,
            (document_ids,),
        )
        rows = cur.fetchall()
    return [
        {
            "document_id": r[0],
            "title": r[1],
            "url": r[2],
            "author": r[3],
            "published_at": r[4].isoformat() if r[4] else None,
            "category": r[5],
        }
        for r in rows
    ]


def search_context(topic: str, category: str | None = None, top_k: int = 5) -> dict:
    """
    topic(연구 주제/제목 문자열)을 받아 관련 근거를 검색해서 RAG Context로 반환.

    embedding provider가 아직 설정 안 됐으면(embedding/embed.py 참고) 벡터 검색은 건너뛰고
    키워드 검색만으로 동작 — MVP 초기 개발 단계에서도 search_context()를 바로 쓸 수 있게 하기 위함.
    """
    with get_connection() as conn:
        try:
            query_embedding = embed_texts([topic])[0]
            vec_results = vector_search(conn, query_embedding, category=category, top_k=50)
        except NotImplementedError:
            print("[context_builder] embedding 미설정 — 키워드 검색만으로 동작합니다.")
            vec_results = []

        kw_results = keyword_search(conn, topic, category=category, top_k=50)

        fused = reciprocal_rank_fusion(vec_results, kw_results, top_k=top_k)
        sources = _fetch_sources(conn, list({r["document_id"] for r in fused}))

    contexts = [
        {
            "chunk_id": r["chunk_id"],
            "document_id": r["document_id"],
            "content": r["content"],
            "score": r["score"],
        }
        for r in fused
    ]

    return {"contexts": contexts, "sources": sources}


if __name__ == "__main__":
    import json

    result = search_context("생성형 AI의 음성복제와 저작권 침해 문제")
    print(json.dumps(result, ensure_ascii=False, indent=2))
