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

2026-09-16: 라벨링 결과를 쿼리당 bare int 리스트("labels": [1,0,1,...])로만 남기던 걸
청크별 레코드("chunk_results": [{chunk_id, document_id, title, score, label}, ...])로
바꿈 — 어떤 청크가 관련없다고 판정됐는지 나중에 다시 열어봐도 바로 추적 가능하게 하기 위함
(전엔 순서만 보고 어떤 청크였는지 역추적해야 했음). precision_at_k 계산 방식/의미는 그대로라
이전 결과 파일과 precision 수치 비교는 계속 유효함.

2026-09-17: 청크가 너무 길어서(600단어) 눈으로 훑기 힘들다는 피드백 -> "관련된 부분만
보여달라"는 요청이 있었는데, 그건 순환논리가 됨(뭐가 관련있는지 사람이 판단하게 하려고
만든 스크립트인데, 관련 부분을 미리 걸러 보여주면 그 판단을 스크립트가 먼저 해버리는 셈).
게다가 벡터검색으로 잡힌 청크는 쿼리와 글자 하나 안 겹쳐도(패러프레이즈) 의미상 관련될 수
있어서, 키워드 안 겹치는 부분을 무조건 숨기면 그런 청크가 통째로 안 보이게 될 위험도 있음.
그래서 내용은 그대로 다 보여주되(전체 정보 보존), 쿼리와 형태소 토큰이 겹치는 문장 앞에만
"▶" 표시를 달아서 눈이 먼저 갈 곳을 안내하는 절충안으로 구현(_mark_matching_sentences).
표시가 하나도 없다고 "무관하다"는 뜻은 아님(특히 벡터검색으로만 잡힌 청크) — 참고용 하이라이트일
뿐, 최종 판단은 여전히 사람이 전체 내용을 보고 함.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path

from rag.preprocessing.korean_tokenize import tokenize_for_search
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
RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval_results"

# preprocessing/translate.py의 _SENTENCE_SPLIT_RE와 동일한 기준(마침표/물음표/느낌표 뒤 공백) —
# 한국어 문장 종결어미(다/까/요 등)는 보통 그 뒤에 마침표가 붙어서 이 기준으로 충분히 갈라짐.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_MARK_PREFIX = "▶ "


def _mark_matching_sentences(text: str, query: str) -> list[tuple[bool, str]]:
    """text를 문장 단위로 쪼개서, 각 문장이 query와 형태소 토큰을 하나라도 공유하면
    (True, 문장) 아니면 (False, 문장)으로 표시. 검색에 실제 쓰인 형태소분석(korean_tokenize)과
    동일한 기준으로 비교해야 "저작권을"(청크) vs "저작권"(쿼리) 같은 조사 차이로 놓치지 않음.

    이건 참고용 하이라이트일 뿐 — 표시 안 된 문장을 숨기지 않고 그대로 다 보여주는 게 핵심
    (위 모듈 docstring 2026-09-17 참고). query 토큰화 결과가 비어있으면(예: 전부 특수문자)
    전부 표시 없음으로 반환 — 이 경우 화면엔 그냥 문장 구분만 있고 하이라이트는 안 뜸."""
    query_tokens = set(tokenize_for_search(query).split())
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if not query_tokens or not sentences:
        return [(False, text)] if text.strip() else []

    marked: list[tuple[bool, str]] = []
    for sentence in sentences:
        sentence_tokens = set(tokenize_for_search(sentence).split())
        marked.append((bool(query_tokens & sentence_tokens), sentence))
    return marked


def _label_result(i: int, ctx: dict, source: dict, query: str) -> dict:
    """검색 결과(청크 하나)를 화면에 보여주고 사람한테 관련성(y/n)을 물어봐서, 그 청크를
    나중에도 추적할 수 있도록 chunk_id/document_id 등 메타데이터를 라벨과 함께 dict로 반환.

    2026-09-16: 라벨만 반환하던 걸 청크별 레코드로 바꿈 — 결과 JSON을 나중에 다시 열어봤을 때
    "5개 중 3번째가 0이었다"가 아니라 "이 chunk_id가 관련없다고 판정됐다"를 바로 알 수 있게 함.

    2026-09-17: SNIPPET_LEN(글자수) 기준 추가 절단을 없앰 — ctx["content"]는 이미 chunks.content
    (chunker.py의 600단어 슬라이딩 윈도우) 그 자체라 이미 "청크 단위"로 경계가 정해진 텍스트인데,
    그 위에 또 1000자로 잘라서 보여주면 실제 검색에 쓰인 내용과 화면에 보이는 내용이 달라져서
    판단이 왜곡됨(예: 청크 앞부분이 사이트 잡음이고 실제 관련 내용은 뒷부분에 있는데 앞부분만
    보고 판단하게 되는 경우). 청크 하나는 원래도 화면에 다 못 띄울 만큼 길지 않으므로(문서
    전체가 아니라 그 문서의 한 조각) 전체를 그대로 보여줌 — 콘솔 폭에 맞게 textwrap만 적용.

    2026-09-17: 청크가 길 때(예: 2600자) 쿼리와 무관한 문장까지 다 읽어야 하는 문제를 논의한 끝에,
    내용을 자르거나 요약하지 않고 "쿼리와 토큰이 겹치는 문장 앞에 ▶ 표시"만 추가하는 방식(옵션 3)
    으로 결정함 — 자르기/요약은 판단 근거 자체를 조작하는 순환논리가 되지만, 표시는 실제 청크
    내용을 그대로 유지한 채 훑어보기만 돕는 것이라 안전함."""
    raw = ctx["content"].replace("\n", " ").strip()

    print(f"\n  [{i}] score={ctx['score']:.4f}")
    print(f"      제목: {source.get('title', '(제목 없음)')}")
    print(f"      출처: {source.get('url', '-')}")
    print(f"      카테고리: {source.get('category', '-')}")
    print(f"      내용 ({len(raw)}자, 청크 전체, ▶ = 쿼리와 겹치는 문장):")
    for is_match, sentence in _mark_matching_sentences(raw, query):
        prefix = _MARK_PREFIX if is_match else "        "
        wrapped = textwrap.fill(
            sentence.strip(),
            width=90,
            initial_indent=prefix,
            subsequent_indent="        ",
        )
        print(wrapped)

    while True:
        answer = input("      이 결과가 쿼리와 관련 있나요? (y/n/s=건너뛰기): ").strip().lower()
        if answer in ("y", "n", "s"):
            label = 1 if answer == "y" else 0 if answer == "n" else -1  # s(건너뛰기)는 precision 계산에서 제외
            return {
                "rank": i,
                "chunk_id": ctx.get("chunk_id"),
                "document_id": ctx.get("document_id"),
                "title": source.get("title"),
                "url": source.get("url"),
                "category": source.get("category"),
                "score": ctx["score"],
                "label": label,
            }
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
            "chunk_results": [],
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
            "chunk_results": [],
            "precision_at_k": None,
        }

    print(f"  ({elapsed:.2f}초, {len(contexts)}건)")

    chunk_results = []
    for i, ctx in enumerate(contexts[:TOP_K], start=1):
        src = sources.get(ctx["document_id"], {})
        chunk_results.append(_label_result(i, ctx, src, query))

    scored = [c["label"] for c in chunk_results if c["label"] != -1]
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
        "chunk_results": chunk_results,
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
