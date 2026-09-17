"""
기업 공식 자료(Suno/Udio/IFPI 등 ToS·가이드라인·보도자료) 주기 재확인 DAG.
official_collector.collect()를 스케줄대로 돌려서 rag.pipeline.ingest.ingest_document()로 자동 적재.

TARGET_PAGES가 고정 URL 목록이라(자동으로 새 페이지를 찾아오는 게 아니라 우리가 직접 큐레이션한
목록) 자주 돌 필요는 없음 — 같은 URL을 다시 읽어서 내용이 바뀌었는지(약관 개정 등) 확인하는
용도가 큼. content_hash 중복 체크 덕분에 내용이 안 바뀌었으면 재저장되지 않음.

주 1회로 설정.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.insert(0, "/opt/airflow/project")


def _collect_official() -> None:
    from collector.run_collectors import run_official_only

    stats = run_official_only()
    print(stats)


default_args = {
    "owner": "rag",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="collect_official",
    description="기업 공식 자료(Suno/Udio/IFPI 등) 주기 재확인 -> Postgres/Neo4j 자동 적재",
    default_args=default_args,
    schedule_interval=timedelta(days=7),  # 필요에 맞게 조정 (예: "@weekly")
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["rag", "official"],
) as dag:
    PythonOperator(
        task_id="collect_official",
        python_callable=_collect_official,
    )
