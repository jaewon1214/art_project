"""
번역 결과에 원문(영어 등) 문장이 그대로 남아있는 기존 문서들을, 원본 URL에서 다시 긁어와
재번역하는 일회성 백필 스크립트.

배경: rag/preprocessing/translate.py의 번역 품질 문제(긴 텍스트를 한 번에 번역시킬 때 LLM이
일부 문장을 원문 그대로 남기는 현상)를 CHUNK_SIZE_CHARS 축소(3000->1500) + 재시도 로직으로
고쳤음(translate.py 참고) — 근데 이건 "앞으로 수집되는 문서"부터 적용됨. 이미 DB에 저장된
문서는 번역 전 원문 텍스트 자체를 저장 안 해서(content_hash만 번역 전 원문 기준으로 계산하고
원문은 버림 — ingest.py 참고) DB 안에서는 복구가 안 되고, documents.url로 원본 페이지를
다시 긁어와야만 재번역이 가능함.

대상: document_type IN ('news', 'official', 'policy')인 문서 중, content 안에 한글이 하나도
없는 긴 문장(_count_untranslated_sentences — translate.py와 동일 기준)이 남아있는 것들.
- case는 law.go.kr API 응답이라 원문 자체가 항상 한국어라 번역 단계를 아예 안 거침 → 제외
- paper는 원문 학술 용어 보존 목적으로 애초에 번역 대상이 아님 → 제외

문서 하나당 처리 순서:
    1. document_type에 맞는 collector의 fetch 함수로 documents.url 원본 페이지를 다시 긁어옴
       (news: news_collector._extract_body, official/policy: 각 모듈의 _fetch_page)
    2. 새로 긁어온 원문이 이미 한글 위주(_is_already_korean)면 번역 없이 그대로 사용 — 원래
       한국어 매체인데 옛 content 안에 섞인 영어 인용문 때문에 오탐(false positive)된 경우를
       여기서 걸러냄. 그 외엔 translate.py의 개선된 translate_to_korean()으로 재번역.
    3. documents.content/content_hash 갱신 (해시는 ingest.py와 동일하게 "번역 전 원문" 기준),
       chunks/embedding 재생성(rechunk_documents.py의 _rebuild_chunks()와 동일 패턴)

entities/document_entities(Neo4j 포함)는 안 건드림 — 같은 기사의 번역 품질만 좋아지는 거라
사실관계 자체는 안 바뀌므로 재추출(LLM 비용) 생략함(backfill_strip_html.py와 동일한 판단).

⚠️ 원본 페이지가 그새 사라졌거나(404) 봇 차단으로 재수집이 막힌 경우 스킵하고 계속 진행 —
실패한 URL은 마지막에 목록으로 출력되니, 그건 수동으로 확인하거나 그냥 다음 수집 주기에
맡기면 됨.

실행 (secondpj 루트에서, 서버 DB 접속 가능한 PC에서):
    python -m rag.scripts.backfill_retranslate
"""
from __future__ import annotations

import re
import time

from rag import config
from rag.chunking.chunker import build_chunk_rows
from rag.embedding.embed import embed_texts, embedding_to_pgvector_literal
from rag.preprocessing.dedupe import content_hash
from rag.preprocessing.translate import _count_untranslated_sentences, translate_to_korean

_HANGUL_RE = re.compile(r"[가-힣]")

# 재수집 사이 최소 간격 — 같은 도메인(예: musicbusinessworldwide.com 기사 여러 건)을 짧은
# 시간에 여러 번 요청하지 않도록 예의상 둠(paper_collector.py/news_collector.py의 요청 간격
# 관례와 동일한 취지).
REFETCH_INTERVAL_SEC = 1


