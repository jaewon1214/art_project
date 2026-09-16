"""
뉴스 문서(collector/news_collector.py) 카테고리 재분류 백필 스크립트.

배경: news_collector.py가 모든 기사에 category="음성복제"를 하드코딩해서 저장하던 버그가 있었음
(rag/entity_extraction/extractor.py + rag/pipeline/ingest.py에서 이미 고침 — 앞으로 수집되는
문서는 LLM이 실제 내용을 보고 분류함). 이 스크립트는 버그가 있던 시절 이미 저장된 기존 news
문서들을 다시 분류해서 category를 바로잡는 일회성 백필용.

LLM_PROVIDER가 .env에 설정돼 있어야 동작함(설정 안 돼 있으면 재분류할 방법이 없으므로 즉시 종료).

실행 (secondpj 루트에서):
    python -m rag.scripts.backfill_news_category
"""
from __future__ import annotations

import time

from rag import config
from rag.entity_extraction import extractor

SLEEP_SEC = 0.5


def main() -> None:
    if not config.LLM_PROVIDER:
        print("LLM_PROVIDER가 .env에 없음 — 재분류 불가, 종료")
        return

    with config.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, content, category FROM documents WHERE document_type = 'news' ORDER BY created_at;"
            )
            rows = cur.fetchall()

        print(f"news 문서 {len(rows)}건 재분류 시작")
        changed = 0
        unchanged = 0
        failed = 0

        for doc_id, content, old_category in rows:
            try:
                extraction = extractor.analyze_document(content)
            except Exception as e:  # noqa: BLE001
                print(f"[backfill] {doc_id} 분류 실패: {e}")
                failed += 1
                continue

            new_category = extraction.get("category")
            if not extraction.get("is_relevant") or not new_category:
                # 이미 저장된 문서를 관련없음 판정났다고 지우진 않음 — category만 못 바꾸고 스킵
                print(
                    f"[backfill] {doc_id} category 재분류 실패"
                    f"(is_relevant={extraction.get('is_relevant')}) — 유지: {old_category}"
                )
                failed += 1
                continue

            if new_category == old_category:
                unchanged += 1
            else:
                with conn.cursor() as cur:
                    cur.execute("UPDATE documents SET category = %s WHERE id = %s;", (new_category, doc_id))
                conn.commit()
                print(f"[backfill] {doc_id}: {old_category} -> {new_category}")
                changed += 1

            time.sleep(SLEEP_SEC)

    print(f"\n끝 — 변경 {changed}건, 유지 {unchanged}건, 실패 {failed}건")


if __name__ == "__main__":
    main()
