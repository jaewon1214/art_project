"""
DB 초기화 스모크 테스트 — docker compose up -d 로 DB가 떠 있어야 통과함.
실행: pytest tests/test_db_smoke.py  (또는 rag/ 루트에서 python -m tests.test_db_smoke)
"""
from database.config import get_connection

MVP_TABLES = ["sources", "documents", "chunks", "papers", "paper_citations"]


def _tables(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
        )
        return {r[0] for r in cur.fetchall()}


def test_pgvector_extension_installed():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension;")
        extensions = {r[0] for r in cur.fetchall()}
    assert "vector" in extensions, "pgvector(extension 'vector')가 설치되지 않았습니다."


def test_mvp_tables_exist():
    with get_connection() as conn:
        tables = _tables(conn)
    missing = set(MVP_TABLES) - tables
    assert not missing, f"MVP 테이블 누락: {missing}"


def test_citation_not_null_constraint():
    """paper_citations.claim_text가 NOT NULL인지 확인 — '근거 없는 문장 금지'의 DB단 강제."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'paper_citations' AND column_name = 'claim_text';
            """
        )
        row = cur.fetchone()
    assert row is not None, "paper_citations.claim_text 컬럼을 찾을 수 없습니다."
    assert row[0] == "NO", "paper_citations.claim_text가 NOT NULL이 아닙니다."


if __name__ == "__main__":
    test_pgvector_extension_installed()
    test_mvp_tables_exist()
    test_citation_not_null_constraint()
    print("모든 스모크 테스트 통과")
