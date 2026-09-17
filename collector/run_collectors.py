"""
collectors/*.collect()를 돌려서 나온 문서를 pipeline.ingest.ingest_document()로 하나씩 밀어넣는
운영 스크립트. "데이터 수집 → 자동 연결(관련성 판정 + Postgres + 엔티티 추출 + 임베딩 + Neo4j)"을
한 번에 실행. collector/airflow/dags/collect_news_dag.py가 run_news_only()를 그대로 재사용함.

사용법 (secondpj 루트에서):
    python -m collector.run_collectors            # news + policy + official + paper + case 전부
    python -m collector.run_collectors --news      # news_collector만
    python -m collector.run_collectors --papers    # paper_collector만 (arXiv + Semantic Scholar)
    python -m collector.run_collectors --official  # official_collector만
    python -m collector.run_collectors --policy    # policy_collector만
    python -m collector.run_collectors --case      # case_collector만 (판례, LAW_API_OC 설정 전까진 0건)
   (전부 Airflow DAG가 도는 것과 동일한 함수를 그대로 호출 — 수동으로 돌려도 청크 생성/임베딩까지
    ingest_document() 파이프라인을 그대로 타므로 자동 수집과 100% 동일하게 처리됨.)

collectors/*.py의 FEEDS/TARGET_PAGES가 아직 비어있으면 0건 수집되는 게 정상 — 실제 출처를
채운 뒤에 의미 있는 실행이 됨.
"""
from __future__ import annotations

import sys

from collector import case_collector, news_collector, official_collector, paper_collector, policy_collector
from rag.pipeline.ingest import ingest_document

COLLECTORS = [news_collector, official_collector, policy_collector, paper_collector, case_collector]


def run_collector(module) -> dict:
    """수집기 모듈 1개(collect() -> list[dict] 규약)를 돌려서 전부 ingest_document()로 밀어넣음."""
    name = module.__name__.rsplit(".", 1)[-1]
    stats = {
        "collected": 0,
        "inserted": 0,
        "duplicate": 0,
        "near_duplicate": 0,
        "irrelevant": 0,
        "failed": 0,
        "embedding_failed": 0,  # 2026-09-16: 저장은 됐지만(inserted) embedding만 실패한 문서 수 —
                                 # inserted에도 같이 잡히니 "inserted 중 몇 건은 재임베딩 필요"로 읽을 것.
    }

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
            if result.get("embedding_failed"):
                stats["embedding_failed"] += 1
        elif status == "duplicate":
            stats["duplicate"] += 1
        elif status == "near_duplicate":
            stats["near_duplicate"] += 1
            print(f"  근접중복으로 스킵 ({doc.get('url')}): 기존 '{result.get('similar_to')}'와 유사")
        elif status == "irrelevant":
            stats["irrelevant"] += 1
            print(f"  주제 무관으로 스킵 ({doc.get('url')}): {result.get('reason')}")

    return stats


def run_news_only() -> dict:
    """Airflow DAG(collect_news_dag.py)가 호출하는 진입점 — news_collector만 주기적으로 돌림."""
    return run_collector(news_collector)


def run_paper_only() -> dict:
    """Airflow DAG(collect_papers_dag.py)가 호출하는 진입점 — paper_collector만 주기적으로 돌림."""
    return run_collector(paper_collector)


def run_official_only() -> dict:
    """Airflow DAG(collect_official_dag.py)가 호출하는 진입점 — official_collector만 주기적으로 돌림."""
    return run_collector(official_collector)


def run_policy_only() -> dict:
    """Airflow DAG(collect_policy_dag.py)가 호출하는 진입점 — policy_collector만 주기적으로 돌림."""
    return run_collector(policy_collector)


def run_case_only() -> dict:
    """Airflow DAG(collect_case_dag.py)가 호출하는 진입점 — case_collector만 주기적으로 돌림.
    LAW_API_OC(.env) 미설정이면 case_collector.collect()가 빈 리스트를 반환하고 조용히 끝남."""
    return run_collector(case_collector)


def run_all() -> dict:
    """news + policy + official 전부 — 원본자료(policy/official)는 보통 최초 1회 수동 실행용."""
    total = {
        "collected": 0,
        "inserted": 0,
        "duplicate": 0,
        "near_duplicate": 0,
        "irrelevant": 0,
        "failed": 0,
        "embedding_failed": 0,
    }
    for module in COLLECTORS:
        stats = run_collector(module)
        for k in total:
            total[k] += stats[k]
    return total


def _print_summary(stats: dict) -> None:
    print(
        f"\n총 수집 {stats['collected']}건 — 신규 저장 {stats['inserted']}건, "
        f"중복 스킵 {stats['duplicate']}건, 근접중복 스킵 {stats['near_duplicate']}건, "
        f"주제무관 스킵 {stats['irrelevant']}건, 실패 {stats['failed']}건"
    )


def main() -> None:
    if "--news" in sys.argv:
        _print_summary(run_news_only())
    elif "--papers" in sys.argv:
        _print_summary(run_paper_only())
    elif "--official" in sys.argv:
        _print_summary(run_official_only())
    elif "--policy" in sys.argv:
        _print_summary(run_policy_only())
    elif "--case" in sys.argv:
        _print_summary(run_case_only())
    else:
        _print_summary(run_all())


if __name__ == "__main__":
    main()
