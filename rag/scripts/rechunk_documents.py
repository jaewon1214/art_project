"""
청크 크기를 300/50 -> 600/100으로 바꾼 뒤(rag/chunking/chunker.py), 이미 적재된 문서들의
chunks를 전부 새 설정 기준으로 재생성하는 일회성 백필 스크립트.

배경: DEFAULT_CHUNK_SIZE/DEFAULT_OVERLAP은 청크를 "만드는 시점"에만 적용되기 때문에, 값을
바꿔도 이미 DB에 저장된 chunks는 자동으로 안 바뀜 — 문서마다 기존 chunks를 지우고
documents.content(원문, 안 건드림) 기준으로 새로 잘라서 임베딩까지 다시 채워야 새 청크
크기가 실제로 적용됨. backfill_strip_html.py의 _rebuild_chunks()와 같은 패턴이고, 차이는
거기는 content가 바뀐 문서만 골라서 재생성했다면 여기는 전체 문서 대상으로 무조건 재생성.

entities/document_entities(Neo4j 포함)는 안 건드림 — 청크 경계만 바뀌는 거라 문서 단위
엔티티 추출 결과에는 영향 없음.

⚠️ 문서 수만큼(수백 건) OpenAI 임베딩 API를 다시 호출함 — 청크가 커진 만큼(300->600단어)
문서당 청크 개수는 줄어들어서 총 호출량이 기존 최초 임베딩 때보다 크게 늘진 않지만,
그래도 시간이 좀 걸림(embed.py의 배치/재시도 로직 그대로 적용됨).

실행 (secondpj 루트에서, 서버 DB 접속 가능한 PC에서):
    python -m rag.scripts.rechunk_documents
"""
from __future__ import annotations

from rag import config
from rag.chunking.chunker import build_chunk_rows
from rag.embedding.embed import embed_texts, embedding_to_pgvector_literal


def _rebuild_chunks(conn, document_id, content: str) -> int:
    """document_id의 기존 chunks를 지우고 content(원문, 안 바뀜) 기준으로 새 청크 크기로
    다시 만들어 임베딩까지 채움. 반환: 새로 만든 chunk 개수."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE document_id = %s;", (document_id,))

    chunk_rows = build_chunk_rows(document_id, content)
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
    with config.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks;")
            old_total_chunks = cur.fetchone()[0]

            cur.execute("SELECT id, document_type, content FROM documents ORDER BY created_at;")
            rows = cur.fetchall()

        print(f"재청킹 대상 문서 {len(rows)}건 (기존 chunks 총 {old_total_chunks}개 -> chunk_size=600/overlap=100 기준 재생성)")

        new_total_chunks = 0
        failed = 0

        for i, (doc_id, doc_type, content) in enumerate(rows, start=1):
            try:
                n_chunks = _rebuild_chunks(conn, doc_id, content)
            except Exception as e:  # noqa: BLE001 — 한 문서 실패해도 나머지는 계속 진행
                conn.rollback()
                print(f"[rechunk] {doc_id} ({doc_type}): 재생성 실패({e}) — 이 문서는 chunk 없이 남을 수 있음")
                failed += 1
                continue

            new_total_chunks += n_chunks
            if i % 20 == 0 or i == len(rows):
                print(f"  진행 {i}/{len(rows)}...")

    print(f"\n끝 — 문서 {len(rows)}건 처리, 실패 {failed}건")
    print(f"chunks 총 개수: {old_total_chunks}개 -> {new_total_chunks}개")


if __name__ == "__main__":
    main()
