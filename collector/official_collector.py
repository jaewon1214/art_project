"""
기업 공식 자료 수집기 (Suno, Udio, ElevenLabs 등의 공식 블로그/이용약관/저작권 정책 페이지).

news_collector.py와 같은 규약: collect() -> list[dict] (documents 컬럼과 1:1 대응).
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
# 리스트/블로그 인덱스 페이지는 넣지 말 것 — 메뉴/네비게이션 텍스트만 긁혀서 못 씀.
# 실제 내용이 있는 개별 문서(ToS, 가이드라인, FAQ 등) URL만 넣기.
# language: pipeline.ingest 번역 단계 판단 기준 — 안 적으면 collect()에서 기본값 "en" 적용
# (지금 등록된 페이지가 전부 영어라 기본값이 en. 한국어 공식페이지 추가되면 꼭 "ko" 명시할 것).
TARGET_PAGES: list[dict] = [
    {"source_name": "Suno", "url": "https://suno.com/terms-of-service", "category": "저작권", "language": "en"},
    {"source_name": "Suno", "url": "https://suno.com/community-guidelines", "category": "AI작곡", "language": "en"},
    {"source_name": "Suno", "url": "https://help.suno.com/en/articles/2746945", "category": "저작권", "language": "en"},
    {"source_name": "Suno", "url": "https://help.suno.com/en/articles/2416769", "category": "창작자성", "language": "en"},
    {"source_name": "Udio", "url": "https://www.udio.com/terms-of-service", "category": "저작권", "language": "en"},
    {
        "source_name": "IFPI",
        "url": "https://www.ifpi.org/music-community-introduces-new-labelling-program-to-distinguish-generative-ai-in-sound-recordings/",
        "category": "AI작곡",
        "language": "en",
    },
    {
        "source_name": "ElevenLabs",
        "url": "https://elevenlabs.io/use-policy",
        "category": "음성복제",
        "language": "en",
    },
    {
        "source_name": "ElevenLabs",
        "url": "https://elevenlabs.io/docs/help-center/legal/do-i-own-the-files-i-upload",
        "category": "저작권",
        "language": "en",
    },
    {"source_name": "AIVA", "url": "https://useaiva.com/terms", "category": "저작권", "language": "en"},
    {
        "source_name": "Stability AI",
        "url": "https://stability.ai/terms-of-service",
        "category": "저작권",
        "language": "en",
    },
    {"source_name": "Soundraw", "url": "https://soundraw.io/terms", "category": "저작권", "language": "en"},
    {
        "source_name": "Boomy",
        "url": "https://support.boomy.com/hc/en-us/articles/15261808044301-Who-owns-the-rights-to-Boomy-songs",
        "category": "창작자성",
        "language": "en",
    },
    {
        "source_name": "Boomy",
        "url": "https://support.boomy.com/hc/en-us/articles/17795290396173-Is-Boomy-compliant-with-copyright-laws-How-so",
        "category": "저작권",
        "language": "en",
    },
    {
        "source_name": "Endel",
        "url": "https://endel.zendesk.com/hc/en-us/articles/360003558200-General-terms-and-conditions-for-Endel-app",
        "category": "저작권",
        "language": "en",
    },
    # --- 2026-09-16 추가: official+policy+case 우선 확장 요청에 따라 보강 ---
    {"source_name": "Kits.AI", "url": "https://www.kits.ai/terms-of-service", "category": "음성복제", "language": "en"},
    {"source_name": "LANDR", "url": "https://www.landr.com/terms-of-service/", "category": "저작권", "language": "en"},
    {"source_name": "LANDR", "url": "https://www.landr.com/fairai", "category": "창작자성", "language": "en"},
    {"source_name": "Voicemod", "url": "https://www.voicemod.net/en/guidelines/", "category": "음성복제", "language": "en"},
    {"source_name": "Respeecher", "url": "https://www.respeecher.com/ethics", "category": "음성복제", "language": "en"},
    {"source_name": "Beatoven.ai", "url": "https://www.beatoven.ai/tos", "category": "AI작곡", "language": "en"},
    {"source_name": "Loudly", "url": "https://www.loudly.com/terms-and-conditions", "category": "AI작곡", "language": "en"},
    {
        "source_name": "CISAC",
        "url": "https://www.cisac.org/artificial-intelligence-0",
        "category": "창작자성",
        "language": "en",
    },
    {
        "source_name": "NMPA",
        "url": "https://www.nmpa.org/nmpa-generative-ai-is-the-greatest-risk-to-the-human-creative-class-that-has-ever-existed/",
        "category": "저작권",
        "language": "en",
    },
]


def _fetch_page(url: str) -> tuple[str, str]:
    resp = requests.get(url, timeout=10, headers=_BROWSER_HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    strip_noise_tags(soup)
    body = soup.find("article") or soup.find("main") or soup.find("body")
    content = body.get_text(separator="\n", strip=True) if body else ""
    return title, normalize_whitespace(content)


def collect() -> list[dict]:
    results: list[dict] = []
    for page in TARGET_PAGES:
        try:
            title, content = _fetch_page(page["url"])
        except Exception as e:  # noqa: BLE001
            print(f"[official_collector] {page['url']} 수집 실패: {e}")
            continue

        if is_too_short(content):
            print(f"[official_collector] {page['url']} 본문이 너무 짧아 스킵 ({len(content)}자)")
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
                "language": page.get("language", "en"),
                "source_name": page["source_name"],
            }
        )
    return results


if __name__ == "__main__":
    docs = collect()
    print(f"{len(docs)}건 수집")
