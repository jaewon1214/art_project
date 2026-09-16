"""
RRF(Reciprocal Rank Fusion) — vector_search / keyword_search / graph_search 결과를
순위 기반으로 결합. 정규화가 필요 없어서(점수 스케일이 안 맞는 문제를 피해서) MVP에는 이 방식을 채택.

score(chunk) = sum(1 / (k + rank_i))  — 참여한 검색 방식 각각에서의 순위를 더함.
검색 방식이 vector+keyword 2개에서 vector+keyword+graph 3개로 늘어나도 이 함수는 안 바뀌게
가변 인자로 설계함 — 결과 리스트를 몇 개를 넘기든 동일하게 동작.
"""
from __future__ import annotations

DEFAULT_K = 60


def reciprocal_rank_fusion(
    *result_lists: list[dict],
    k: int = DEFAULT_K,
    top_k: int = 10,
) -> list[dict]:
    """
    result_lists: vector_search/keyword_search/graph_search가 반환하는 형식과 동일한
        [{"chunk_id", "document_id", "content", "rank"}, ...] 리스트를 원하는 개수만큼 넘기면 됨.
    반환: score 내림차순으로 정렬된 [{"chunk_id", "document_id", "content", "score"}, ...] (top_k개)
    """
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}

    for results in result_lists:
        for r in results:
            cid = r["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + r["rank"])
            meta.setdefault(cid, r)  # content/document_id는 처음 본 결과 기준으로 저장

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [
        {
            "chunk_id": cid,
            "document_id": meta[cid]["document_id"],
            "content": meta[cid]["content"],
            "score": score,
        }
        for cid, score in ranked
    ]
