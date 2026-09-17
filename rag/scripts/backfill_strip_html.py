"""
이미 저장된 문서 중 HTML 잔재가 섞여있을 수 있는 것들을 재정리하는 일회성 백필 스크립트.

배경: case_collector.py가 law.go.kr API 응답(판시사항/판결요지/판례내용)에 strip_html()을
안 거치고 그대로 저장하던 버그가 있었음(collector/case_collector.py에서 이미 고침 — 앞으로
수집되는 case 문서는 정상). 이 스크립트는 버그가 있던 시절 이미 저장된 기존 문서들의
documents.content를 strip_html()로 다시 정리하고, content가 바뀐 문서는 content_hash도
다시 계산하고 chunks/embedding도 새 content 기준으로 재생성함(안 그러면 documents.content와
chunks.content가 서로 어긋나서 검색 결과에 옛날 HTML 섞인 텍스트가 그대로 나옴).

entities/document_entities(Neo4j 포함)는 건드리지 않음 — strip_html은 태그만 제거하고 실제
텍스트 내용 자체는 그대로라 엔티티 추출 결과가 달라질 가능성이 낮고, 재추출은 LLM 호출 비용이
드니 여기선 생략(필요해지면 나중에 별도 스크립트로 재추출하면 됨).

실행 (secondpj 루트에서):
    python -m rag.scripts.backfill_strip_html             # document_type='case'만 (기본, 실제로
                                                            # HTML이 안 걸러지던 유일한 타입)
    python -m rag.scripts.backfill_strip_html --all-types # 모든 document_type 검사(안전 확인용 —
                                                            # news/official/policy는 원래도 strip_html을
                                                            # 거쳤고 paper는 HTML이 안 섞이는 소스라
                                                            # 바뀌는 게 거의 없을 것으로 예상되지만
                                                            # 혹시 몰라 옵션으로 둠)
"""
from __future__ import annotations

import sys

import psycopg2

from rag import config
from rag.chunking.chunker import build_chunk_rows
from rag.embedding.embed import embed_texts, embedding_to_pgvector_literal
from rag.preprocessing.clean_html import strip_html
from rag.preprocessing.dedupe import content_hash


def _rebuild_chunks(conn, document_id, new_content: str) -> int:
    """document_id의 기존 chunks를 지우고 new_content 기준으로 새로 만들어 임베딩까지 채움.
    반환: 새로 만든 chunk 개수."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE document_id = %s;", (document_id,))

    chunk_rows = build_chunk_rows(document_id, new_content)
    if not chunk_rows:
        conn.commit()
        return 0

    chunk_id_by_index: dict[int, str] = {}
    with conn.cursor() as cur:
        for row in chunk_rows:
            cur.execute(
                """
                INSERT INTO chunks (document_id, chunk_index, content, content_tokenized, token_count)
                VALUES (%(document_id)s, %(chunk_index)s, %(content)s, %(content_tokenized)s, %(token_count)s)
                RETURNING id;
                """,
                row,
            )
            chunk_id_by_index[row["chunk_index"]] = cur.fetchone()[0]
    conn.commit()

    if config.EMBEDDING_PROVIDER:
        vectors = embed_texts([row["content"] for row in chunk_rows])
        with conn.cursor() as cur:
            for row, vec in zip(chunk_rows, vectors):
                cur.execute(
                    "UPDATE chunks SET embedding = %s::vector WHERE id = %s;",
                    (embedding_to_pgvector_literal(vec), chunk_id_by_index[row["chunk_index"]]),
                )
        conn.commit()

    return len(chunk_rows)


def main() -> None:
    all_types = "--all-types" in sys.argv

    with config.get_connection() as conn:
        with conn.cursor() as cur:
            if all_types:
                cur.execute("SELECT id, document_type, content FROM documents ORDER BY created_at;")
            else:
                cur.execute(
                    "SELECT id, document_type, content FROM documents "
                    "WHERE document_type = 'case' ORDER BY created_at;"
                )
            rows = cur.fetchall()

        print(f"검사 대상 {len(rows)}건 ({'전체 타입' if all_types else 'case만'})")
        changed = 0
        unchanged = 0
        failed = 0

        for doc_id, doc_type, old_content in rows:
            new_content = strip_html(old_content)
            if new_content == old_content:
                unchanged += 1
                continue

            new_hash = content_hash(new_content)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE documents SET content = %s, content_hash = %s WHERE id = %s;",
                        (new_content, new_hash, doc_id),
                    )
                conn.commit()
            except psycopg2.errors.UniqueViolation:
                # 정리 후 내용이 이미 저장된 다른 문서와 완전히 똑같아진 극히 드문 경우 — 스킵
                conn.rollback()
                print(f"[backfill] {doc_id} ({doc_type}): 정리 후 다른 문서와 내용 중복 — 스킵")
                failed += 1
                continue

            try:
                n_chunks = _rebuild_chunks(conn, doc_id, new_content)
            except Exception as e:  # noqa: BLE001 — 한 문서 실패해도 나머지는 계속 진행
                conn.rollback()
                print(f"[backfill] {doc_id} ({doc_type}): chunk 재생성 실패({e}) — content는 정리됐지만 chunk는 옛날 것으로 남음")
                failed += 1
                continue

            changed += 1
            removed = len(old_content) - len(new_content)
            print(f"[backfill] {doc_id} ({doc_type}): HTML 잔재 {removed}자 제거, chunk {n_chunks}개 재생성")

    print(f"\n끝 — 변경 {changed}건, 그대로 {unchanged}건, 실패 {failed}건")


if __name__ == "__main__":
    main()
