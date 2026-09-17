"""
DB 데이터 현황 점검 스크립트 — 세션에서는 DB(43.203.178.125:5432)에 직접 접근을 못 해서
(TCP 아웃바운드가 막혀있음), 사용자가 로컬에서 돌려서 결과를 다시 붙여넣는 용도로 만듦.

documents 테이블을 document_type x category로 교차 집계하고, 최근 적재 문서 10건,
그리고 chunks/embeddings이 없는(=ingest 파이프라인이 끝까지 안 간) 문서가 있는지도 같이 확인.

2026-09-16 추가: published_at 기준 "과거/최신 데이터" 분포 — "논문은 과거 데이터라 파인튜닝이
낫고 RAG는 최신 데이터만 맡아야 한다"는 팀 논의에 실제 숫자로 답하기 위한 섹션. LLM_MODEL
(.env, entity_extraction/translate에 쓰는 모델)의 학습 컷오프를 기준선으로 두고, 그 이전/이후로
수집 문서가 몇 건씩 있는지 document_type별로 보여줌 — "논문 중에도 컷오프 이후(=모델이 모르는)
문서가 몇 건이나 되는지"가 바로 이 표에서 나옴.

실행 (secondpj 루트에서, DB 접속 가능한 PC에서):
    python -m rag.scripts.db_stats
"""
from __future__ import annotations

from database.config import get_connection

# gpt-4o-mini 기준 대략적인 학습 데이터 컷오프 — OpenAI가 정확한 날짜를 못박아 공개하진 않아서
# "2023-10-01"은 공식적으로 알려진 대략값(대외 문서 기준)임. LLM_MODEL을 나중에 바꾸면 이 값도
# 같이 갱신할 것 — 정확한 컷오프가 아니라 "이 언저리부터는 모델이 몰랐을 가능성이 높다"는
# 참고선(reference line) 용도로만 씀.
KNOWLEDGE_CUTOFF = "2023-10-01"


def _print_table(headers: list[str], rows: list[tuple]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        print(fmt.format(*row))


def main() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM documents;")
            total = cur.fetchone()[0]
            print(f"documents 총 {total}건\n")

            print("=== document_type별 ===")
            cur.execute(
                "SELECT document_type, count(*) FROM documents GROUP BY document_type ORDER BY count(*) DESC;"
            )
            _print_table(["document_type", "count"], cur.fetchall())

            print("\n=== category별 ===")
            cur.execute(
                "SELECT category, count(*) FROM documents GROUP BY category ORDER BY count(*) DESC;"
            )
            _print_table(["category", "count"], cur.fetchall())

            print("\n=== document_type x category 교차표 ===")
            cur.execute(
                """
                SELECT document_type, category, count(*)
                FROM documents
                GROUP BY document_type, category
                ORDER BY document_type, category;
                """
            )
            _print_table(["document_type", "category", "count"], cur.fetchall())

            print("\n=== chunks/embedding 없는 문서 (ingest 미완료 의심) ===")
            cur.execute(
                """
                SELECT d.document_type, count(*)
                FROM documents d
                LEFT JOIN chunks c ON c.document_id = d.id
                WHERE c.id IS NULL
                GROUP BY d.document_type
                ORDER BY count(*) DESC;
                """
            )
            rows = cur.fetchall()
            if rows:
                _print_table(["document_type", "chunk 없는 문서 수"], rows)
            else:
                print("없음 — 전부 chunk까지 생성됨")

            print("\n=== embedding 없는 chunk (임베딩 실패로 박제됐을 가능성) ===")
            cur.execute(
                """
                SELECT d.document_type, count(*)
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.embedding IS NULL
                GROUP BY d.document_type
                ORDER BY count(*) DESC;
                """
            )
            rows = cur.fetchall()
            if rows:
                _print_table(["document_type", "embedding 없는 chunk 수"], rows)
                print("  -> python -m rag.scripts.backfill_missing_embeddings 로 재계산 가능")
            else:
                print("없음 — 전부 embedding까지 채워짐")

            print(f"\n=== published_at 기준 과거/최신 분포 (기준선: {KNOWLEDGE_CUTOFF}, LLM 학습 컷오프 대략값) ===")
            cur.execute(
                """
                SELECT
                    document_type,
                    count(*) FILTER (WHERE published_at IS NULL) AS 날짜없음,
                    count(*) FILTER (WHERE published_at < %s) AS 컷오프이전,
                    count(*) FILTER (WHERE published_at >= %s) AS 컷오프이후,
                    min(published_at) AS 최고령,
                    max(published_at) AS 최신
                FROM documents
                GROUP BY document_type
                ORDER BY document_type;
                """,
                (KNOWLEDGE_CUTOFF, KNOWLEDGE_CUTOFF),
            )
            _print_table(
                ["document_type", "날짜없음", "컷오프이전(구지식)", "컷오프이후(신지식)", "최고령", "최신"],
                cur.fetchall(),
            )

            print("\n=== 최근 적재 문서 10건 ===")
            cur.execute(
                """
                SELECT created_at, document_type, category, title
                FROM documents
                ORDER BY created_at DESC
                LIMIT 10;
                """
            )
            _print_table(
                ["created_at", "type", "category", "title"],
                [(str(r[0])[:19], r[1], r[2], (r[3] or "")[:50]) for r in cur.fetchall()],
            )


if __name__ == "__main__":
    main()
