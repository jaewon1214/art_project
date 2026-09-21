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

2026-09-21: 위 필터를 실제 생성 논문 3건으로 역추적한 결과, 근거 문서가 2~3건까지 쪼그라드는
과도한 필터링이 확인됨 — 원인은 "활성 채널 2개 이상이면 합의(2채널 이상 동시 매칭) 요구"
조건이 vector/keyword라는 사실상 상시 활성인 baseline 2채널만으로도 그냥 켜져버리는 것.
graph/exact 채널이 니치 주제에서 구조적으로 자주 비어있는 현재 상황(Neo4j 엔티티 적재량 부족
— backfill_entity_extraction.py로 별도 보완 중)에서는, "활성 채널 2개"가 사실상 "vector와
keyword가 같은 chunk를 동시에 잡아야만 통과"를 의미하게 되어 의미적으로만 맞거나 형태소만
겹치는 정상적으로 관련 있는 문서까지 과도하게 걸러졌음. 그래서 합의 요구 기준을
"활성 채널 3개 이상"(=graph/exact 중 최소 하나가 실제로 신호를 냈을 때)으로 올리고, baseline
2채널만 활성인 상태에서는 단일채널 점수 기준 자체를 완화(rank<=3 -> rank<=6 수준)해서 대신
적용하도록 바꿈. graph 채널이 백필로 채워지면 활성 채널 3개 이상인 경우가 늘어 원래의 엄격한
합의 기준이 자연히 더 자주 적용되게 됨 — 이번 변경은 그 전까지의 임시 완화가 아니라, "합의를
요구하려면 합의할 대상이 실제로 있어야 한다"는 원칙에 맞춘 구조적 수정.

2026-09-21 (2차): 팀 피드백 2건을 추가로 반영.
(1) 다양성/적합도 — 위 필터를 통과한 chunk들이 종종 같은 문서 유형(예: 뉴스만, 혹은 같은
문서의 여러 chunk)으로 top_k가 채워져서 최종 참고문헌이 편중됨. _select_diverse()로
document_type(공식자료/논문/판례·법률자료/뉴스 등)이 골고루 섞이도록 문서당 최상위 chunk를
유형별 라운드로빈으로 고르고, distinct 문서 수가 top_k보다 적으면(니치 주제) 근거 개수가
줄지 않도록 남은 후보로 채운다. 최소 관련성 필터 다음, top_k로 자르기 전에 적용해야
"어차피 top_k 밖으로 밀릴 후보"까지 다양성 판단 대상에 넣을 수 있다.
(2) 주제와 다른 자료 검색 문제 — 게임 저작권 기사가 "저작권"/"AI" 단어 겹침만으로 음악 관련
검색에 섞여 들어오는 사례가 확인됨. 정규식 키워드 게이트(값싸지만 부정확)보다 정확한 방법으로,
rerank_by_relevance()(rag/retrieval/relevance_rerank.py)를 통해 최소 관련성 필터를 통과한
후보에 대해 LLM 1회 호출로 "주제와 실질적으로 관련 있는지"를 재판정한다. 다양성 선별보다
먼저 적용함 — 애초에 주제와 무관한 후보는 유형이 얼마나 다양하든 처음부터 뽑히면 안 되므로.
파이프라인 순서: 최소관련성필터(_passes) -> LLM 재판정(rerank_by_relevance) ->
유형다양성선별(_select_diverse, 여기서 top_k로 자름).

