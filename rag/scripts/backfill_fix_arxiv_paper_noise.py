"""
2026-09-19 데이터 감사(content-only export 재확인)에서 발견: document_type='paper' 문서
423건 중 251건(59%)의 content가 실제 초록이 아니라 arxiv.org/doi.org 페이지 전체(사이드바
"Bibliographic Tools"/"NASA ADS"/"Google Scholar"/"Semantic Scholar export BibTeX"/
"Download as File Copy to Clipboard" 위젯 텍스트 포함)를 그대로 긁어온 것으로 확인됨.

원인 추정: collector/paper_collector.py 자체(arXiv Atom API의 entry.summary, Semantic
Scholar/OpenAlex의 abstract 필드)는 원래 깨끗한 초록만 가져오는데, 이 251건은 그 경로가 아니라
add_url.py류의 "뉴스 기사용" 범용 추출(strip_noise_tags + strip_boilerplate_lines, article/body
태그 통째로 get_text())로 재수집된 것으로 보임 — arxiv.org 페이지엔 <article> 태그가 없어서
<body> 전체가 그대로 잡히고, 뉴스 CMS용 정제 패턴은 학술 사이트 사이드바 구조를 모름(예:
backfill_fix_encoding.py의 paper 재추출 폴백이 이 경로를 씀).

이 251건 중 248건은 url이 arxiv.org/abs/... 또는 doi.org/10.48550/arxiv.... 형태라 arxiv ID를
그대로 뽑아낼 수 있음 — arXiv 공식 Atom API(export.arxiv.org, paper_collector.py가 원래
쓰던 바로 그 API)로 id_list 파라미터를 이용해 재수집하면 원래 의도했던 깨끗한 초록으로
정확히 복원됨(API 자체가 배치 조회를 지원해서 id_list=id1,id2,...로 한 번에 여러 건 요청
가능 — 여기서도 그렇게 써서 arXiv 권장 요청 간격 부담을 줄임).

나머지 3건(Cambridge 저널 doi.org/10.1017/..., doi.org/10.17863/cam...)은 arXiv가 아니라
API로 못 잡음 — 이 스크립트 대상에서 제외, 감사 보고서에 별도로 남겨서 수동 확인 필요.

문서 단위 처리:
  1. document_type='paper'이고 url이 arxiv.org/abs/ 또는 48550/arxiv. 형태인 문서를 DB에서 조회.
  2. url에서 arxiv ID 추출(예: "2609.19304"). 실패하면 스킵.
  3. arxiv ID들을 BATCH_SIZE 단위로 묶어서 export.arxiv.org/api/query?id_list=id1,id2,...로 한
     번에 조회(paper_collector.py와 동일한 feedparser 파싱).
  4. 반환된 entry.summary(공백 정리)를 새 content로, 응답에 없는 id는 "arXiv에서 못 찾음"으로
     실패 처리(철회된 프리프린트 등 — 원래 그 시점엔 있었지만 지금은 없을 수 있음).
  5. content_hash가 기존과 다르면 content/content_hash 교체 + chunk/embedding 재생성.
     language는 건드리지 않음(이 251건은 전부 영어 논문이라 원래도 language='en'로 맞음 —
     language 오분류는 별도 감사(backfill_fix_audit_20260919.py)에서 이미 다룸).

기본 dry-run. --apply로 실제 반영. --limit/--offset으로 배치 분할 가능.

실행 (secondpj 루트에서):
    python -m rag.scripts.backfill_fix_arxiv_paper_noise                    # 미리보기
    python -m rag.scripts.backfill_fix_arxiv_paper_noise --apply --limit 20 # 소규모 확인
    python -m rag.scripts.backfill_fix_arxiv_paper_noise --apply            # 전체 반영
"""
from __future__ import annotations

import re
import sys
import time

import feedparser  # pip install feedparser
import psycopg2

from rag import config
from rag.chunking.chunker import build_chunk_rows
from rag.embedding.embed import embed_texts, embedding_to_pgvector_literal
from rag.preprocessing.dedupe import content_hash

ARXIV_API = "http://export.arxiv.org/api/query"
BATCH_SIZE = 40  # id_list 배치당 건수 — 너무 크면 요청 URL이 지나치게 길어질 수 있어 보수적으로 잡음
REQUEST_INTERVAL_SEC = 3  # arXiv 공식 권장 최소 간격 — paper_collector.py와 동일

_ARXIV_ID_RE = re.compile(
    r"arxiv\.org/abs/([\w.\-]+)|48550/arxiv\.([\w.\-]+)",
    re.IGNORECASE,
)


def _extract_arxiv_id(url: str) -> str | None:
    m = _ARXIV_ID_RE.search(url)
    if not m:
        return None
    raw = (m.group(1) or m.group(2)).rstrip("/")
    # 2026-09-19 버그 수정: url에서 뽑은 raw id는 "2609.18585v1"처럼 버전 접미사가 붙어있는데,
    # _fetch_batch()가 만드는 dict는 _arxiv_short_id()로 버전을 뗀 "2609.18585" 키를 쓴다.
    # 이 둘을 그대로 비교(main()의 fetched.get(arxiv_id))하면 버전 붙은 쪽은 절대 못 찾아서
    # 버전 있는 URL 228건이 전부 "arXiv에 없음"으로 스킵되는 버그가 있었음(실측: 248건 중
    # 버전 없는 20건만 매칭되고 나머지 228건 전부 실패). id_list 조회 자체는 버전 있는 ID를
    # 그대로 써도 arXiv API가 정상 응답하므로, 여기서는 "비교용 키"만 버전을 떼서 반환한다.
    return re.sub(r"v\d+$", "", raw)


