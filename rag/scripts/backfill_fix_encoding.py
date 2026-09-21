"""
이미 저장된 문서 중, requests가 charset을 잘못 추측해서(resp.text 사용 — 서버가 응답 헤더에
charset을 안 밝히거나 잘못 밝힌 경우) 스마트따옴표/줄표 같은 비-ASCII 문장부호가
"â€™"/"â"류로 깨져서 저장된 문서들을 URL 재방문으로 다시 수집해 바로잡는 일회성 백필 스크립트.

배경: collector/news_collector.py, collector/official_collector.py, collector/policy_collector.py,
add_url.py가 전부 BeautifulSoup(resp.text, ...) 패턴을 쓰고 있었는데, 이게 Music Business
Worldwide 기사에서 "Dua Lipaâs"(원래 "Dua Lipa's")처럼 깨지는 걸로 실제 확인됨 — 서버가
Content-Type 헤더에 잘못된/불일치하는 charset을 보내면 requests가 그걸 그대로 믿어버려서
생김(BeautifulSoup 자체 인코딩 감지를 쓰는 resp.content가 훨씬 안정적). 4개 파일 전부
resp.content로 이미 고쳤음 — 이 스크립트는 그 전에 이미 저장된 문서들을 URL로 재수집해서
같은 로직으로 다시 뽑고 교체.

문서마다 어떤 collector로 들어왔는지 정확히는 모르므로 document_type 기준으로 그나마 제일
가까운 추출 로직을 그대로 재사용(로직 중복을 피하려고 각 collector 모듈의 실제 함수를 import):
    document_type == "official" -> collector.official_collector._fetch_page()
    document_type == "policy"   -> collector.policy_collector._fetch_page()
    document_type == "news"     -> collector.news_collector._extract_body() (본문만 사용, 날짜는 무시
                                    — published_at 재계산은 별도로 이미 만든
                                    backfill_fix_published_dates.py가 담당)
    그 외(webpage/case/paper 등, url이 있는 경우) -> add_url._fetch_and_extract()
        (news_collector와 거의 동일한 article/body 기반 추출 — add_url.py로 수동 추가된
        문서들이 여기 해당)

안전장치:
  - 재추출한 본문이 원래보다 훨씬 짧아지거나(페이지 구조 변경/페이월/삭제 등) 비어있으면
    "본문이 너무 짧음"으로 스킵하고 기존 값을 유지 — 멀쩡한 기존 데이터를 나쁜 재수집 결과로
    덮어쓰지 않기 위함.
  - content가 실제로 바뀐 문서만 content_hash 재계산 + chunks/embedding 재생성
    (backfill_strip_boilerplate.py와 동일한 패턴 — 안 그러면 documents.content와 chunks.content가
    서로 어긋나서 검색 결과에 옛날 텍스트가 그대로 나옴).
  - content_hash 유니크 제약 충돌(정리 후 다른 문서와 완전히 같아지는 극히 드문 경우)은
    롤백하고 스킵.

기본값은 dry-run(미리보기만, DB 안 건드림) — 문서 전체를 재fetch하고 chunks/embedding까지
다시 만드는 무거운 작업이라 먼저 몇 건이나 바뀌는지 확인하고 실행하는 게 안전함.

실행 (secondpj 루트에서, venv 활성화 상태로):
    python -m rag.scripts.backfill_fix_encoding              # 미리보기만
    python -m rag.scripts.backfill_fix_encoding --apply       # 실제로 DB에 반영
    python -m rag.scripts.backfill_fix_encoding --apply --types news,official  # 특정 타입만
"""
from __future__ import annotations

import sys
import time

import psycopg2

from add_url import _fetch_and_extract as _add_url_fetch_and_extract
from collector.news_collector import _extract_body as _news_extract_body
from collector.official_collector import _fetch_page as _official_fetch_page
from collector.policy_collector import _fetch_page as _policy_fetch_page
from rag import config
from rag.chunking.chunker import build_chunk_rows
from rag.embedding.embed import embed_texts, embedding_to_pgvector_literal
from rag.preprocessing.clean_html import is_too_short
from rag.preprocessing.dedupe import content_hash

# news_collector.py와 동일한 정중한 간격 — 문서 전체를 순회하며 재fetch하는 대량 작업이라
# 특히 더 지켜야 함(한 매체에 너무 몰아서 요청하면 403/429로 차단당할 수 있음).
SLEEP_SEC = 1.0


def _reextract_content(document_type: str, url: str) -> str:
    """document_type에 맞는 collector의 실제 추출 함수를 그대로 재사용해서 본문만 뽑아 반환."""
    if document_type == "official":
        _title, content = _official_fetch_page(url)
        return content
    if document_type == "policy":
        _title, content = _policy_fetch_page(url)
        return content
    if document_type == "news":
        content, _page_date = _news_extract_body(url)
        return content
    # webpage/case/paper 등 나머지 — add_url.py로 수동 추가된 문서들이 주로 해당.
    _title, content = _add_url_fetch_and_extract(url)
    return content


