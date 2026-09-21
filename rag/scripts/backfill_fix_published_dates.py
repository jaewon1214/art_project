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

2026-09-21 업데이트: 같은 종류의 사고가 또 발견됨 — "Digital Music News" 피드는
_extract_page_published_date()(meta/time/JSON-LD)와 RSS의 published_parsed 둘 다 실패해서
매번 조용히 수집일로 대체되고 있었음(실측: id=4986f260-d971-4647-8ecd-829c9789210c, Ashley
King 기사, 실제 게재일은 URL 슬러그상 2026-09-03인데 published_at=2026-09-16=created_at
날짜와 동일 — 같은 매체 문서 13건에서 동일 패턴 확인). news_collector.py 쪽에 (a) meta 태그
느슨한 매칭(속성 이름에 date/time/publish가 들어가면 전부 시도), (b) URL 경로의
/YYYY/MM/DD/ 패턴 추출(_extract_url_date — 워드프레스 계열 CMS에 흔한 패턴이라 특정 매체를
몰라도 커버됨), (c) RSS updated_parsed 폴백, (d) 폴백 발생 시 경고 로그, 이렇게 네 가지를
추가했음. 이 스크립트도 _extract_url_date를 같이 import해서 _extract_page_published_date(soup)가
실패하면 URL 패턴도 마저 시도하도록 맞춤 — 안 그러면 news_collector.py는 이미 고쳐졌는데 이
백필 스크립트만 구버전 로직으로 남아서, meta 태그 자체가 없는 Digital Music News 같은 사이트는
재방문해도 여전히 못 잡는 상태가 됨.

본문(content)/chunks/embedding은 전혀 안 건드림 — documents.published_at 컬럼만 갱신.

페이지에 게재일 정보가 끝까지(meta/time/JSON-LD/URL 패턴 다) 없는 경우는 기존 값을 함부로
지우지 않고 그대로 둠 — "메타데이터가 없다"가 "기존 값이 틀렸다"를 증명하진 않으므로.

실행 (secondpj 루트에서, venv 활성화 상태로):
    python -m rag.scripts.backfill_fix_published_dates                        # 미리보기 (기본, 안전)
    python -m rag.scripts.backfill_fix_published_dates --source="Digital Music News"   # 특정 매체만 미리보기
    python -m rag.scripts.backfill_fix_published_dates --apply --limit=20     # 소규모로 먼저 반영 확인
    python -m rag.scripts.backfill_fix_published_dates --apply                # 전체 반영

--dry-run이 기본값인 이유: news 문서 전체를 다시 fetch하는 대규모 작업이라 먼저 훑어보고
바뀔 항목 수를 눈으로 확인한 뒤에 실제 반영하는 게 안전함. --source/--limit은 이번에 발견된
Digital Music News처럼 특정 매체만 먼저 좁혀서 확인하고 싶을 때 씀 — backfill_fix_arxiv_paper_noise.py
등 다른 백필 스크립트와 동일하게 argparse 없이 "--flag=value" 형태로 받음.
"""
from __future__ import annotations

import sys
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

from collector.news_collector import (
    _BROWSER_HEADERS,
    _extract_page_published_date,
    _extract_url_date,
)
from rag import config

# news_collector.py와 동일한 정중한 간격 — 짧은 시간에 같은 매체로 요청이 몰려서
# 403/429로 차단당하는 걸 피하기 위함. 이미 저장된 문서를 전부 재방문하는 대량 작업이라
# 특히 더 지켜야 함.
SLEEP_SEC = 1.0


def _fetch_page_date(url: str) -> date | None:
    resp = requests.get(url, timeout=10, headers=_BROWSER_HEADERS)
    resp.raise_for_status()
    # 2026-09-19: resp.text 대신 resp.content — 서버가 charset을 안 밝히면 requests가
    # ISO-8859-1로 잘못 추측해서 UTF-8 페이지가 깨지는 버그 회피(news_collector.py/add_url.py와
    # 동일 이유 — BeautifulSoup 자체 인코딩 감지가 더 정확함).
    soup = BeautifulSoup(resp.content, "html.parser")
    # 2026-09-21: meta/time/JSON-LD가 다 실패해도 URL의 /YYYY/MM/DD/ 패턴으로 한 번 더 시도
    # (news_collector.py의 동일 폴백과 맞춤 — 자세한 이유는 위 모듈 docstring 참고).
    return _extract_page_published_date(soup) or _extract_url_date(url)


def main() -> None:
    apply_changes = "--apply" in sys.argv

    source_filter: str | None = None
    limit: int | None = None
    for arg in sys.argv:
        if arg.startswith("--source="):
            source_filter = arg.split("=", 1)[1]
        elif arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])

    with config.get_connection() as conn:
        with conn.cursor() as cur:
            if source_filter:
                cur.execute(
                    """
                    SELECT d.id, d.url, d.published_at, d.title, s.name
                    FROM documents d
                    JOIN sources s ON s.id = d.source_id
                    WHERE d.document_type = 'news' AND d.url IS NOT NULL AND s.name = %s
                    ORDER BY d.created_at;
                    """,
                    (source_filter,),
                )
            else:
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

        if limit is not None:
            rows = rows[:limit]

        mode_label = "실제 반영 모드" if apply_changes else "dry-run (미리보기만, DB는 안 건드림)"
        scope_label = f" (source={source_filter!r})" if source_filter else ""
        print(f"검사 대상 news 문서 {len(rows)}건{scope_label} — {mode_label}")

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
