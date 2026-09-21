"""
document_entities에 한 건도 없는(=엔티티 추출이 한 번도 안 된 것으로 추정되는) 기존 문서를
찾아서 LLM로 엔티티/관계를 추출하고 Postgres(entities/document_entities) + Neo4j에 반영하는
백필 스크립트.

배경: pipeline/ingest.py는 새로 들어오는 문서마다 관련성판정과 같은 LLM 호출 1번으로 엔티티도
같이 추출/저장하지만(entity_extraction/sync.py), 그 기능이 붙기 전에 이미 저장돼 있던 문서나
LLM_PROVIDER/NEO4J_URI가 아직 설정 안 됐던 시점에 들어온 문서는 entities/document_entities에
아무 행도 없는 채로 남아있을 수 있음. "Neo4j 그래프 채널이 엔티티 적재량 부족으로 검색에서
보조적 역할"이라는 한계를 메우기 위한 백필.

⚠️ 판별 기준의 한계: document_entities에 행이 없는 것 = "추출을 아예 안 했다" 라는 뜻일 수도
있고, "추출은 했는데 LLM이 엔티티를 하나도 못 찾았다"는 뜻일 수도 있음 — 스키마에 "추출
시도 여부" 자체를 남기는 플래그가 없어서 이 스크립트는 구분하지 못하고 둘 다 재처리 대상으로
잡음(중복 LLM 호출 약간 발생 가능하지만, 이 프로젝트 주제 특성상 관련 문서에 엔티티가 0개로
나오는 경우는 드물어서 실질적 낭비는 적을 것으로 예상).

문서 1건당 LLM 호출 1번(비용 발생) — 기본은 미리보기(대상 건수/제목만 보여주고 끝), --apply로
실제 반영, --limit으로 건수 제한(전체 실행 전 소규모 확인 권장 — backfill_fix_audit_20260919.py
등 기존 백필 스크립트들과 동일한 안전장치 패턴).

실행 (secondpj 루트에서, DB 접속 가능한 PC에서):
    python -m rag.scripts.backfill_entity_extraction                    # 미리보기(대상 건수만)
    python -m rag.scripts.backfill_entity_extraction --apply --limit 20 # 소규모 확인 권장
    python -m rag.scripts.backfill_entity_extraction --apply            # 전체 반영
"""
from __future__ import annotations

import argparse
import time

from rag import config
from rag.entity_extraction import extractor
from rag.entity_extraction.sync import store_extraction
from database.neo4j.loader import load_entities, load_relations

INTERVAL_SEC = 1  # LLM 호출 사이 최소 간격(레이트리밋 안전마진)


def _find_missing(conn, limit: int | None) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.title, d.content, d.document_type, d.category, d.published_at
            FROM documents d
            LEFT JOIN document_entities de ON de.document_id = d.id
            WHERE de.id IS NULL
            GROUP BY d.id, d.title, d.content, d.document_type, d.category, d.published_at
            ORDER BY d.created_at;
            """
        )
        rows = cur.fetchall()
    return rows[:limit] if limit else rows


def main() -> None:
    parser = argparse.ArgumentParser(description="엔티티 추출 안 된 기존 문서 백필")
    parser.add_argument(
        "--apply", action="store_true",
        help="실제로 LLM 호출 + DB/Neo4j 반영(기본은 대상 건수만 미리보기, 아무것도 바꾸지 않음)",
    )
    parser.add_argument("--limit", type=int, default=None, help="처리할 최대 문서 수(테스트용, 기본 전체)")
    args = parser.parse_args()

    if not config.LLM_PROVIDER:
        print("LLM_PROVIDER가 .env에 설정되지 않았습니다 — 엔티티를 추출할 수 없습니다.")
        return

    with config.get_connection() as conn:
        rows = _find_missing(conn, args.limit)
        if not rows:
            print("document_entities가 비어있는 문서 없음 — 백필할 것 없습니다.")
            return

        print(
            f"엔티티 미추출(추정) 문서 {len(rows)}건 발견"
            + (f" (--limit {args.limit} 적용)" if args.limit else "")
        )

        if not args.apply:
            print("미리보기 모드입니다 — 실제로 반영하려면 --apply를 붙여서 다시 실행하세요.")
            for doc_id, title, _content, doc_type, category, _pub in rows[:10]:
                print(f"  - [{doc_type}/{category}] {title[:60]!r}")
            if len(rows) > 10:
                print(f"  ... 외 {len(rows) - 10}건")
            return

        if not config.NEO4J_URI:
            print(
                "⚠️ NEO4J_URI가 .env에 설정되지 않았습니다 — entities/document_entities(Postgres)는 "
                "채워지지만 Neo4j 동기화는 건너뜁니다."
            )

        succeeded = 0
        skipped_irrelevant = 0
        failed = 0
        for i, (doc_id, title, content, doc_type, category, published_at) in enumerate(rows, start=1):
            try:
                extraction = extractor.analyze_document(content, document_type=doc_type)
            except Exception as e:  # noqa: BLE001 — 이 문서만 실패, 나머지는 계속 진행
                print(f"[{i}/{len(rows)}] LLM 호출 실패({e}) — [{doc_type}] {title[:40]!r}")
                failed += 1
                time.sleep(INTERVAL_SEC)
                continue

            if not extraction.get("is_relevant"):
                # 이미 저장된 문서라 여기서 지우지는 않음(관련성 재검토는 별도 감사 대상) —
                # 엔티티 추출만 스킵.
                print(f"[{i}/{len(rows)}] 현재 기준 무관 판정 — entities 없이 스킵 — [{doc_type}] {title[:40]!r}")
                skipped_irrelevant += 1
                time.sleep(INTERVAL_SEC)
                continue

            doc_meta = {"title": title, "category": category, "published_at": published_at}
            entities_for_graph, relations_for_graph = store_extraction(conn, doc_id, doc_meta, extraction)
            conn.commit()

            if config.NEO4J_URI and entities_for_graph:
                load_entities(entities_for_graph)
                load_relations(relations_for_graph)

            succeeded += 1
            print(
                f"[{i}/{len(rows)}] 완료 — [{doc_type}] {title[:40]!r} "
                f"(entities {len(entities_for_graph)}건, relations {len(relations_for_graph)}건)"
            )
            time.sleep(INTERVAL_SEC)

    print(f"\n끝 — 성공 {succeeded}건, 무관판정 스킵 {skipped_irrelevant}건, 실패 {failed}건")
    if failed:
        print("실패분은 API 상태 확인 후 스크립트를 다시 돌리면 됨(이미 entities 채워진 문서는 다음 실행 대상에서 자동 제외).")


if __name__ == "__main__":
    main()
