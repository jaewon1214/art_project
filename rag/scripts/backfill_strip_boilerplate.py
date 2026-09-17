"""
이미 저장된 문서 중 카테고리 메뉴/바이라인/공유 위젯 같은 CMS 잡음이 본문에 섞여있을 수
있는 것들을 재정리하는 일회성 백필 스크립트 (backfill_strip_html.py와 같은 패턴).

배경: news_collector.py/official_collector.py/policy_collector.py의 _extract_body()/
_fetch_page()가 strip_noise_tags()(태그 기반)만 거치고 clean_html.strip_boilerplate_lines()
(텍스트 패턴 기반)는 안 거치던 시절 수집된 문서들 — 예: 데일리안 기사에서 "생활/문화 건강정보
..." 카테고리 메뉴, "OOO 기자 (email@...)" 바이라인, "입력/수정" 날짜배너, "구글 검색 선호
출처로 추가", "공유하기 카카오톡 블로그 페이스북 X 주소복사" 공유 위젯이 본문 content에 그대로
저장된 게 확인됨. collector들은 이미 고쳐뒀으니(strip_boilerplate_lines 연결) 앞으로 새로
수집되는 문서는 정상 — 이 스크립트는 그 전에 이미 저장된 news/official/policy 문서만 다시
정리.

backfill_strip_html.py와 마찬가지로 content가 바뀐 문서는 content_hash도 다시 계산하고
chunks/embedding도 새 content 기준으로 재생성함(안 그러면 documents.content와 chunks.content가
서로 어긋나서 검색 결과에 옛날 잡음 섞인 텍스트가 그대로 나옴).

실행 (secondpj 루트에서):
    python -m rag.scripts.backfill_strip_boilerplate              # news/official/policy만 (기본)
    python -m rag.scripts.backfill_strip_boilerplate --all-types  # 모든 document_type 검사(안전 확인용)
"""
from __future__ import annotations

import sys

import psycopg2

from rag import config
from rag.chunking.chunker import build_chunk_rows
from rag.embedding.embed import embed_texts, embedding_to_pgvector_literal
from rag.preprocessing.clean_html import normalize_whitespace, strip_boilerplate_lines
from rag.preprocessing.dedupe import content_hash

TARGET_TYPES = ("news", "official", "policy")


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
                    "WHERE document_type = ANY(%s) ORDER BY created_at;",
                    (list(TARGET_TYPES),),
                )
            rows = cur.fetchall()

        print(f"검사 대상 {len(rows)}건 ({'전체 타입' if all_types else '/'.join(TARGET_TYPES)})")
        changed = 0
        unchanged = 0
        failed = 0

        for doc_id, doc_type, old_content in rows:
            new_content = normalize_whitespace(strip_boilerplate_lines(old_content))
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
            print(f"[backfill] {doc_id} ({doc_type}): 잡음 {removed}자 제거, chunk {n_chunks}개 재생성")

    print(f"\n끝 — 변경 {changed}건, 그대로 {unchanged}건, 실패 {failed}건")


if __name__ == "__main__":
    main()
