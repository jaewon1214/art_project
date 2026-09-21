"""
이미 저장된 news 문서들의 published_at을 다시 계산해서 바로잡는 일회성 백필 스크립트.

배경: news_collector.py의 NewsAPI/네이버 수집 경로가 API가 주는 publishedAt/pubDate를
검증 없이 그대로 신뢰하던 버그가 있었음 — NMPA 기사(실제 게재일 2023-12-13)가
published_at=2026-09-16(수집 당일)로 잘못 저장된 사고로 발견됨. NewsAPI의 publishedAt이
실제로는 API 자신의 크롤링/색인 시각을 반영하는 경우가 있는 것으로 확인됨(created_at과
거의 일치). news_collector.py는 이미 고쳐서(페이지 자체 <meta>/<time>/JSON-LD에서 게재일을
직접 추출해 최우선으로 씀) 앞으로 수집되는 문서는 정상 — 이 스크립트는 그 전에 이미 저장된
news 문서를 url로 다시 방문해서 news_collector.py의 _extract_page_published_date()와
완전히 같은 로직으로 게재일을 재확인하고, 값이 다르면 바로잡음. (같은 함수를 그대로 import해서
쓰기 때문에 로직이 어긋날 일이 없음 — 나중에 그쪽을 고치면 이 스크립트도 자동으로 같이 고쳐짐.)

본문(content)/chunks/embedding은 전혀 안 건드림 — documents.published_at 컬럼만 갱신.

페이지에 게재일 메타데이터가 아예 없는 경우(구식 사이트, 메타태그 미제공 등)는 기존 값을
함부로 지우지 않고 그대로 둠 — "메타데이터가 없다"가 "기존 값이 틀렸다"를 증명하진 않으므로.

실행 (secondpj 루트에서, venv 활성화 상태로):
    python -m rag.scripts.backfill_fix_published_dates              # 뭐가 바뀔지만 미리 확인 (기본, 안전)
    python -m rag.scripts.backfill_fix_published_dates --apply       # 실제로 DB에 반영

--dry-run이 기본값인 이유: 이 스크립트는 news 문서 전체를 다시 fetch하는 대규모 작업이라
먼저 훑어보고 바뀔 항목 수를 눈으로 확인한 뒤에 실제 반영하는 게 안전함.
"""
from __future__ import annotations

import sys
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

from collector.news_collector import _BROWSER_HEADERS, _extract_page_published_date
from rag import config

# news_collector.py와 동일한 정중한 간격 — 짧은 시간에 같은 매체로 요청이 몰려서
# 403/429로 차단당하는 걸 피하기 위함. 이미 저장된 문서를 전부 재방문하는 대량 작업이라
# 특히 더 지켜야 함.
SLEEP_SEC = 1.0


def _fetch_page_date(url: str) -> date | None:
    resp = requests.get(url, timeout=10, headers=_BROWSER_HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return _extract_page_published_date(soup)


def main() -> None:
    apply_changes = "--apply" in sys.argv

    with config.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.id, d.url, d.published_at, d.title, s.name
                FROM documents d
                JOIN sources s ON s.id = d.source_id
                WHERE d.document_type = 'news' AND d.url IS NOT NULL
                ORDER BY d.created_at;
                """
            )
            rows = cur.fetchall()

        mode_label = "실제 반영 모드" if apply_changes else "dry-run (미리보기만, DB는 안 건드림)"
        print(f"검사 대상 news 문서 {len(rows)}건 — {mode_label}")

        changed = 0
        unchanged = 0
        no_page_date = 0
        failed = 0

        for doc_id, url, old_published_at, title, source_name in rows:
            try:
                page_date = _fetch_page_date(url)
            except Exception as e:  # noqa: BLE001 — 한 건 실패해도 나머지는 계속 진행
                print(f"[backfill] {doc_id} ({url}): 재방문 실패 — {e}")
                failed += 1
                time.sleep(SLEEP_SEC)
                continue

            if page_date is None:
                no_page_date += 1
                time.sleep(SLEEP_SEC)
                continue

            if page_date == old_published_at:
                unchanged += 1
                time.sleep(SLEEP_SEC)
                continue

            print(
                f"[backfill] {doc_id} ({source_name}) {title[:40]!r}: "
                f"{old_published_at} -> {page_date}  ({url})"
            )
            if apply_changes:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE documents SET published_at = %s WHERE id = %s;",
                        (page_date, doc_id),
                    )
                conn.commit()
            changed += 1
            time.sleep(SLEEP_SEC)

    verb = "변경" if apply_changes else "바뀔 것"
    print(
        f"\n끝 — {verb} {changed}건, 그대로 {unchanged}건, "
        f"페이지에 게재일 정보 없음(유지) {no_page_date}건, 재방문 실패 {failed}건"
    )
    if not apply_changes and changed:
        print("dry-run이었습니다 — 실제로 반영하려면 --apply를 붙여서 다시 실행하세요:")
        print("    python -m rag.scripts.backfill_fix_published_dates --apply")


if __name__ == "__main__":
    main()
