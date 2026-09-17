"""
embedding이 NULL로 남은 chunk를 찾아서 재계산하는 백필 스크립트.

배경: pipeline/ingest.py는 documents/chunks를 먼저 커밋한 뒤 별도로 임베딩을 계산하는데,
2026-09-16 이전에는 이 임베딩 단계가 실패(rate limit 재시도 소진, API 일시 장애 등)하면
예외가 ingest_document() 밖으로 그대로 나가서 (1) documents/chunks는 이미 커밋된 채로 남고,
(2) content_hash가 이미 DB에 있어서 다음 수집 때 "완전중복"으로 처리돼 다시는 재시도되지
않고, (3) 그 뒤에 있던 엔티티/관계 저장 단계까지 통째로 스킵되는 문제가 있었음 — 즉
embedding=NULL인 채로 영구 박제되는 문서가 생길 수 있었음(벡터검색에서 계속 누락).

지금은 ingest.py가 임베딩 실패를 잡아서 엔티티 저장은 계속 진행하도록 고쳤지만(같은 날
커밋), embedding=NULL 자체는 여전히 남으므로 이 스크립트로 한 번 정리 필요. 엔티티/관계는
이미 정상 저장됐을 가능성이 높아 이 스크립트는 embedding만 다시 계산 — entities 재추출은
안 함(LLM 재호출 비용 없음).

실행 (secondpj 루트에서, DB 접속 가능한 PC에서):
    python -m rag.scripts.backfill_missing_embeddings
"""
from __future__ import annotations

from rag import config
from rag.embedding.embed import embed_texts, embedding_to_pgvector_literal

BATCH_SIZE = 50  # 한 번에 재계산할 chunk 수 (embed_texts 내부에서 또 100단위로 나뉨)


def main() -> None:
    if not config.EMBEDDING_PROVIDER:
        print("EMBEDDING_PROVIDER가 .env에 설정되지 않았습니다 — 재계산할 수 없습니다.")
        return

    with config.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id, c.document_id, c.content, d.document_type, d.title
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.embedding IS NULL
                ORDER BY c.document_id, c.chunk_index;
                """
            )
            rows = cur.fetchall()

        if not rows:
            print("embedding이 NULL인 chunk 없음 — 정리할 것 없습니다.")
            return

        affected_docs = {r[1] for r in rows}
        print(f"embedding 없는 chunk {len(rows)}건 (문서 {len(affected_docs)}건) 발견 — 재계산 시작")

        succeeded = 0
        failed = 0
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            try:
                vectors = embed_texts([r[2] for r in batch])
            except Exception as e:  # noqa: BLE001 — 이 배치만 실패, 나머지는 계속 진행
                print(f"[backfill] 배치 {i}~{i + len(batch)} 임베딩 실패, 다음 배치로 계속: {e}")
                failed += len(batch)
                continue

            with conn.cursor() as cur:
                for (chunk_id, document_id, _content, doc_type, title), vec in zip(batch, vectors):
                    cur.execute(
                        "UPDATE chunks SET embedding = %s::vector WHERE id = %s;",
                        (embedding_to_pgvector_literal(vec), chunk_id),
                    )
            conn.commit()
            succeeded += len(batch)
            print(f"[backfill] {i + len(batch)}/{len(rows)}건 처리 (마지막: [{doc_type}] {title[:40]!r})")

    print(f"\n끝 — 재계산 성공 {succeeded}건, 실패(여전히 NULL) {failed}건")
    if failed:
        print("실패분은 API 상태 확인 후 스크립트를 다시 돌리면 됨(이미 성공한 건 재요청 안 하고 넘어감).")


if __name__ == "__main__":
    main()
