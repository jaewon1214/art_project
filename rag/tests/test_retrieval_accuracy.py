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
