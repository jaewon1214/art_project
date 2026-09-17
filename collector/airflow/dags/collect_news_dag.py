"""
뉴스 RSS/API 주기 수집 DAG — news_collector.collect()를 스케줄대로 돌려서
rag.pipeline.ingest.ingest_document()로 자동 적재(관련성 판정 -> 저장 -> 임베딩 -> 엔티티 -> Neo4j)까지 실행.

로컬 PC의 Airflow(collector/airflow/docker-compose.yml, standalone 모드)에 이 파일이 그대로 마운트됨.
repo 루트 전체(collector/rag/database)가 컨테이너 안 /opt/airflow/project 에 마운트돼 있어서 여기서 바로 import 가능.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.insert(0, "/opt/airflow/project")


def _collect_news() -> None:
    from collector.run_collectors import run_news_only

    stats = run_news_only()
    print(stats)


default_args = {
    "owner": "rag",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="collect_news",
    description="뉴스 RSS/API 주기 수집 -> Postgres/Neo4j 자동 적재",
    default_args=default_args,
    schedule_interval=timedelta(hours=6),  # 필요에 맞게 조정 (예: "@daily")
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["rag", "news"],
) as dag:
    PythonOperator(
        task_id="collect_news",
        python_callable=_collect_news,
    )
