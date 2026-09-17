"""
번역 정책 폐지(2026-09-17, rag/pipeline/ingest.py 참고)에 맞춰, 그 전에 이미 번역돼서
저장된 news/official/policy 문서들을 원문 언어로 되돌리는 일회성 백필 스크립트.

배경: ingest.py는 원래 document_type != "paper"이고 language != "ko"인 문서(주로 NewsAPI발
해외 뉴스)를 LLM으로 한국어 번역해서 저장했는데, 이제 그 단계를 없애고 papers처럼 원문
언어 그대로 저장/임베딩하기로 함(다국어 임베딩이 cross-lingual 검색을 커버하므로). 근데
이 정책 변경 전에 이미 수집·번역돼서 DB에 들어간 문서들은 번역문 그대로 남아있고, 그
문서들의 번역 전 원문 텍스트 자체는 DB에 저장된 적이 없음(content_hash만 번역 전 원문
기준으로 계산하고 원문 텍스트는 버림 — ingest.py 참고, backfill_retranslate.py와 동일한
제약) — 그래서 documents.url로 원본 페이지를 다시 긁어와야만 원문 복구가 가능함.

대상: document_type IN ('news', 'official', 'policy') 전체.
- case는 law.go.kr API 응답이라 원문 자체가 항상 한국어라 번역 단계를 아예 안 거침 → 제외
- paper는 애초에 번역 대상이 아니었음(원문 학술 용어 보존 목적) → 제외

"어떤 문서가 실제로 번역됐었는지"는 지금 DB만 보고는 구분이 안 됨 — 번역 후 language
컬럼을 전부 "ko"로 덮어써서, 원래 한국어였던 문서와 번역된 문서가 구분 불가능해짐. 그래서
대상 전체를 다시 긁어와서, 새로 긁어온 원문이 이미 한글 위주(_is_already_korean)면
"원래 한국어였음"으로 보고 내용이 실질적으로 같으면 건드리지 않고, 한글 위주가 아니면
"번역됐던 것"으로 보고 그 원문(번역 없이 그대로)으로 content를 교체함.

문서 하나당 처리 순서:
    1. document_type에 맞는 collector의 fetch 함수로 documents.url 원본 페이지를 다시 긁어옴
       (news: news_collector._extract_body, official/policy: 각 모듈의 _fetch_page)
    2. 새로 긁어온 원문의 content_hash가 documents.content_hash와 같으면(이미 원문 상태,
       번역 안 됐던 문서) 건드릴 필요 없음 — skip으로 카운트하고 다음 문서로.
    3. 다르면 documents.content/content_hash를 새로 긁어온 원문으로 교체(번역 호출 없음),
       chunks/embedding 재생성(rechunk_documents.py의 _rebuild_chunks()와 동일 패턴).
       documents.language는 "ko"였던 걸 그대로 두지 않고, 새로 긁어온 원문이 한글 위주면
       "ko", 아니면 "en"으로 갱신(정확한 언어 코드까지는 못 알아내므로 en/ko 2분류만 — 지금
       소스들(NewsAPI 등)이 실제로 다른 외국어를 섞어 낼 가능성은 낮다고 보고 단순화함).

entities/document_entities(Neo4j 포함)는 안 건드림 — 같은 사실관계를 다루는 문서의 언어만
바뀌는 거라(내용 자체는 원래 그 문서가 다루던 사실관계와 동일) 재추출(LLM 비용) 생략함
(backfill_retranslate.py/backfill_strip_html.py와 동일한 판단). 단, 엔티티가 번역문 기준으로
뽑혔을 수는 있음(이번 변경으로 정확히 고쳐지는 부분은 아님 — 필요하면 별도 논의).

⚠️ 원본 페이지가 그새 사라졌거나(404) 봇 차단으로 재수집이 막힌 경우 스킵하고 계속 진행 —
실패한 URL은 마지막에 목록으로 출력되니, 그건 수동으로 확인하거나 그냥 다음 수집 주기에
맡기면 됨.
⚠️ 사이트가 그새 기사를 수정했으면(오탈자 수정 등) 원래 수집 시점의 텍스트와 100% 동일하진
않을 수 있음 — backfill_strip_boilerplate.py 등 기존 백필들과 동일하게 감수하는 수준의 오차.
⚠️ 문서 수만큼 원본 페이지 재요청 + (교체된 문서만) 임베딩 API 재호출이 발생 — 시간이 걸림.

실행 (secondpj 루트에서, 서버 DB 접속 가능한 PC에서):
    python -m rag.scripts.backfill_restore_original
"""
from __future__ import annotations

import re
import time

from rag import config
from rag.chunking.chunker import build_chunk_rows
from rag.embedding.embed import embed_texts, embedding_to_pgvector_literal
from rag.preprocessing.dedupe import content_hash