def _refetch(document_type: str, url: str) -> str:
    """document_type에 맞는 collector의 본문 추출 함수로 url을 다시 긁어와 본문 텍스트만 반환."""
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
    """새로 긁어온 원문이 이미 한글 위주면 True. 원래 한국어 매체(예: 전자신문, 한국저작권위원회
    보도자료)인데 옛 content에 섞인 영어 인용문 한두 줄 때문에 후보로 잘못 걸린 경우를 여기서
    걸러내서 불필요한 LLM 번역 호출을 막음."""
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
    if not config.LLM_PROVIDER:
        print("LLM_PROVIDER가 .env에 없어서 재번역을 할 수 없습니다 — .env를 먼저 채우세요.")
        return

    with config.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, document_type, url, content
                FROM documents
                WHERE document_type IN ('news', 'official', 'policy')
                ORDER BY created_at;
                """
            )
            rows = cur.fetchall()

        candidates = [
            (doc_id, doc_type, url, content)
            for doc_id, doc_type, url, content in rows
            if _count_untranslated_sentences(content) > 0
        ]
        print(f"검사 대상 {len(rows)}건 중 미번역 문장 의심 {len(candidates)}건 발견")

        fixed = 0
        skipped_already_ko = 0
        failed: list[tuple[str, str]] = []

        for i, (doc_id, doc_type, url, old_content) in enumerate(candidates, start=1):
            try:
                raw = _refetch(doc_type, url)
            except Exception as e:  # noqa: BLE001 — 페이지 하나 실패해도 나머지는 계속 진행
                print(f"[retranslate] {doc_id} ({doc_type}, {url}): 원본 재수집 실패({e}) — 스킵")
                failed.append((url, str(e)))
                time.sleep(REFETCH_INTERVAL_SEC)
                continue

            if not raw or not raw.strip():
                print(f"[retranslate] {doc_id} ({doc_type}, {url}): 재수집 결과가 비어있음 — 스킵")
                failed.append((url, "빈 본문"))
                time.sleep(REFETCH_INTERVAL_SEC)
                continue

            if _is_already_korean(raw):
                new_content = raw
                skipped_already_ko += 1
                note = "원문이 이미 한글 위주라 번역 없이 갱신"
            else:
                # 2026-09-16: 이 호출이 실패(타임아웃/API 에러)하면 예전엔 예외가 그대로 위로
                # 튀어서 main() 전체가 죽고 나머지 후보들을 아예 처리 못 했음 — 문서 하나 번역
                # 실패해도 나머지는 계속 진행되게 try/except로 감쌈(다른 단계들과 동일 패턴).
                try:
                    new_content = translate_to_korean(raw)
                except Exception as e:  # noqa: BLE001
                    print(f"[retranslate] {doc_id} ({doc_type}, {url}): 번역 실패({e}) — 스킵")
                    failed.append((url, f"번역 실패: {e}"))
                    time.sleep(REFETCH_INTERVAL_SEC)
                    continue
                note = "재번역 완료"

            new_hash = content_hash(raw)  # ingest.py와 동일하게 "번역 전 원문" 기준 해시

            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE documents SET content = %s, content_hash = %s WHERE id = %s;",
                        (new_content, new_hash, doc_id),
                    )
                conn.commit()
            except Exception as e:  # noqa: BLE001 — 예: 재수집 결과가 다른 기존 문서와 해시 중복
                conn.rollback()
                print(f"[retranslate] {doc_id} ({doc_type}, {url}): documents 갱신 실패({e}) — 스킵")
                failed.append((url, str(e)))
                time.sleep(REFETCH_INTERVAL_SEC)
                continue

            try:
                n_chunks = _rebuild_chunks(conn, doc_id, new_content)
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                print(
                    f"[retranslate] {doc_id} ({doc_type}, {url}): chunk 재생성 실패({e}) "
                    "— content는 갱신됐지만 chunk는 옛날 것으로 남음"
                )
                failed.append((url, str(e)))
                time.sleep(REFETCH_INTERVAL_SEC)
                continue

            remaining = _count_untranslated_sentences(new_content)
            fixed += 1
            warn = f" (⚠️ 여전히 미번역 문장 {remaining}개 남음 — 원문 자체가 특이 케이스일 수 있음)" if remaining else ""
            print(f"[retranslate] {i}/{len(candidates)} {doc_id} ({doc_type}): {note}, chunk {n_chunks}개 재생성{warn}")

            time.sleep(REFETCH_INTERVAL_SEC)

    print(
        f"\n끝 — 후보 {len(candidates)}건 중 처리 {fixed}건"
        f"(그중 원래 한글이라 번역 생략 {skipped_already_ko}건), 실패 {len(failed)}건"
    )
    if failed:
        print("실패한 URL:")
        for url, reason in failed:
            print(f"  - {url}: {reason}")


if __name__ == "__main__":
    main()