2026-09-21 (3차): category 하드 필터로 인한 근거 고갈 문제 수정. category가 주어지면
vector_search/keyword_search/exact_match_search 세 채널 모두 SQL 단계에서
"d.category = %s"(metadata_filter.build_filter)로 정확히 일치하는 문서만 후보가 되는데,
실측(2026-09-21, "한국 내 AI 창작물의 저작자 인정 기준" 논문 재검토)으로 확인한 문제: 수집
시점 카테고리 태깅이 4개 버킷(저작권/창작자성/음성복제/AI작곡)으로 성기게 나뉘다 보니, 주제상
명백히 관련 있는 문서 다수(예: 음저협 AI 음악 등록기준 기사 119건 중 117건)가 그 주제와 더
좁게 대응하는 카테고리(예: '창작자성')가 아니라 더 넓은 인접 카테고리(예: '저작권')로 분류돼
있어서, category로 필터링하면 코퍼스에 자료가 충분히 있어도(위 예시는 119건) SQL 단계에서
이미 후보가 1~2건으로 고갈됨 — 위 (1)(2)의 다양성/재판정 로직은 이 SQL 필터보다 뒤에서
동작하므로 아무리 개선해도 이 병목엔 영향을 못 준다. 그래서 category를 "하드 배제"가 아니라
"우선순위"로 바꿈: category로 먼저 찾고, 그 결과(distinct 문서 기준)가 아래 후보 풀 크기에
못 미치면 category 없이 한 번 더 검색해서 모자란 만큼만 보충한다(_merge_backfill). 이미
category-일치 후보가 rank 앞자리를 그대로 유지하므로 RRF에서 자연히 우선순위를 갖고, 보충분은
그 뒤로 이어붙는 것만 다르다 — category가 잘 맞을 때(넉넉한 경우)는 동작이 전혀 안 바뀐다.

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
from rag.retrieval.relevance_rerank import rerank_by_relevance
from rag.retrieval.vector_search import vector_search

# 단일 채널만 짚었더라도 그 채널 안에서 확실히 상위(3위 이내)로 걸렸으면 통과시키는 점수 하한선.
# hybrid_rrf.py 계산대로 단일 채널 rank=1 ≈ 0.0164, rank=3 ≈ 0.0159, rank=10 ≈ 0.0143이라,
# 이 값(rank=3 기준)은 "그 채널이 확신을 갖고 상위로 올린 것"과 "10위권 근처에서 애매하게 걸린
# 것"을 가른다. 활성 채널이 3개 이상(REQUIRE_CORROBORATION_MIN_ACTIVE_CHANNELS 이상)일 때만 씀.
MIN_SINGLE_CHANNEL_SCORE = 1.0 / (DEFAULT_K + 3)

# 2026-09-21 추가: vector+keyword만 활성인(=baseline 2채널만 신호를 낸) 상태에서 쓰는 완화된
# 단일채널 기준 — rank<=6 수준(1/(60+6)≈0.01515). 합의(다른 채널과의 corroboration)를 요구할
# 대상 자체가 없는 상황이라, 대신 순위 컷오프를 3위에서 6위로 넓혀서 지나치게 좁아지는 걸 막는다.
MIN_SINGLE_CHANNEL_SCORE_BASELINE_ONLY = 1.0 / (DEFAULT_K + 6)

# 서로 다른 채널이 최소 몇 개 동시에 짚어야 "우연이 아니다"로 볼지 — channel_count 기준.
MIN_CHANNELS_FOR_CORROBORATION = 2

# 2026-09-21 추가: "합의를 요구할지" 자체를 켜는 기준 — 활성 채널이 이 값 이상일 때만 위
# MIN_CHANNELS_FOR_CORROBORATION 합의 요구를 켠다. vector/keyword는 embedding/DB가 정상
# 설정된 한 사실상 상시 활성이라, "활성 채널 2개"만으로 합의를 요구하면 그 둘끼리의 합의만
# 요구하는 꼴이 되어버림(graph/exact가 구조적으로 자주 비는 니치 주제에서 과도한 필터링 유발
# — 2026-09-21 생성 논문 3건에서 근거 2~3건으로 쪼그라드는 현상으로 확인됨). 그래서 graph/exact
# 중 최소 하나가 실제로 신호를 낸 경우(활성 채널 3개 이상)에만 합의를 요구하도록 올림.
REQUIRE_CORROBORATION_MIN_ACTIVE_CHANNELS = 3