_HANGUL_RE = re.compile(r"[가-힣]")

# 재수집 사이 최소 간격 — backfill_retranslate.py와 동일한 예의상 간격.
REFETCH_INTERVAL_SEC = 1


def _refetch(document_type: str, url: str) -> str:
    """document_type에 맞는 collector의 본문 추출 함수로 url을 다시 긁어와 본문 텍스트만 반환.
    backfill_retranslate.py의 동명 함수와 동일 — 이 스크립트도 독립 실행 가능하도록 그대로
    복제해서 씀(이 프로젝트 백필 스크립트들의 공통 관례)."""
    if document_type == "news":
        from collector.news_collector import _extract_body

        return _extract_body(url)
    if document_type == "official":
        from collector.official_collector import _fetch_page

        _, content = _fetch_page(url)
        return content
    if document_type == "policy":
        from collector.policy_collector import _fetch_page

        _, content = _fetch_page(url)
        return content
    raise ValueError(f"재수집 미지원 document_type: {document_type}")


def _is_already_korean(text: str, min_ratio: float = 0.2) -> bool:
    """텍스트가 한글 위주면 True — backfill_retranslate.py의 동명 함수와 동일 기준."""
    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return False
    hangul = sum(1 for c in non_space if _HANGUL_RE.match(c))
    return (hangul / len(non_space)) >= min_ratio


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
    with config.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, document_type, url, content_hash
                FROM documents
                WHERE document_type IN ('news', 'official', 'policy')
                ORDER BY created_at;
                """
            )
            rows = cur.fetchall()

        print(f"대상 {len(rows)}건 — 원본 재수집해서 번역 전 원문과 비교합니다.")

        restored = 0
        unchanged = 0
        failed: list[tuple[str, str]] = []

        for i, (doc_id, doc_type, url, old_hash) in enumerate(rows, start=1):
            try:
                raw = _refetch(doc_type, url)
            except Exception as e:  # noqa: BLE001 — 페이지 하나 실패해도 나머지는 계속 진행
                print(f"[restore_original] {doc_id} ({doc_type}, {url}): 원본 재수집 실패({e}) — 스킵")
                failed.append((url, str(e)))
                time.sleep(REFETCH_INTERVAL_SEC)
                continue

            if not raw or not raw.strip():
                print(f"[restore_original] {doc_id} ({doc_type}, {url}): 재수집 결과가 비어있음 — 스킵")
                failed.append((url, "빈 본문"))
                time.sleep(REFETCH_INTERVAL_SEC)
                continue

            new_hash = content_hash(raw)  # ingest.py와 동일하게 "원문 그대로" 기준 해시

            if new_hash == old_hash:
                # 번역 전 원문 기준 해시가 이미 지금 저장된 값과 같음 — 애초에 번역 안 됐던
                # 문서(원래 한국어)이거나, 이미 다른 경로로 원문 상태였던 문서. 손댈 필요 없음.
                unchanged += 1
                time.sleep(REFETCH_INTERVAL_SEC)
                continue

            new_language = "ko" if _is_already_korean(raw) else "en"

            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE documents SET content = %s, content_hash = %s, language = %s WHERE id = %s;",
                        (raw, new_hash, new_language, doc_id),
                    )
                conn.commit()
            except Exception as e:  # noqa: BLE001 — 예: 재수집 결과가 다른 기존 문서와 해시 중복
                conn.rollback()
                print(f"[restore_original] {doc_id} ({doc_type}, {url}): documents 갱신 실패({e}) — 스킵")
                failed.append((url, str(e)))
                time.sleep(REFETCH_INTERVAL_SEC)
                continue

            try:
                n_chunks = _rebuild_chunks(conn, doc_id, raw)
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                print(
                    f"[restore_original] {doc_id} ({doc_type}, {url}): chunk 재생성 실패({e}) "
                    "— content는 갱신됐지만 chunk는 옛날 것으로 남음"
                )
                failed.append((url, str(e)))
                time.sleep(REFETCH_INTERVAL_SEC)
                continue

            restored += 1
            print(
                f"[restore_original] {i}/{len(rows)} {doc_id} ({doc_type}): "
                f"원문으로 교체(language={new_language}), chunk {n_chunks}개 재생성"
            )

            time.sleep(REFETCH_INTERVAL_SEC)

    print(
        f"\n끝 — 대상 {len(rows)}건 중 원문으로 교체 {restored}건, "
        f"이미 원문 상태라 변경 없음 {unchanged}건, 실패 {len(failed)}건"
    )
    if failed:
        print("실패한 URL:")
        for url, reason in failed:
            print(f"  - {url}: {reason}")


if __name__ == "__main__":
    main()
