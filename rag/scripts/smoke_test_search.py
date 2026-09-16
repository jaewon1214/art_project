"""
검색 파이프라인 스모크 테스트 — 4개 카테고리(저작권/창작자성/음성복제/AI작곡)별로 대표 쿼리
하나씩 넣어서 search_context()가 그럴듯한 결과를 주는지 눈으로 확인하는 용도.

⚠️ 정량적 정확도 평가(precision/recall 같은 지표, ground truth 라벨링)를 하는 스크립트가
아님 — 그건 별도 작업(검색 정확도 테스트)으로 의도적으로 미뤄둔 부분이고, 이건 그냥
"검색이 0건이 아니고 내용이 주제랑 맞아 보이는가"를 빠르게 확인하는 스모크 테스트임.

실행 (secondpj 루트에서, 서버 DB 접속 가능한 PC에서):
    python -m rag.scripts.smoke_test_search
"""
from __future__ import annotations

import time

from rag.retrieval.context_builder import search_context

# 카테고리별 대표 쿼리 — documents.category 값(저작권/창작자성/음성복제/AI작곡)과 1:1 대응.
TEST_QUERIES: dict[str, str] = {
    "저작권": "생성형 AI 음악과 저작권 침해 문제",
    "창작자성": "AI 음악 창작에서 인간과 AI의 공동창작 및 저작자성",
    "음성복제": "AI 음성복제(보이스 클로닝) 기술과 법적 쟁점",
    "AI작곡": "텍스트 기반 AI 작곡 생성 모델",
}

SNIPPET_LEN = 100
TOP_K = 5


def _print_result(category: str, topic: str, result: dict, elapsed: float) -> None:
    contexts = result["contexts"]
    sources = {s["document_id"]: s for s in result["sources"]}

    print(f"\n{'=' * 70}")
    print(f"[{category}] 쿼리: {topic!r}  ({elapsed:.2f}초, {len(contexts)}건)")
    print("=" * 70)

    if not contexts:
        print("  ⚠️  결과 0건 — 임베딩 미설정(EMBEDDING_PROVIDER)이거나 관련 데이터 부족일 수 있음")
        return

    for i, ctx in enumerate(contexts[:TOP_K], start=1):
        src = sources.get(ctx["document_id"], {})
        snippet = ctx["content"][:SNIPPET_LEN].replace("\n", " ")
        print(f"  {i}. score={ctx['score']:.4f}  [{src.get('title', '(제목 없음)')}]")
        print(f"     출처: {src.get('url', '-')}")
        print(f"     내용: {snippet}...")


def main() -> None:
    print(f"검색 스모크 테스트 — 쿼리 {len(TEST_QUERIES)}개, 카테고리당 top {TOP_K}")

    for category, topic in TEST_QUERIES.items():
        start = time.time()
        try:
            result = search_context(topic, top_k=TOP_K)
        except Exception as e:  # noqa: BLE001 — 한 쿼리 실패해도 나머지는 계속 진행
            print(f"\n[{category}] 쿼리 실패: {e}")
            continue
        elapsed = time.time() - start
        _print_result(category, topic, result, elapsed)

    print(f"\n{'=' * 70}")
    print("끝. 각 카테고리마다 0건이 없고, 내용이 쿼리 주제랑 실제로 맞아 보이면 정상.")
    print("=" * 70)


if __name__ == "__main__":
    main()