# RRF에 넘기는 후보 풀은 최종 top_k보다 넉넉하게 뽑아서(필터링으로 일부가 빠져도 top_k를 채울
# 여지를 남김) 필터링 이후에 top_k로 자른다.
CANDIDATE_POOL_MIN = 20
CANDIDATE_POOL_MULTIPLIER = 4


def _merge_backfill(primary: list[dict], backfill: list[dict]) -> list[dict]:
    """category로 찾은 primary 결과 뒤에, category 없이 다시 찾은 backfill 결과 중 primary에
    이미 없는 chunk만 이어붙인다. backfill 쪽 rank는 primary 뒤로 재부여해서(원래 자기 쿼리
    안에서의 순위를 그대로 쓰지 않음) category-일치 후보가 RRF 점수 계산에서 항상 우선하도록
    한다 — category가 잘 맞아서 primary만으로 충분한 경우엔 이 함수가 호출조차 안 되므로
    (search_context() 쪽 호출 조건 참고) 기존 동작에 영향이 없다."""
    seen = {r["chunk_id"] for r in primary}
    merged = list(primary)
    next_rank = len(primary) + 1
    for r in backfill:
        if r["chunk_id"] in seen:
            continue
        seen.add(r["chunk_id"])
        merged.append({**r, "rank": next_rank})
        next_rank += 1
    return merged


