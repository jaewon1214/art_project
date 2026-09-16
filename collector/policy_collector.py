"""
정책/법령 자료 수집기 (한국저작권위원회, 문화체육관광부, US Copyright Office 등).

news_collector.py와 같은 규약: collect() -> list[dict] (documents 컬럼과 1:1 대응).
정책 사이트는 페이지 구조가 제각각이라 사이트별로 함수를 나눠서 관리하는 걸 권장.
"""
from __future__ import annotations

from datetime import date

import requests
from bs4 import BeautifulSoup

from rag.preprocessing.clean_html import is_too_short, normalize_whitespace, strip_noise_tags

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
# 예전 "Mozilla/5.0" 하나짜리 UA는 WIPO처럼 봇 차단이 있는 사이트에서 403을 유발함 —
# 완전한 봇 우회를 보장하진 않지만(Cloudflare 등은 더 정교한 차단도 함) 실제 브라우저에
# 가까운 헤더로 개선. 그래도 막히면 해당 소스는 requests 방식으로는 한계로 보고 포기할 것.

# 실제 fetch해서 살아있는 것만 확인해서 등록 (2026-09-15 기준).
# language: pipeline.ingest 번역 단계 판단 기준 — 꼭 실제 언어로 맞출 것.
# (예전엔 이 리스트 전체가 "language": "ko" 하드코딩이라 US Copyright Office 등 영어 문서도
#  ko로 잘못 찍혀서 번역 대상에서 빠지는 버그가 있었음 — 이번에 항목별로 명시하면서 같이 고침)
TARGET_PAGES: list[dict] = [
    {"source_name": "한국저작권위원회", "url": "https://www.copyright.or.kr/notify/press-release/view.do?brdctsno=55878", "category": "저작권", "language": "ko"},
    {"source_name": "US Copyright Office", "url": "https://www.copyright.gov/ai/", "category": "저작권", "language": "en"},
    # EUR-Lex 원문 페이지는 실제로 돌려보니 0자 수집(JS 렌더링/첨부파일 기반이라 requests로는 본문이 안 잡힘) —
    # 유럽집행위원회(EC) 공식 AI Act 정책 설명 페이지로 교체함 (직접 fetch해서 본문 텍스트 있는 거 확인).
    {"source_name": "European Commission (AI Act)", "url": "https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai", "category": "저작권", "language": "en"},
    {
        "source_name": "WIPO",
        "url": "https://www.wipo.int/en/web/frontier-technologies/artificial-intelligence/index",
        "category": "저작권",
        "language": "en",
    },
    {
        "source_name": "UK Government (DSIT/DCMS/IPO)",
        "url": "https://www.gov.uk/government/publications/report-and-impact-assessment-on-copyright-and-artificial-intelligence/report-on-copyright-and-artificial-intelligence",
        "category": "저작권",
        "language": "en",
    },
    {
        "source_name": "Japan Agency for Cultural Affairs",
        "url": "https://www.bunka.go.jp/english/policy/copyright/",
        "category": "저작권",
        "language": "en",
    },
    {
        "source_name": "Canada (Canadian Heritage)",
        "url": "https://www.canada.ca/en/canadian-heritage/services/copyright-policy-publications.html",
        "category": "저작권",
        "language": "en",
    },
    {
        "source_name": "Singapore IPOS",
        "url": "https://www.ipos.gov.sg/about-ip/copyright/copyright-resources/",
        "category": "저작권",
        "language": "en",
    },
    # --- 2026-09-16 추가: official+policy+case 우선 확장 요청에 따라 보강 ---
    # 호주 정부(Attorney-General's Department) CAIRG 페이지는 robots.txt가 스크래핑을
    # 막고 있어서 제외 — 다른 정부 페이지들처럼 requests로 그냥 긁으면 안 되는 사이트로 판단.
    {
        "source_name": "WIPO",
        "url": "https://www.wipo.int/en/web/frontier-technologies/artificial-intelligence/conversation",
        "category": "저작권",
        "language": "en",
    },
]


def _fetch_page(url: str) -> tuple[str, str]:
    """(title, content) 반환. 사이트마다 selector가 달라서 TODO로 남겨둠."""
    resp = requests.get(url, timeout=10, headers=_BROWSER_HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    strip_noise_tags(soup)
    body = soup.find("article") or soup.find("div", {"class": "content"}) or soup.find("body")
    content = body.get_text(separator="\n", strip=True) if body else ""
    return title, normalize_whitespace(content)


def collect() -> list[dict]:
    results: list[dict] = []
    for page in TARGET_PAGES:
        try:
            title, content = _fetch_page(page["url"])
        except Exception as e:  # noqa: BLE001
            print(f"[policy_collector] {page['url']} 수집 실패: {e}")
            continue

        if is_too_short(content):
            print(f"[policy_collector] {page['url']} 본문이 너무 짧아 스킵 ({len(content)}자)")
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
                "language": page.get("language", "ko"),
                "source_name": page["source_name"],
            }
        )
    return results


if __name__ == "__main__":
    docs = collect()
    print(f"{len(docs)}건 수집")
