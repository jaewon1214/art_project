"""
collectors/*.collect()를 돌려서 나온 문서를 pipeline.ingest.ingest_document()로 하나씩 밀어넣는
운영 스크립트. "데이터 수집 → 자동 연결(관련성 판정 + Postgres + 엔티티 추출 + 임베딩 + Neo4j)"을
한 번에 실행. airflow/dags/collect_news_dag.py가 run_collector(news_collector)를 그대로 재사용함.

사용법 (rag/ 에서):
    python -m scripts.run_collectors          # news + policy + official 전부
    python -m scripts.run_collectors --news    # news_collector만 (Airflow DAG가 도는 것과 동일)

collectors/*.py의 FEEDS/TARGET_PAGES가 아직 비어있으면 0건 수집되는 게 정상 — 실제 출처를
채운 뒤에 의미 있는 실행이 됨.
"""
from __future__ import annotations

import sys

from collector import news_collector, official_collector, paper_collector, policy_collector
from rag.pipeline.ingest import ingest_document

COLLECTORS = [news_collector, official_collector, policy_collector, paper_collector]


def run_collector(module) -> dict:
    """수집기 모듈 1개(collect() -> list[dict] 규약)를 돌려서 전부 ingest_document()로 밀어넣음."""
    name = module.__name__.rsplit(".", 1)[-1]
    stats = {"collected": 0, "inserted": 0, "duplicate": 0, "irrelevant": 0, "failed": 0}

    try:
        docs = module.collect()
    except Exception as e:  # noqa: BLE001 — 수집기 실패해도 호출부(DAG 등)는 계속 돌 수 있게 예외를 밖으로 던지지 않음
        print(f"[{name}] collect() 실패: {e}")
        return stats

    print(f"[{name}] {len(docs)}건 수집")
    stats["collected"] = len(docs)

    for doc in docs:
        try:
            result = ingest_document(doc)
        except Exception as e:  # noqa: BLE001
            print(f"  실패 ({doc.get('url')}): {e}")
            stats["failed"] += 1
            continue

        status = result["status"]
        if status == "inserted":
            stats["inserted"] += 1
        elif status == "duplicate":
            stats["duplicate"] += 1
        elif status == "irrelevant":
            stats["irrelevant"] += 1
            print(f"  주제 무관으로 스킵 ({doc.get('url')}): {result.get('reason')}")

    return stats


def run_news_only() -> dict:
    """Airflow DAG(collect_news_dag.py)가 호출하는 진입점 — news_collector만 주기적으로 돌림."""
    return run_collector(news_collector)


def run_all() -> dict:
    """news + policy + official 전부 — 원본자료(policy/official)는 보통 최초 1회 수동 실행용."""
    total = {"collected": 0, "inserted": 0, "duplicate": 0, "irrelevant": 0, "failed": 0}
    for module in COLLECTORS:
        stats = run_collector(module)
        for k in total:
            total[k] += stats[k]
    return total


def _print_summary(stats: dict) -> None:
    print(
        f"\n총 수집 {stats['collected']}건 — 신규 저장 {stats['inserted']}건, "
        f"중복 스킵 {stats['duplicate']}건, 주제무관 스킵 {stats['irrelevant']}건, "
        f"실패 {stats['failed']}건"
    )


def main() -> None:
    if "--news" in sys.argv:
        _print_summary(run_news_only())
    else:
        _print_summary(run_all())


if __name__ == "__main__":
    main()