def _select_diverse(candidates: list[dict], top_k: int) -> list[dict]:
    """candidates(score 내림차순, 최소관련성필터+LLM재판정을 통과한 것들)에서 문서 유형
    (document_type)이 골고루 섞이도록 top_k개를 고른다.

    2026-09-21 추가 — 리뷰한 생성 논문 3건에서 판례/뉴스 등 유형이 섞이지 않고 같은 유형
    문서의 chunk 여러 개로 top_k가 채워지는 경우가 많았음(팀 피드백 "다양성/적합도" 항목).

    절차:
    1) 문서당 최상위(=먼저 나오는, score 내림차순이므로) chunk 하나만 남김 — 같은 문서의
       chunk를 여러 개 넣어봐야 "유형 다양성"에는 기여하지 않으므로.
    2) document_type별로 그룹을 나누고, 그룹이 처음 등장한 순서(=그 유형의 최고점 후보가
       먼저 나온 순서)를 유지한 채 그룹 간 라운드로빈으로 하나씩 뽑는다.
    3) distinct 문서 수 자체가 top_k보다 적어서 못 채웠으면(니치 주제 등), 다양성보다
       "근거 개수가 줄면 안 된다"가 우선이므로 이미 뽑힌 chunk를 제외한 나머지 후보
       (같은 문서의 다음 순위 chunk 포함)를 점수 순으로 채워 top_k를 맞춘다.
    """
    if not candidates:
        return candidates

    seen_docs: set[str] = set()
    best_per_doc: list[dict] = []
    for r in candidates:
        doc_id = r["document_id"]
        if doc_id in seen_docs:
            continue
        seen_docs.add(doc_id)
        best_per_doc.append(r)

    buckets: dict = {}
    order: list = []  # 버킷(유형) 등장 순서 — 그 유형의 최고점 후보가 먼저 나온 순서
    for r in best_per_doc:
        dtype = r.get("document_type")
        if dtype not in buckets:
            buckets[dtype] = []
            order.append(dtype)
        buckets[dtype].append(r)

    selected: list[dict] = []
    selected_chunk_ids: set[str] = set()
    idx = 0
    remaining = len(best_per_doc)
    while len(selected) < top_k and remaining > 0:
        dtype = order[idx % len(order)]
        if buckets[dtype]:
            r = buckets[dtype].pop(0)
            selected.append(r)
            selected_chunk_ids.add(r["chunk_id"])
            remaining -= 1
        idx += 1

    if len(selected) < top_k:
        for r in candidates:
            if len(selected) >= top_k:
                break
            if r["chunk_id"] in selected_chunk_ids:
                continue
            selected.append(r)
            selected_chunk_ids.add(r["chunk_id"])

    return selected[:top_k]


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
    REQUIRE_CORROBORATION_MIN_ACTIVE_CHANNELS(3) 이상일 때만 이 합의 규칙을 적용한다 —
    2026-09-21: 원래는 "활성 채널 2개 이상"이 기준이었는데, vector+keyword(사실상 상시 활성인
    baseline 2채널)만 켜진 상태에서도 합의를 요구해버려 니치 주제에서 근거가 과도하게 걸러지는
    문제가 실제 생성 논문에서 확인되어 3으로 올림. baseline 2채널만 활성일 때는 대신
    MIN_SINGLE_CHANNEL_SCORE_BASELINE_ONLY(rank<=6 수준)로 완화된 단일채널 기준을 적용한다.
    """
    with get_connection() as conn:
        query_embedding = None
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

        # 2026-09-21 (3차): category 하드 필터로 인한 근거 고갈 방지(위 모듈 docstring 참고).
        # category 일치 후보(distinct 문서 기준)가 candidate_pool보다 적으면, category 없이
        # 한 번 더 검색해서 모자란 만큼만 보충한다 — category가 잘 맞아서 이미 충분하면
        # (일반적인 경우) 여기서 더 할 일이 없어 기존 동작 그대로.
        if category is not None:
            distinct_docs = {r["document_id"] for r in vec_results + kw_results + exact_results}
            if len(distinct_docs) < candidate_pool:
                print(
                    f"[context_builder] category={category!r} 필터 후 후보 문서가 "
                    f"{len(distinct_docs)}건뿐(<{candidate_pool}) — category 없이 보충 검색합니다."
                )
                if query_embedding is not None:
                    vec_results = _merge_backfill(
                        vec_results, vector_search(conn, query_embedding, category=None, top_k=50)
                    )
                kw_results = _merge_backfill(
                    kw_results, keyword_search(conn, topic, category=None, top_k=50)
                )
                exact_results = _merge_backfill(
                    exact_results, exact_match_search(conn, topic, category=None, top_k=30)
                )

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
        # 2026-09-21: "활성 채널 2개"(=baseline인 vector+keyword만 켜진 상태)만으로 합의를
        # 요구하면 사실상 "둘 다 동시에 잡아야만 통과"가 되어 과도하게 걸러짐 — graph/exact 중
        # 최소 하나가 실제로 신호를 낸(활성 채널 3개 이상) 경우에만 합의를 요구하고, baseline
        # 2채널뿐일 때는 단일채널 기준 자체를 완화(rank<=3 -> rank<=6)해서 대신 적용한다.
        require_corroboration = active_channels >= REQUIRE_CORROBORATION_MIN_ACTIVE_CHANNELS
        single_channel_threshold = (
            MIN_SINGLE_CHANNEL_SCORE if require_corroboration else MIN_SINGLE_CHANNEL_SCORE_BASELINE_ONLY
        )

        def _passes(r: dict) -> bool:
            if r["score"] >= single_channel_threshold:
                return True
            return require_corroboration and r["channel_count"] >= MIN_CHANNELS_FOR_CORROBORATION

        # 파이프라인: 최소관련성필터 -> LLM 재판정(주제와 실질적으로 무관한 후보 제거) ->
        # 문서유형 다양성 선별(여기서 top_k로 자름). top_k 슬라이싱을 마지막으로 미루는 이유는
        # 앞 두 단계가 순서를 바꾸거나(다양성 선별) 일부를 제거할 수 있어서(재판정), 미리 잘라
        # 버리면 뒤 단계가 다룰 후보 자체가 부족해질 수 있기 때문.
        passed = [r for r in fused_candidates if _passes(r)]
        passed = rerank_by_relevance(topic, passed)
        fused = _select_diverse(passed, top_k)

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
