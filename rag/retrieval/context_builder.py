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

2026-09-19: sources 각 항목에 score(그 문서의 chunk 중 RRF 최고점) 필드를 추가하고, 너무
약하게만 걸린 문서를 contexts/sources에서 걸러내는 최소 관련성 필터를 추가함 — 3번(backend)이
RAG가 반환한 sources를 그대로 최종 참고문헌 목록에 넣다 보니, RRF에서 top_k 안에만 들면 실제로는
주제와 약하게만 연관된 문서도 "근거"처럼 인용되는 문제가 있었음. search_context()의 반환
스키마(딕셔너리 키 구성)는 그대로라 3번 쪽 호출부는 변경 없이 그대로 써도 됨 — sources 항목에
score 키가 "추가"될 뿐 기존 키는 전부 유지됨. 자세한 필터 기준은 아래 search_context() 본문 참고.

반환 형식(공통 규약):
{
  "contexts": [
      {"chunk_id": ..., "document_id": ..., "content": ..., "score": 0.91}, ...
  ],
  "sources": [
      {"document_id": ..., "title": ..., "url": ..., "author": ...,
       "published_at": "2025-11-10", "category": "음성복제", "score": 0.91}, ...
  ]
}
"""
from __future__ import annotations

from database.config import get_connection
from rag.embedding.embed import embed_texts
from rag.retrieval.exact_match_search import exact_match_search
from rag.retrieval.graph_search import graph_search
from rag.retrieval.hybrid_rrf import DEFAULT_K, reciprocal_rank_fusion
from rag.retrieval.keyword_search import keyword_search
from rag.retrieval.vector_search import vector_search

# 단일 채널만 짚었더라도 그 채널 안에서 확실히 상위(3위 이내)로 걸렸으면 통과시키는 점수 하한선.
# hybrid_rrf.py 계산대로 단일 채널 rank=1 ≈ 0.0164, rank=3 ≈ 0.0159, rank=10 ≈ 0.0143이라,
# 이 값(rank=3 기준)은 "그 채널이 확신을 갖고 상위로 올린 것"과 "10위권 근처에서 애매하게 걸린
# 것"을 가른다.
MIN_SINGLE_CHANNEL_SCORE = 1.0 / (DEFAULT_K + 3)

# 서로 다른 채널이 최소 몇 개 동시에 짚어야 "우연이 아니다"로 볼지.
MIN_CHANNELS_FOR_CORROBORATION = 2

# RRF에 넘기는 후보 풀은 최종 top_k보다 넉넉하게 뽑아서(필터링으로 일부가 빠져도 top_k를 채울
# 여지를 남김) 필터링 이후에 top_k로 자른다.
CANDIDATE_POOL_MIN = 20
CANDIDATE_POOL_MULTIPLIER = 4


def _fetch_sources(conn, document_ids: list[str], doc_scores: dict[str, float]) -> list[dict]:
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
            "score": doc_scores.get(str(r[0]), 0.0),
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

    2026-09-19: 최소 관련성 필터 — "2개 이상 채널이 동시에 짚었거나(우연이 아니라는 신호), 단일
    채널이어도 그 안에서 확실히 상위(rank<=3 수준)로 걸린" chunk만 통과시키고 나머지는
    contexts/sources에서 제외함. 단, embedding/Neo4j 등이 미설정이라 애초에 활성 채널이 1개뿐인
    상황(MVP 초기 등)에서는 "2개 채널 합의"를 요구하면 전부 걸러지는 사고가 나므로, 활성 채널이
    2개 이상일 때만 이 합의 규칙을 적용한다.
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

        # 필터링으로 일부가 걸러질 걸 감안해서 top_k보다 넉넉한 후보 풀을 RRF로 먼저 뽑는다.
        candidate_pool = max(top_k * CANDIDATE_POOL_MULTIPLIER, CANDIDATE_POOL_MIN)
        # exact_results를 두 번 넣어서 RRF 가중치를 강하게 줌(위 모듈 docstring 참고) — channel_count는
        # 동일 리스트 객체 기준으로 세므로 이 이중 전달이 채널 수를 부풀리진 않음(hybrid_rrf.py 참고).
        fused_candidates = reciprocal_rank_fusion(
            vec_results, kw_results, graph_results, exact_results, exact_results,
            top_k=candidate_pool,
        )

        # 실제로 신호를 낸 채널이 몇 개였는지 — vec/kw/graph/exact 중 결과가 있었던 것만 카운트.
        active_channels = sum(
            1 for results in (vec_results, kw_results, graph_results, exact_results) if results
        )
        require_corroboration = active_channels >= MIN_CHANNELS_FOR_CORROBORATION

        def _passes(r: dict) -> bool:
            if r["score"] >= MIN_SINGLE_CHANNEL_SCORE:
                return True
            return require_corroboration and r["channel_count"] >= MIN_CHANNELS_FOR_CORROBORATION

        fused = [r for r in fused_candidates if _passes(r)][:top_k]

        doc_scores: dict[str, float] = {}
        for r in fused:
            doc_id = str(r["document_id"])
            doc_scores[doc_id] = max(doc_scores.get(doc_id, 0.0), r["score"])

        sources = _fetch_sources(conn, list({r["document_id"] for r in fused}), doc_scores)

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
