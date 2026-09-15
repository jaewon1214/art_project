"""
정책/법령 자료 수집기 (한국저작권위원회, 문화체육관광부, US Copyright Office 등).

news_collector.py와 같은 규약: collect() -> list[dict] (documents 컬럼과 1:1 대응).
정책 사이트는 페이지 구조가 제각각이라 사이트별로 함수를 나눠서 관리하는 걸 권장.
"""
from __future__ import annotations

from datetime import date

import requests
from bs4 import BeautifulSoup

# 실제 fetch해서 살아있는 것만 확인해서 등록 (2026-09-15 기준).
TARGET_PAGES: list[dict] = [
    {"source_name": "한국저작권위원회", "url": "https://www.copyright.or.kr/notify/press-release/view.do?brdctsno=55878", "category": "저작권"},
    {"source_name": "US Copyright Office", "url": "https://www.copyright.gov/ai/", "category": "저작권"},
]


def _fetch_page(url: str) -> tuple[str, str]:
    """(title, content) 반환. 사이트마다 selector가 달라서 TODO로 남겨둠."""
    resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    body = soup.find("article") or soup.find("div", {"class": "content"}) or soup.find("body")
    content = body.get_text(separator="\n", strip=True) if body else ""
    return title, content


def collect() -> list[dict]:
    results: list[dict] = []
    for page in TARGET_PAGES:
        try:
            title, content = _fetch_page(page["url"])
        except Exception as e:  # noqa: BLE001
            print(f"[policy_collector] {page['url']} 수집 실패: {e}")
            continue

        results.append(
            {
                "title": title,
                "content": content,
                "url": page["url"],
                "author": None,
                "category": page.get("category", "저작권"),
                "document_type": "policy",
                "published_at": date.today(),  # TODO: 페이지에서 게시일 파싱
                "language": "ko",
                "source_name": page["source_name"],
            }
        )
    return results


if __name__ == "__main__":
    docs = collect()
    print(f"{len(docs)}건 수집")
