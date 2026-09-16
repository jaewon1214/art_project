"""
판례(law.go.kr Open API) 주기 수집 DAG.
case_collector.collect()를 스케줄대로 돌려서 rag.pipeline.ingest.ingest_document()로 자동 적재.

⚠️ LAW_API_OC(.env)가 아직 없으면 case_collector.collect()가 빈 리스트를 반환하고 조용히
끝남 — open.law.go.kr 승인 전까지는 이 DAG를 켜둬도 매번 0건으로 끝날 뿐 에러는 안 남.
승인 나서 OC 값 넣으면 다음 스케줄부터 자동으로 수집 시작됨(코드 변경 불필요).

판례는 자주 새로 안 나오니 주 1회로 설정 (official/policy와 동일한 주기).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.insert(0, "/opt/airflow/project")


def _collect_case() -> None:
    from collector.run_collectors import run_case_only

    stats = run_case_only()
    print(stats)


default_args = {
    "owner": "rag",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="collect_case",
    description="판례(law.go.kr) 주기 수집 -> Postgres/Neo4j 자동 적재 (LAW_API_OC 설정 전까지는 0건)",
    default_args=default_args,
    schedule_interval=timedelta(days=7),
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["rag", "case"],
) as dag:
    PythonOperator(
        task_id="collect_case",
        python_callable=_collect_case,
    )
