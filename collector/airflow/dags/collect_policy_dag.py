"""
정책/법령 자료(한국저작권위원회, US Copyright Office, EU AI Act, WIPO, 영국정부 등) 주기 재확인 DAG.
policy_collector.collect()를 스케줄대로 돌려서 rag.pipeline.ingest.ingest_document()로 자동 적재.

원래는 official_collector와 같은 이유로(고정 URL 목록 재확인 용도) 주 1회였는데, 2026-09-16에
policy_collector.collect()에 한국저작권위원회 보도자료 RSS가 추가되면서 매일 도는 게 나아짐
(정적 URL 재확인은 어차피 content_hash로 완전중복 스킵돼서 매일 돌려도 비용 거의 안 늚 — 새
보도자료가 있을 때만 LLM 관련성판정 호출이 실제로 발생함). 그래서 papers/news와 동일하게 1일로 변경.
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
    schedule_interval=timedelta(days=1),  # 2026-09-16: RSS 추가로 주1회->매일 (필요에 맞게 조정)
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["rag", "policy"],
) as dag:
    PythonOperator(
        task_id="collect_policy",
        python_callable=_collect_policy,
    )
