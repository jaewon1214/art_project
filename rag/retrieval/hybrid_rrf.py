"""
RRF(Reciprocal Rank Fusion) — vector_search 결과와 keyword_search 결과를 순위 기반으로 결합.
정규화가 필요 없어서(점수 스케일이 안 맞는 문제를 피해서) MVP에는 이 방식을 채택.

score(chunk) = sum(1 / (k + rank_i))  — 여러 검색 방식 각각에서의 순위를 더함
"""
from __future__ import annotations

DEFAULT_K = 60


def reciprocal_rank_fusion(
    vector_results: list[dict],
    keyword_results: list[dict],
    k: int = DEFAULT_K,
    top_k: int = 10,
) -> list[dict]:
    """
    vector_results/keyword_results: [{"chunk_id", "document_id", "content", "rank"}, ...]
    반환: score 내림차순으로 정렬된 [{"chunk_id", "document_id", "content", "score"}, ...] (top_k개)
    """
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}

    for results in (vector_results, keyword_results):
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
