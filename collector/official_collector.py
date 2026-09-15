"""
기업 공식 자료 수집기 (Suno, Udio, ElevenLabs 등의 공식 블로그/이용약관/저작권 정책 페이지).

news_collector.py와 같은 규약: collect() -> list[dict] (documents 컬럼과 1:1 대응).
"""
from __future__ import annotations

from datetime import date

import requests
from bs4 import BeautifulSoup

# 실제 fetch해서 살아있는 것만 확인해서 등록 (2026-09-15 기준).
# 리스트/블로그 인덱스 페이지는 넣지 말 것 — 메뉴/네비게이션 텍스트만 긁혀서 못 씀.
# 실제 내용이 있는 개별 문서(ToS, 가이드라인, FAQ 등) URL만 넣기.
TARGET_PAGES: list[dict] = [
    {"source_name": "Suno", "url": "https://suno.com/terms-of-service", "category": "저작권"},
    {"source_name": "Suno", "url": "https://suno.com/community-guidelines", "category": "AI작곡"},
    {"source_name": "Suno", "url": "https://help.suno.com/en/articles/2746945", "category": "저작권"},
    {"source_name": "Suno", "url": "https://help.suno.com/en/articles/2416769", "category": "창작자성"},
]


def _fetch_page(url: str) -> tuple[str, str]:
    resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    body = soup.find("article") or soup.find("main") or soup.find("body")
    content = body.get_text(separator="\n", strip=True) if body else ""
    return title, content


def collect() -> list[dict]:
    results: list[dict] = []
    for page in TARGET_PAGES:
        try:
            title, content = _fetch_page(page["url"])
        except Exception as e:  # noqa: BLE001
            print(f"[official_collector] {page['url']} 수집 실패: {e}")
            continue

        results.append(
            {
                "title": title,
                "content": content,
                "url": page["url"],
                "author": None,
                "category": page.get("category", "AI작곡"),
                "document_type": "official",
                "published_at": date.today(),  # TODO: 페이지에서 게시일 파싱
                "language": "en",
                "source_name": page["source_name"],
            }
        )
    return results


if __name__ == "__main__":
    docs = collect()
    print(f"{len(docs)}건 수집")
