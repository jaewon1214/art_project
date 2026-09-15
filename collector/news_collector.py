"""
뉴스 기사 수집기 (RSS 우선, 없으면 requests + BeautifulSoup).

모든 collector는 같은 규약을 따름:
    collect() -> list[dict]
    반환 dict 키는 documents 테이블 컬럼과 1:1 대응:
        title, content, url, author, category, document_type,
        published_at (date), language, source_name

source_name은 sources.name과 매칭해서 source_id를 찾는 데 씀(없으면 upsert).
실제 저장은 preprocessing/dedupe.py를 거친 뒤 DB에 넣는다 (여기서는 수집만).
"""
from __future__ import annotations

from datetime import date

import feedparser  # pip install feedparser
import requests
from bs4 import BeautifulSoup  # pip install beautifulsoup4

# 실제 fetch해서 살아있는 걸 확인한 RSS 주소만 등록 (2026-09-15 기준).
# 관련성 없는 기사는 pipeline.ingest의 LLM 관련성판정에서 자동으로 걸러지므로,
# 소스 자체는 "AI/음악산업" 태그가 있는 매체 위주로 골라서 적중률을 높임.
FEEDS: dict[str, str] = {
    "전자신문(AI)": "http://rss.etnews.com/04046.xml",
    "Music Business Worldwide": "https://www.musicbusinessworldwide.com/feed/",
}

CATEGORY_HINT_DEFAULT = "음성복제"  # TODO: 기사 내용 기반으로 분류하는 로직으로 교체


def _extract_body(url: str) -> str:
    """기사 본문만 추출 (광고/메뉴 제거는 preprocessing/clean_html.py에서 한 번 더 정제)."""
    resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    article = soup.find("article") or soup.find("body")
    return article.get_text(separator="\n", strip=True) if article else ""


def collect() -> list[dict]:
    results: list[dict] = []
    for source_name, feed_url in FEEDS.items():
        parsed = feedparser.parse(feed_url)
        for entry in parsed.entries:
            try:
                content = _extract_body(entry.link)
            except Exception as e:  # noqa: BLE001 — 수집 단계에서는 개별 실패를 건너뛰고 계속 진행
                print(f"[news_collector] {entry.link} 수집 실패: {e}")
                continue

            results.append(
                {
                    "title": entry.get("title", ""),
                    "content": content,
                    "url": entry.link,
                    "author": entry.get("author", None),
                    "category": CATEGORY_HINT_DEFAULT,
                    "document_type": "news",
                    "published_at": date.today(),  # TODO: entry.published_parsed 파싱해서 실제 발행일로 교체
                    "language": "ko",
                    "source_name": source_name,
                }
            )
    return results


if __name__ == "__main__":
    docs = collect()
    print(f"{len(docs)}건 수집")