def _arxiv_short_id(raw_id: str) -> str:
    """entry.id('http://arxiv.org/abs/2609.19304v1')에서 버전 접미사 뗀 순수 ID만."""
    tail = raw_id.rstrip("/").rsplit("/", 1)[-1]
    return tail.split("v")[0] if "v" in tail else tail


def _fetch_batch(arxiv_ids: list[str]) -> dict[str, str]:
    """id_list 배치 조회 -> {arxiv_id: 초록} 딕셔너리. 응답에 없는 id는 그냥 빠짐(호출부가
    "못 찾음"으로 처리)."""
    id_list = ",".join(arxiv_ids)
    url = f"{ARXIV_API}?id_list={id_list}&max_results={len(arxiv_ids)}"
    parsed = feedparser.parse(url)
    out: dict[str, str] = {}
    for entry in parsed.entries:
        short_id = _arxiv_short_id(entry.get("id", ""))
        summary = entry.get("summary", "").replace("\n", " ").strip()
        if short_id and summary:
            out[short_id] = summary
    return out


def _rebuild_chunks(conn, document_id, content: str) -> int:
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
    apply_changes = "--apply" in sys.argv

    limit: int | None = None
    offset = 0
    for arg in sys.argv:
        if arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
        elif arg.startswith("--offset="):
            offset = int(arg.split("=", 1)[1])

    with config.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                r"""
                SELECT id, url, content, content_hash
                FROM documents
                WHERE document_type = 'paper'
                  AND (url ~* 'arxiv\.org/abs/' OR url ~* '48550/arxiv\.')
                ORDER BY created_at DESC;
                """
            )
            rows = cur.fetchall()

        targets = []
        no_id: list[str] = []
        for doc_id, url, old_content, old_hash in rows:
            arxiv_id = _extract_arxiv_id(url)
            if not arxiv_id:
                no_id.append(url)
                continue
            targets.append((doc_id, url, arxiv_id, old_content, old_hash))

        if no_id:
            print(f"arxiv ID를 못 뽑은 url {len(no_id)}건(스킵):")
            for u in no_id:
                print(f"  - {u}")

        batch = targets[offset : offset + limit] if limit is not None else targets[offset:]
        mode_label = "실제 반영 모드" if apply_changes else "dry-run (미리보기만, DB는 안 건드림)"
        print(f"arXiv 논문 대상 {len(targets)}건 중 offset={offset}부터 {len(batch)}건 처리 — {mode_label}")

        content_replaced = 0
        unchanged = 0
        not_found_in_arxiv: list[str] = []
        failed: list[tuple[str, str]] = []

        for batch_start in range(0, len(batch), BATCH_SIZE):
            chunk = batch[batch_start : batch_start + BATCH_SIZE]
            arxiv_ids = [t[2] for t in chunk]
            try:
                fetched = _fetch_batch(arxiv_ids)
            except Exception as e:  # noqa: BLE001 — 배치 하나 실패해도 나머지 배치는 계속 진행
                print(f"배치 조회 실패({arxiv_ids[0]}...{arxiv_ids[-1]}): {e}")
                for _, url, _, _, _ in chunk:
                    failed.append((url, str(e)))
                time.sleep(REQUEST_INTERVAL_SEC)
                continue

            for doc_id, url, arxiv_id, old_content, old_hash in chunk:
                new_content = fetched.get(arxiv_id)
                if not new_content:
                    print(f"  {doc_id} ({url}): arXiv API 응답에 없음(철회/오탈자 등 추정) — 스킵")
                    not_found_in_arxiv.append(url)
                    continue

                new_hash = content_hash(new_content)
                if new_hash == old_hash:
                    unchanged += 1
                    continue

                print(
                    f"  {doc_id} ({url}): content 교체 "
                    f"({len(old_content)}자 -> {len(new_content)}자)"
                )
                if apply_changes:
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE documents SET content = %s, content_hash = %s WHERE id = %s;",
                                (new_content, new_hash, doc_id),
                            )
                        conn.commit()
                    except psycopg2.errors.UniqueViolation:
                        conn.rollback()
                        print(f"    -> 다른 문서와 content_hash 중복 — 스킵")
                        failed.append((url, "content_hash unique violation"))
                        continue

                    try:
                        n_chunks = _rebuild_chunks(conn, doc_id, new_content)
                        print(f"    -> chunk {n_chunks}개 재생성 완료")
                    except Exception as e:  # noqa: BLE001
                        conn.rollback()
                        print(f"    -> chunk 재생성 실패({e})")
                        failed.append((url, str(e)))
                        continue

                content_replaced += 1

            if batch_start + BATCH_SIZE < len(batch):
                time.sleep(REQUEST_INTERVAL_SEC)

    print(
        f"\n끝 — content 교체 {content_replaced}건, 변경 없음 {unchanged}건, "
        f"arXiv에 없음 {len(not_found_in_arxiv)}건, 실패 {len(failed)}건"
    )
    if not_found_in_arxiv:
        print("arXiv API 응답에 없던 url(수동 확인 필요):")
        for u in not_found_in_arxiv:
            print(f"  - {u}")
    if failed:
        print("실패한 url:")
        for url, reason in failed:
            print(f"  - {url}: {reason}")
    if not apply_changes:
        print("\ndry-run이었습니다 — 실제로 반영하려면 --apply를 붙여서 다시 실행하세요.")


if __name__ == "__main__":
    main()
