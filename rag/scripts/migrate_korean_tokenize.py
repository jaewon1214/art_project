"""
한국어 형태소 분석 도입 마이그레이션 — 이미 운영 중인 DB(43.203.178.125)에 스키마 변경을
적용하고 기존 chunks를 전부 재토큰화하는 일회성 스크립트.

database/init/01_schema.sql은 "새로 DB를 만들 때"만 적용되는 초기화 스크립트라
(docker-entrypoint-initdb.d 관례상 빈 볼륨에서만 실행됨) 이미 데이터가 있는 지금 서버에는
자동으로 반영이 안 됨 — 그래서 이 스크립트로 직접 ALTER를 실행함.

하는 일:
  1. chunks.content_tokenized TEXT 컬럼 추가
  2. chunks.content_tsv(GENERATED)를 content 기준 -> content_tokenized 기준으로 재정의
     (Postgres는 GENERATED 컬럼의 생성식을 ALTER로 못 바꿔서 DROP 후 다시 ADD해야 함 —
     content_tsv에 걸려있던 GIN 인덱스도 같이 지워졌다가 새로 생성됨)
  3. 기존 chunks 전부 content_tokenized를 채움(kiwipiepy로 재계산) — 이 UPDATE가 끝나야만
     content_tsv(GENERATED)도 새 값으로 다시 계산됨

실행 전 꼭 확인:
  - kiwipiepy가 설치돼 있어야 함(pip install -e . 다시 하면 pyproject.toml에 추가된 걸로 설치됨)
  - 이 스크립트는 한 번만 실행하면 됨 — 다시 돌려도 안전하긴 함(멱등적: 컬럼/인덱스가 이미
    있으면 건너뜀, content_tokenized는 매번 재계산해서 덮어씀)

실행 (secondpj 루트에서):
    python -m rag.scripts.migrate_korean_tokenize
"""
from __future__ import annotations

from rag import config
from rag.preprocessing.korean_tokenize import tokenize_for_search

_BATCH_SIZE = 200


def _column_exists(conn, table: str, column: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s;
            """,
            (table, column),
        )
        return cur.fetchone() is not None


def _apply_schema_changes(conn) -> None:
    with conn.cursor() as cur:
        if not _column_exists(conn, "chunks", "content_tokenized"):
            print("[migrate] content_tokenized 컬럼 추가")
            cur.execute("ALTER TABLE chunks ADD COLUMN content_tokenized TEXT;")
        else:
            print("[migrate] content_tokenized 컬럼 이미 있음 — 건너뜀")

        cur.execute(
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'chunks' AND column_name = 'content_tsv';
            """
        )
        # content_tsv가 이미 content_tokenized 기준으로 재정의됐는지는 information_schema로
        # 생성식까지는 확인이 번거로워서, pg_get_expr로 실제 생성식 텍스트를 확인.
        cur.execute(
            """
            SELECT pg_get_expr(adbin, adrelid)
            FROM pg_attrdef
            WHERE adrelid = 'chunks'::regclass
              AND adnum = (
                  SELECT attnum FROM pg_attribute
                  WHERE attrelid = 'chunks'::regclass AND attname = 'content_tsv'
              );
            """
        )
        row = cur.fetchone()
        already_migrated = bool(row and row[0] and "content_tokenized" in row[0])

        if already_migrated:
            print("[migrate] content_tsv가 이미 content_tokenized 기준 — 재정의 건너뜀")
        else:
            print("[migrate] content_tsv를 content_tokenized 기준으로 재정의 (DROP INDEX -> DROP/ADD COLUMN -> CREATE INDEX)")
            cur.execute("DROP INDEX IF EXISTS idx_chunks_content_tsv;")
            cur.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS content_tsv;")
            cur.execute(
                """
                ALTER TABLE chunks
                ADD COLUMN content_tsv TSVECTOR
                GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content_tokenized, content))) STORED;
                """
            )
            cur.execute("CREATE INDEX idx_chunks_content_tsv ON chunks USING GIN (content_tsv);")
    conn.commit()
    print("[migrate] 스키마 변경 완료")


def _backfill_tokenized(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunks;")
        total = cur.fetchone()[0]
    print(f"[migrate] chunks 총 {total}건 재토큰화 시작")

    done = 0
    while True:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, content FROM chunks ORDER BY id LIMIT %s OFFSET %s;",
                (_BATCH_SIZE, done),
            )
            rows = cur.fetchall()
        if not rows:
            break

        with conn.cursor() as cur:
            for chunk_id, content in rows:
                tokenized = tokenize_for_search(content) or content
                cur.execute(
                    "UPDATE chunks SET content_tokenized = %s WHERE id = %s;",
                    (tokenized, chunk_id),
                )
        conn.commit()

        done += len(rows)
        print(f"[migrate]   {done}/{total}건 처리")

    print(f"[migrate] 재토큰화 완료 — 총 {done}건")


def main() -> None:
    with config.get_connection() as conn:
        _apply_schema_changes(conn)
        _backfill_tokenized(conn)
    print("\n끝 — python -m rag.scripts.smoke_test_search 로 키워드 검색이 정상인지 확인해볼 것")


if __name__ == "__main__":
    main()