def _rebuild_chunks(conn, document_id, new_content: str) -> int:
    """document_id의 기존 chunks를 지우고 new_content 기준으로 새로 만들어 임베딩까지 채움.
    backfill_strip_boilerplate.py의 동일 함수와 완전히 같은 패턴."""
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
    apply_changes = "--apply" in sys.argv

    type_filter: list[str] | None = None
    for arg in sys.argv:
        if arg.startswith("--types="):
            type_filter = [t.strip() for t in arg.split("=", 1)[1].split(",") if t.strip()]
        elif arg == "--types" and sys.argv.index(arg) + 1 < len(sys.argv):
            nxt = sys.argv[sys.argv.index(arg) + 1]
            if not nxt.startswith("--"):
                type_filter = [t.strip() for t in nxt.split(",") if t.strip()]

    with config.get_connection() as conn:
        with conn.cursor() as cur:
            if type_filter:
                cur.execute(
                    "SELECT id, url, document_type, content FROM documents "
                    "WHERE url IS NOT NULL AND document_type = ANY(%s) ORDER BY created_at;",
                    (type_filter,),
                )
            else:
                cur.execute(
                    "SELECT id, url, document_type, content FROM documents "
                    "WHERE url IS NOT NULL ORDER BY created_at;"
                )
            rows = cur.fetchall()

        mode_label = "실제 반영 모드" if apply_changes else "dry-run (미리보기만, DB는 안 건드림)"
        scope_label = f"types={','.join(type_filter)}" if type_filter else "전체 타입"
        print(f"검사 대상 문서 {len(rows)}건 ({scope_label}) — {mode_label}")

        changed = 0
        unchanged = 0
        skipped_too_short = 0
        failed = 0

        for doc_id, url, doc_type, old_content in rows:
            try:
                new_content = _reextract_content(doc_type, url)
            except Exception as e:  # noqa: BLE001 — 한 건 실패해도 나머지는 계속 진행
                print(f"[backfill] {doc_id} ({doc_type}, {url}): 재수집 실패 — {e}")
                failed += 1
                time.sleep(SLEEP_SEC)
                continue

            if is_too_short(new_content):
                # 페이지 구조 변경/페이월/삭제 등으로 재수집 결과가 부실한 경우 — 멀쩡한 기존
                # 값을 나쁜 결과로 덮어쓰지 않고 그대로 둠.
                print(f"[backfill] {doc_id} ({doc_type}, {url}): 재수집 본문이 너무 짧음 ({len(new_content)}자) — 기존 값 유지")
                skipped_too_short += 1
                time.sleep(SLEEP_SEC)
                continue

            if new_content == old_content:
                unchanged += 1
                time.sleep(SLEEP_SEC)
                continue

            preview_old = old_content[:60].replace("\n", " ")
            preview_new = new_content[:60].replace("\n", " ")
            print(f"[backfill] {doc_id} ({doc_type}, {url}):")
            print(f"    이전: {preview_old!r}")
            print(f"    이후: {preview_new!r}")

            if apply_changes:
                new_hash = content_hash(new_content)
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE documents SET content = %s, content_hash = %s WHERE id = %s;",
                            (new_content, new_hash, doc_id),
                        )
                    conn.commit()
                except psycopg2.errors.UniqueViolation:
                    conn.rollback()
                    print(f"[backfill] {doc_id}: 재수집 후 다른 문서와 내용 중복 — 스킵")
                    failed += 1
                    time.sleep(SLEEP_SEC)
                    continue

                try:
                    n_chunks = _rebuild_chunks(conn, doc_id, new_content)
                    print(f"    -> chunk {n_chunks}개 재생성 완료")
                except Exception as e:  # noqa: BLE001
                    conn.rollback()
                    print(f"[backfill] {doc_id}: chunk 재생성 실패({e}) — content는 갱신됐지만 chunk는 옛날 것으로 남음")
                    failed += 1
                    time.sleep(SLEEP_SEC)
                    continue

            changed += 1
            time.sleep(SLEEP_SEC)

    verb = "변경" if apply_changes else "바뀔 것"
    print(
        f"\n끝 — {verb} {changed}건, 그대로 {unchanged}건, "
        f"재수집 본문 너무 짧아 유지 {skipped_too_short}건, 실패 {failed}건"
    )
    if not apply_changes and changed:
        print("dry-run이었습니다 — 실제로 반영하려면 --apply를 붙여서 다시 실행하세요:")
        print("    python -m rag.scripts.backfill_fix_encoding --apply")


if __name__ == "__main__":
    main()
