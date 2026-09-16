"""
정책/법령 자료(한국저작권위원회, US Copyright Office, EU AI Act, WIPO, 영국정부 등) 주기 재확인 DAG.
policy_collector.collect()를 스케줄대로 돌려서 rag.pipeline.ingest.ingest_document()로 자동 적재.

official_collector와 같은 이유로(고정 URL 목록 재확인 용도) 주 1회로 설정.
국가법령정보 Open API가 policy_collector에 붙으면(TODO) 그쪽은 갱신 빈도가 다를 수 있으니
그때 이 DAG 스케줄을 다시 검토할 것.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

sys.path.insert(0, "/opt/airflow/project")


def _collect_policy() -> None:
    from collector.run_collectors import run_policy_only

    stats = run_policy_only()
    print(stats)


default_args = {
    "owner": "rag",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="collect_policy",
    description="정책/법령 자료(국내+해외) 주기 재확인 -> Postgres/Neo4j 자동 적재",
    default_args=default_args,
    schedule_interval=timedelta(days=7),  # 필요에 맞게 조정 (예: "@weekly")
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["rag", "policy"],
) as dag:
    PythonOperator(
        task_id="collect_policy",
        python_callable=_collect_policy,
    )
