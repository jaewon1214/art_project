"""
팀 공통 인터페이스: search_context(topic) -> RAG Context

3번(backend)이 이 함수 하나만 import해서 씀. 시그니처가 바뀌면 3번 코드도 같이 깨지니
바꿀 일 있으면 미리 공유할 것.

내부적으로 Vector Search + Keyword Search + Graph Search(Neo4j) + Exact-Match Search
(쿼리에 들어있는 고유명사/사건명이 content에 그대로 있는지) 네 경로를 RRF로 합쳐서
반환함 — search_context()의 입출력 형식 자체는 그대로라 backend는 신경 쓸 필요 없음.

2026-09-17: Exact-Match Search 채널 추가(rag/retrieval/exact_match_search.py) — "Concord Music
Group" 같은 사건 당사자명이 쿼리에 정확히 포함된 경우, 일반적인 AI 음악 관련 문서보다 그
사건을 직접 다룬 문서가 Top-K에 우선적으로 오르도록 하기 위함. RRF에 이 채널의 결과를 두 번
넣어서(reciprocal_rank_fusion 호출부 참고) 가중치를 강하게 줌 — vector/keyword/graph 세 경로는
"의미적으로 비슷한지"/"형태소가 겹치는지"만 보고 정확 일치 여부를 직접 반영하지 못했던 빈틈을
메우는 채널이라, 다른 세 채널과 동일한 가중치로는 신호가 묻힐 수 있어서 의도적으로 2배로 줌.

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
from rag.retrieval.exact_match_search import exact_match_search
from rag.retrieval.graph_search import graph_search
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
            WHERE id = ANY(%s::uuid[]);
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
    키워드+그래프 검색만으로 동작 — MVP 초기 개발 단계에서도 search_context()를 바로 쓸 수 있게 하기 위함.
    Neo4j가 설정 안 됐거나 연결 실패해도 마찬가지로 graph_search()가 빈 리스트를 반환하므로
    vector+keyword만으로 계속 동작한다 — 세 검색 경로 다 "있으면 쓰고 없으면 건너뛰는" 동일한 설계.
    """
    with get_connection() as conn:
        try:
            query_embedding = embed_texts([topic])[0]
            vec_results = vector_search(conn, query_embedding, category=category, top_k=50)
        except NotImplementedError:
            print("[context_builder] embedding 미설정 — 벡터 검색은 건너뜁니다.")
            vec_results = []

        kw_results = keyword_search(conn, topic, category=category, top_k=50)
        graph_results = graph_search(conn, topic, top_k=30)
        exact_results = exact_match_search(conn, topic, category=category, top_k=30)

        # exact_results를 두 번 넣어서 RRF 가중치를 강하게 줌 — 고유명사 exact match는
        # vector/keyword/graph 세 경로가 놓칠 수 있는 신호라 한 번만 넣으면 다른 세 채널에
        # 묻힐 수 있음(위 모듈 docstring 참고).
        fused = reciprocal_rank_fusion(
            vec_results, kw_results, graph_results, exact_results, exact_results, top_k=top_k
        )
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
