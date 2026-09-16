"""
검색 정확도 테스트 — precision@k를 사람이 직접 라벨링해서 측정하는 스크립트.

정적 ground-truth 세트를 미리 만들어두는 방식은 쓰지 않음 — DB에 계속 새 문서가
쌓이는 중이라 "이 쿼리엔 이 문서가 정답" 식으로 고정해두면 금방 낡아버림. 대신 매번
실제 search_context()를 돌려서 나온 top-k 결과를 그 자리에서 y/n으로 라벨링하고
precision@k를 계산 — 데이터가 늘어날 때마다(또는 검색 로직을 바꿀 때마다) 다시 돌려서
같은 쿼리 세트 기준으로 이전 결과와 비교하는 용도.

카테고리당 쿼리 2개, TOP_K=5 — search_context()가 실제로 반환하는 형식
({"contexts": [...], "sources": [...]})은 rag/retrieval/context_builder.py 참고.

실행 (secondpj 루트에서, 서버 DB 접속 가능한 PC에서):
    python -m rag.scripts.evaluate_search

카테고리 하나만 돌리고 싶으면:
    python -m rag.scripts.evaluate_search --category 저작권

결과는 rag/eval_results/eval_YYYYMMDD_HHMMSS.json 로 저장됨 — 나중에 검색 로직을
바꾼 뒤 다시 돌려서 이전 파일과 precision 수치를 비교해보면 됨.
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path

from rag.retrieval.context_builder import search_context

# 카테고리별 대표 쿼리 2개씩 — documents.category 값(저작권/창작자성/음성복제/AI작곡)과 1:1 대응.
TEST_QUERIES: dict[str, list[str]] = {
    "저작권": [
        "생성형 AI 음악과 저작권 침해 문제",
        "AI 음악 학습 데이터의 저작권 라이선스",
    ],
    "창작자성": [
        "AI 음악 창작에서 인간과 AI의 공동창작 및 저작자성",
        "AI 생성물에 저작자 지위를 인정할 수 있는가",
    ],
    "음성복제": [
        "AI 음성복제(보이스 클로닝) 기술과 법적 쟁점",
        "동의 없는 목소리 학습과 음성권 침해",
    ],
    "AI작곡": [
        "텍스트 기반 AI 작곡 생성 모델",
        "Suno Udio 등 AI 작곡 서비스 산업 동향",
    ],
}

TOP_K = 5
SNIPPET_LEN = 1000  # 2026-09-16: 150 -> 1000 (청크가 600단어로 커져서 150자론 문장 중간에 끊겨 판단이 안 됨)
RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval_results"


def _label_result(i: int, ctx: dict, source: dict) -> int:
    """검색 결과 하나를 화면에 보여주고 사람한테 관련성(y/n)을 물어봐서 1/0으로 반환.

    청크가 600단어 단위라 SNIPPET_LEN(1000자)도 넘는 경우가 있음 — 그럴 땐 끝에 [이하 생략]
    표시로 잘렸다는 걸 명확히 알려줌(예전처럼 "..."만 붙이면 문장이 중간에 끊긴 건지 실제로
    더 있는 건지 구분이 안 됐음). 콘솔 폭에 맞게 textwrap으로 줄바꿈도 같이 해줌."""
    raw = ctx["content"].replace("\n", " ").strip()
    truncated = len(raw) > SNIPPET_LEN
    snippet = raw[:SNIPPET_LEN]

    print(f"\n  [{i}] score={ctx['score']:.4f}")
    print(f"      제목: {source.get('title', '(제목 없음)')}")
    print(f"      출처: {source.get('url', '-')}")
    print(f"      카테고리: {source.get('category', '-')}")
    print("      내용:")
    wrapped = textwrap.fill(snippet, width=90, initial_indent="        ", subsequent_indent="        ")
    print(wrapped)
    if truncated:
        print(f"        [이하 생략 — 전체 {len(raw)}자 중 {SNIPPET_LEN}자까지만 표시]")

    while True:
        answer = input("      이 결과가 쿼리와 관련 있나요? (y/n/s=건너뛰기): ").strip().lower()
        if answer in ("y", "n"):
            return 1 if answer == "y" else 0
        if answer == "s":
            return -1  # 건너뛴 항목은 precision 계산에서 제외
        print("      y, n, s 중 하나로 입력해주세요.")


def _evaluate_query(category: str, query: str) -> dict:
    print(f"\n{'=' * 70}")
    print(f"[{category}] 쿼리: {query!r}")
    print("=" * 70)

    start = time.time()
    try:
        result = search_context(query, top_k=TOP_K)
    except Exception as e:  # noqa: BLE001 — 쿼리 하나 실패해도 나머지는 계속 진행
        print(f"  쿼리 실패: {e}")
        return {
            "category": category,
            "query": query,
            "error": str(e),
            "labels": [],
            "precision_at_k": None,
        }
    elapsed = time.time() - start

    contexts = result["contexts"]
    sources = {s["document_id"]: s for s in result["sources"]}

    if not contexts:
        print("  ⚠️  결과 0건 — 임베딩 미설정이거나 관련 데이터 부족일 수 있음")
        return {
            "category": category,
            "query": query,
            "elapsed_sec": round(elapsed, 2),
            "labels": [],
            "precision_at_k": None,
        }

    print(f"  ({elapsed:.2f}초, {len(contexts)}건)")

    labels = []
    for i, ctx in enumerate(contexts[:TOP_K], start=1):
        src = sources.get(ctx["document_id"], {})
        labels.append(_label_result(i, ctx, src))

    scored = [l for l in labels if l != -1]
    precision = sum(scored) / len(scored) if scored else None

    if precision is not None:
        print(f"\n  → precision@{len(scored)} = {precision:.2f} ({sum(scored)}/{len(scored)} 관련)")
    else:
        print("\n  → 전부 건너뜀 — precision 계산 불가")

    return {
        "category": category,
        "query": query,
        "elapsed_sec": round(elapsed, 2),
        "num_results": len(contexts),
        "labels": labels,
        "precision_at_k": precision,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="검색 정확도(precision@k) 사람 라벨링 테스트")
    parser.add_argument(
        "--category",
        choices=list(TEST_QUERIES.keys()),
        default=None,
        help="이 카테고리 쿼리만 테스트 (기본값: 전체)",
    )
    args = parser.parse_args()

    queries_to_run = (
        {args.category: TEST_QUERIES[args.category]} if args.category else TEST_QUERIES
    )
    total_queries = sum(len(qs) for qs in queries_to_run.values())

    print(f"검색 정확도 테스트 — 쿼리 {total_queries}개, 카테고리당 top {TOP_K}")
    print("각 결과가 쿼리 주제와 관련 있는지 y/n으로 답해주세요 (s는 건너뛰기).")

    all_results = []
    for category, queries in queries_to_run.items():
        for query in queries:
            all_results.append(_evaluate_query(category, query))

    # 카테고리별 + 전체 평균 precision 집계
    by_category: dict[str, list[float]] = {}
    for r in all_results:
        if r["precision_at_k"] is not None:
            by_category.setdefault(r["category"], []).append(r["precision_at_k"])

    print(f"\n{'=' * 70}")
    print("=== 카테고리별 평균 precision ===")
    for category, scores in by_category.items():
        avg = sum(scores) / len(scores)
        print(f"  {category}: {avg:.2f}  (쿼리 {len(scores)}개)")

    all_scores = [s for scores in by_category.values() for s in scores]
    overall = sum(all_scores) / len(all_scores) if all_scores else None
    if overall is not None:
        print(f"\n  전체 평균 precision@{TOP_K}: {overall:.2f}  (쿼리 {len(all_scores)}개 기준)")
    else:
        print("\n  전체 평균 precision: 계산 불가 (라벨링된 결과 없음)")
    print("=" * 70)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"eval_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "top_k": TOP_K,
                "results": all_results,
                "by_category_avg": {c: sum(s) / len(s) for c, s in by_category.items()},
                "overall_avg": overall,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n결과 저장됨: {out_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n중단됨.")
        sys.exit(1)
