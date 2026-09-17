"""
검색 정확도 테스트. 지금은 seed.sql 데이터 기준 최소 동작 확인만 하는 스켈레톤 —
실제 문서가 쌓이면 "이 주제를 검색하면 이 문서가 top-k 안에 들어와야 한다" 식의
케이스를 늘려가는 걸 권장.
"""
from rag.retrieval.context_builder import search_context


def test_search_context_returns_expected_shape():
    result = search_context("음성복제 저작권")
    assert "contexts" in result
    assert "sources" in result
    assert isinstance(result["contexts"], list)
    assert isinstance(result["sources"], list)


def test_search_context_finds_seed_document():
    """seed.sql에 넣어둔 샘플 문서가 관련 키워드 검색에서 나오는지 확인 (키워드 검색만으로도 성립)."""
    result = search_context("AI 커버곡 저작권 침해")
    assert len(result["contexts"]) > 0, "seed 데이터 기준 검색 결과가 비어있습니다 — DB에 seed가 들어갔는지 확인하세요."


# TODO: embedding 모델 확정 후 —
#   - 벡터 검색만 껐을 때 / 켰을 때 결과 비교
#   - category 필터가 실제로 걸리는지
#   - RRF 결합 순위가 기대한 순서로 나오는지


# --- 2026-09-17: Concord Music Group v. Anthropic 사건 exact-match 회귀 테스트 -----------
#
# 배경: 3번(backend)이 "Concord Music Group"/"Universal Music Publishing"/"Concord v Anthropic"
# 같은 사건명 쿼리를 던졌을 때, 그 사건을 정면으로 다룬 문서가 아니라 그 사건을 "배경"으로만
# 짧게 언급하는 다른 소송(2026년 Sony/Warner v. Anthropic 등) 기사만 Top-K에 나오는 문제가
# 있었음 — 원인은 두 가지였음:
#   1) graph_search.py가 "매칭된 엔티티 개수"만 보고 랭킹해서, 회사명을 여럿 스쳐 언급
#      (MENTIONS)한 일반 기사가 사건 하나를 정면으로 다룬(DISCUSSES) 기사보다 위로 올라옴
#      -> 관계 타입(DISCUSSES/CITES/MENTIONS)과 엔티티 타입(Case 우대) 가중치를 추가해서 수정.
#   2) 애초에 Concord 사건 자체를 다룬 문서가 코퍼스에 없었음(일반 카테고리 수집 쿼리로는
#      랜드마크 사건의 1차 기사가 안 걸림) -> seed_concord_case_document.py로 문서 보강,
#      news_collector.py에 사건명 직접 쿼리 추가.
# 이 테스트는 seed_concord_case_document.py로 넣은 문서가 DB에 있다는 전제(1회성 수동 시드)
# 하에 위 두 수정이 앞으로도 유지되는지 확인함. document_id는 환경마다 새로 생성되는 UUID라
# 하드코딩할 수 없어서, sources의 title에 "Concord"와 "Anthropic"이 둘 다 들어있는지로 판별함
# (seed 문서 제목: "[사건 정리] Concord Music Group 외(UMG·ABKCO) v. Anthropic — ...").


def _has_concord_case_source(result: dict) -> bool:
    return any(
        "concord" in (s.get("title") or "").lower() and "anthropic" in (s.get("title") or "").lower()
        for s in result["sources"]
    )


def test_search_context_concord_case_direct_hit_by_full_name():
    """'Concord Music Group' + Anthropic 쿼리는 Concord 사건을 직접 다룬 문서가 Top-K에 나와야 함."""
    result = search_context("Concord Music Group Anthropic")
    assert _has_concord_case_source(result), (
        "Concord Music Group 쿼리인데 Concord 사건을 직접 다룬 문서가 결과에 없습니다 — "
        "graph_search/exact_match_search의 사건명 boost 로직이 퇴행했을 수 있습니다. "
        "(seed_concord_case_document.py로 시드 문서가 DB에 들어가 있는지도 먼저 확인할 것)"
    )


def test_search_context_concord_case_direct_hit_via_universal_and_concord():
    """'Universal Music Publishing' + Anthropic + Concord 조합 쿼리도 동일하게 확인."""
    result = search_context("Universal Music Publishing Anthropic Concord Music Group lawsuit")
    assert _has_concord_case_source(result)


def test_search_context_concord_case_direct_hit_short_form():
    """'Concord v Anthropic' 같은 짧은 사건명 축약형으로도 Concord 사건 문서가 잡혀야 함."""
    result = search_context("Concord v Anthropic")
    assert _has_concord_case_source(result)
