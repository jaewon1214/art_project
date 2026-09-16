"""
DB 데이터 현황 점검 스크립트 — 세션에서는 DB(43.203.178.125:5432)에 직접 접근을 못 해서
(TCP 아웃바운드가 막혀있음), 사용자가 로컬에서 돌려서 결과를 다시 붙여넣는 용도로 만듦.

documents 테이블을 document_type x category로 교차 집계하고, 최근 적재 문서 10건,
그리고 chunks/embeddings이 없는(=ingest 파이프라인이 끝까지 안 간) 문서가 있는지도 같이 확인.

실행 (secondpj 루트에서, DB 접속 가능한 PC에서):
    python -m rag.scripts.db_stats
"""
from __future__ import annotations

from database.config import get_connection


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
