"""
RRF(Reciprocal Rank Fusion) — vector_search / keyword_search / graph_search 결과를
순위 기반으로 결합. 정규화가 필요 없어서(점수 스케일이 안 맞는 문제를 피해서) MVP에는 이 방식을 채택.

score(chunk) = sum(1 / (k + rank_i))  — 참여한 검색 방식 각각에서의 순위를 더함.
검색 방식이 vector+keyword 2개에서 vector+keyword+graph 3개로 늘어나도 이 함수는 안 바뀌게
가변 인자로 설계함 — 결과 리스트를 몇 개를 넘기든 동일하게 동작.

2026-09-19: channel_count 필드 추가 — "몇 개의 서로 다른 검색 경로(채널)에서 이 chunk가
나왔는지"를 반환값에 같이 실어줌(context_builder.py의 최소 관련성 필터에서 씀: 여러 채널이
동시에 짚은 문서는 우연히 걸렸을 가능성이 낮고, 한 채널에서만 걸린 건 그 한 채널의 애매한
순위일 수 있음). 채널 판단은 "같은 리스트 객체(id)가 몇 번 다르게 넘어왔는지"로 셈 —
context_builder.py가 exact_match_search 결과를 가중치 목적으로 두 번 넣는데(동일 리스트
객체를 그대로 두 번 전달), 그걸 채널 2개로 잘못 세면 exact-only 매칭이 "복수 채널 합의"로
둔갑해버리므로, list_id 기준으로 세면 같은 객체가 몇 번 들어오든 채널 1개로 정확히 잡힘.
반대로 vector/keyword처럼 서로 다른 리스트 객체는 각각 다른 채널로 정상 카운트됨.

2026-09-21: 반환 딕셔너리에 document_type 필드 추가 — vector/keyword/graph/exact_match
네 검색 함수 모두 이제 SELECT에 documents.document_type을 포함해서 반환하는데(각 모듈의
2026-09-21 코멘트 참고), meta[cid]에는 그 원본 dict가 그대로 저장되므로 값 자체는 이미 들어와
있었지만 이 함수의 반환 dict는 필드를 하나하나 명시적으로 골라서 만들기 때문에 document_type을
여기서도 명시적으로 뽑아주지 않으면 새로 만들어지는 반환 dict에서는 그냥 사라짐 — 아래처럼
직접 추가해야 context_builder.py의 문서유형 다양성 선별 로직까지 흘러감.
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
        [{"chunk_id", "document_id", "content", "document_type", "rank"}, ...] 리스트를
        원하는 개수만큼 넘기면 됨.
    반환: score 내림차순으로 정렬된
        [{"chunk_id", "document_id", "content", "document_type", "score", "channel_count"}, ...]
        (top_k개)
    """
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}
    channel_ids: dict[str, set[int]] = {}

    for results in result_lists:
        list_id = id(results)  # 동일 리스트 객체가 두 번 넘어와도 채널 1개로 셈(위 docstring 참고)
        for r in results:
            cid = r["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + r["rank"])
            meta.setdefault(cid, r)  # content/document_id는 처음 본 결과 기준으로 저장
            channel_ids.setdefault(cid, set()).add(list_id)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [
        {
            "chunk_id": cid,
            "document_id": meta[cid]["document_id"],
            "content": meta[cid]["content"],
            "document_type": meta[cid].get("document_type"),
            "score": score,
            "channel_count": len(channel_ids[cid]),
        }
        for cid, score in ranked
    ]
