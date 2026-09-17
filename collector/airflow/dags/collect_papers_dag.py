"""
논문(arXiv + Semantic Scholar) 주기 수집 DAG — paper_collector.collect()를 스케줄대로 돌려서
rag.pipeline.ingest.ingest_document()로 자동 적재(관련성 판정 -> 저장 -> 번역(해당시) -> 청크 ->
임베딩 -> 엔티티 -> Neo4j)까지 실행.

collect_news_dag.py와 동일한 마운트/PYTHONPATH를 그대로 씀(collector/airflow/docker-compose.yml).

매일 1회로 충분함 — 새 논문이 몇 시간 단위로 쏟아지는 주제가 아니고, arXiv 공식 권장 사항(과호출
자제)과 Semantic Scholar 무료 공유 rate limit 보호를 위해서도 너무 자주 돌릴 필요 없음.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.insert(0, "/opt/airflow/project")


def _collect_papers() -> None:
    from collector.run_collectors import run_paper_only

    stats = run_paper_only()
    print(stats)


default_args = {
    "owner": "rag",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="collect_papers",
    description="arXiv + Semantic Scholar 논문 주기 수집 -> Postgres/Neo4j 자동 적재",
    default_args=default_args,
    schedule_interval=timedelta(days=1),  # 필요에 맞게 조정 (예: "@daily")
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["rag", "paper"],
) as dag:
    PythonOperator(
        task_id="collect_papers",
        python_callable=_collect_papers,
    )
