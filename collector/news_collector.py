"""
뉴스 기사 수집기 (RSS + NewsAPI, requests + BeautifulSoup으로 본문 추출).

모든 collector는 같은 규약을 따름:
    collect() -> list[dict]
    반환 dict 키는 documents 테이블 컬럼과 1:1 대응:
        title, content, url, author, category, document_type,
        published_at (date), language, source_name

source_name은 sources.name과 매칭해서 source_id를 찾는 데 씀(없으면 upsert).
실제 저장은 preprocessing/dedupe.py를 거친 뒤 DB에 넣는다 (여기서는 수집만).

2026-09-16 추가: 구글 뉴스 RSS(news.google.com)는 robots.txt가 스크래핑을 막고 있어서
포기하고, 대신 NewsAPI.org(https://newsapi.org)를 붙임 — 쿼리 기반이라 paper_collector처럼
검색어를 늘리면 볼륨을 늘릴 수 있음(RSS 피드는 "최근 몇십 건"만 보여줘서 시간이 지나야만 쌓임).
NEWSAPI_KEY(.env)가 없으면 case_collector와 동일한 패턴으로 조용히 건너뜀 — 가입 전까지는
기존 RSS 피드 8개만 그대로 동작. NewsAPI 무료 플랜은 "개발/테스트용"이 원칙이라 상용 서비스에는
쓸 수 없다고 명시돼 있음 — 학교 프로젝트/리서치 용도로만 쓸 것. 응답의 content 필드는 무료
플랜에서 200자로 잘려 나와서(article 전문이 아님) 그대로 저장하지 않고, url만 가져와서 기존
_extract_body()로 본문을 직접 긁어옴 — RSS 경로와 완전히 같은 본문 추출/품질 기준을 탐.
"""
from __future__ import annotations

import os
import re
import time
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse

import feedparser  # pip install feedparser
import requests
from bs4 import BeautifulSoup  # pip install beautifulsoup4
from dotenv import load_dotenv

from rag.preprocessing.clean_html import is_too_short, normalize_whitespace, strip_noise_tags

# 다른 collector들은 database.config/rag.config를 거치면서 load_dotenv()가 이미 호출되지만,
# news_collector는 그걸 안 거치는 독립 모듈이라(case_collector.py에서 겪은 것과 같은 버그) 직접 호출.
load_dotenv()

# 실제 fetch해서 살아있는 걸 확인한 RSS 주소만 등록 (2026-09-15 기준).
# 관련성 없는 기사는 pipeline.ingest의 LLM 관련성판정에서 자동으로 걸러지므로,
# 소스 자체는 "AI/음악산업" 태그가 있는 매체 위주로 골라서 적중률을 높임.
FEEDS: dict[str, str] = {
    "전자신문(AI)": "http://rss.etnews.com/04046.xml",
    "Music Business Worldwide": "https://www.musicbusinessworldwide.com/feed/",
    "Digital Music News": "https://www.digitalmusicnews.com/feed/",
    "MusicTech": "https://www.musictech.com/feed/",
    "Complete Music Update": "https://completemusicupdate.com/feed/",
    "Water & Music": "https://newsletter.waterandmusic.com/rss",
    "The Trichordist": "https://thetrichordist.com/feed/",
    # 2026-09-16: "한국저작권위원회 보도자료"는 여기서 제거함 — 이 RSS는 <link>가 없는 형식이라
    # 아래 collect()가 entry.link에 그대로 접근하면 AttributeError로 collect() 전체가 죽는 버그가
    # 있었음(실제로 한 번도 안 걸렸다면 이 소스가 그동안 빈 결과였거나 아직 안 돌려봤다는 뜻).
    # policy_collector.py에 목록 페이지 매칭까지 포함해서 제대로 옮겨 구현해뒀으니 그쪽을 볼 것.
}

# 매체별 실제 게재 언어 — pipeline.ingest의 번역 단계(document_type != "paper" and language != "ko"
# 인 문서만 번역)가 이 값을 보고 판단하므로 반드시 실제 언어와 맞춰야 함. 안 적어두면 "ko"로 간주.
FEED_LANGUAGE: dict[str, str] = {
    "전자신문(AI)": "ko",
    "Music Business Worldwide": "en",
    "Digital Music News": "en",
    "MusicTech": "en",
    "Complete Music Update": "en",
    "Water & Music": "en",
    "The Trichordist": "en",
}

# 참고: 아래는 확인해봤지만 일부러 안 넣은 후보들 — 필요하면 언제든 재검토 가능.
# - AI타임스(aitimes.com): RSS는 살아있으나 일반 AI 뉴스라 음악 관련성이 낮음(관련성판정 비용만 늘 것으로 예상).
# - Hypebot(hypebot.com): RSS는 살아있으나 최신 항목이 대부분 "주간 요약"류 일반 음악산업 뉴스라
#   AI/저작권 관련성이 낮음. AI 전용 카테고리 피드(/category/artificial-intelligence/feed/)는 404.
# - IPWatchdog(ipwatchdog.com): RSS는 살아있으나 특허법 위주라 음악/AI 관련 항목이 거의 없음.

# documents.category는 NOT NULL이라 수집 시점에 임시값이 필요해서 넣는 기본 힌트.
# 2026-09-16: 예전엔 이 값이 그대로 저장돼서 뉴스 54건 전부 "음성복제"로 잘못 찍히는 버그가 있었음
# (실제 기사 내용과 무관하게 고정값이 저장됨). 지금은 rag/pipeline/ingest.py가 LLM_PROVIDER 설정 시
# 문서 실제 내용을 보고 category를 다시 분류해서 이 값을 덮어쓰므로, 이건 LLM 판정 전 임시값 +
# LLM_PROVIDER 미설정 시의 폴백으로만 쓰임.
CATEGORY_HINT_DEFAULT = "AI작곡"  # 특정 카테고리로 쏠리지 않게 중립적인 기본값으로 변경(예전 "음성복제"는
# LLM_PROVIDER 없이 돌리면 그대로 저장되니 특정 카테고리 하나로 고정하지 않는 게 덜 나쁨)

# 실제 브라우저에 가까운 헤더 — official_collector.py/policy_collector.py와 동일한 이유
# (봇 차단 있는 매체에서 403 줄이기). NewsAPI가 물어다 주는 기사는 출처가 훨씬 다양해서
# 예전의 "Mozilla/5.0" 하나짜리 UA보다 이게 더 안전함.
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "").strip()
NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_INTERVAL_SEC = 1  # 무료 플랜 100req/day라 요청 자체를 아껴 써야 함 — 쿼리 8개면 하루치의 8%

# 카테고리당 (검색어, language) — language="en"은 NewsAPI가 실제로 지원하는 코드라 확실히 필터링됨.
# 한국어("ko")는 NewsAPI language 파라미터가 지원하는 목록에 없어서(공식 문서 기준) None으로 두고
# 한국어 쿼리로만 유도 — 그래서 영어 기사가 섞여 들어올 수 있고, 실제 언어는 _detect_language()로
# 기사 본문을 보고 다시 판별해서 채움(안 그러면 번역 단계가 엉뚱하게 스킵되는 문제가 생김).
NEWSAPI_QUERIES: dict[str, list[tuple[str, str | None]]] = {
    "저작권": [("AI music copyright lawsuit", "en"), ("인공지능 음악 저작권", None)],
    "창작자성": [("AI generated music authorship", "en"), ("인공지능 창작물 저작자", None)],
    "음성복제": [("AI voice cloning music", "en"), ("AI 음성복제 논란", None)],
    "AI작곡": [("Suno Udio AI music generator", "en"), ("생성형 AI 작곡", None)],
}

_HANGUL_RE = re.compile(r"[가-힣]")

# 2026-09-16: "한국 뉴스도 많이 모아야됨" — NewsAPI는 한국 매체 커버리지가 약해서
# (language="ko" 자체를 지원 안 함, 한국어 쿼리로 유도해도 결과가 영어권 위주) 네이버 뉴스
# 검색 API를 추가함. 국내 매체 커버리지가 훨씬 좋고 sort=date로 최신순 정렬도 확실함.
#
# 주의: 예전엔 개발자센터(developers.naver.com)에서 바로 발급받는 구조였는데, 2026년에
# 검색 API가 "NAVER API HUB"(네이버클라우드플랫폼 산하)로 이관되면서 발급 경로/엔드포인트/
# 인증 헤더가 전부 바뀜(개발자센터 쪽엔 이제 "검색" 항목 자체가 없어서 헷갈리기 쉬움).
#   - 발급: https://www.ncloud.com/product/applicationService/naverApiHub 에서
#     "신청하기" -> 네이버클라우드플랫폼(NCP) 계정으로 로그인/가입 -> Application 등록
#   - 무료 한도: 일 25,000건 (2026-09-16 기준, 콘솔에서 재확인 권장)
#   - 기존 openapi.naver.com 키는 2027-06-30까지만 유효 — 새로 받는 거면 처음부터
#     API HUB 쪽으로 받을 것(아래 코드도 API HUB 엔드포인트/헤더 기준으로 작성함).
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "").strip()
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
NAVER_NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
NAVER_NEWS_DISPLAY = 100  # 요청당 최대치
NAVER_NEWS_INTERVAL_SEC = 1  # 무료 한도 보호용 — 쿼리 8개면 초 단위로도 충분히 여유있음

# 검색어는 한국어로 — NAVER는 한국 매체 전용이라 한국어 쿼리가 훨씬 잘 맞음.
NAVER_NEWS_QUERIES: dict[str, list[str]] = {
    "저작권": ["AI 음악 저작권", "생성형 AI 음악 저작권 침해"],
    "창작자성": ["AI 창작물 저작자", "인공지능 창작 주체성"],
    "음성복제": ["AI 음성복제", "딥페이크 보이스 논란"],
    "AI작곡": ["생성형 AI 작곡", "수노 유디오 AI 음악"],
}

_TAG_RE = re.compile(r"</?b>")


def _clean_naver_text(raw: str) -> str:
    """title/description에 검색어 강조용 <b> 태그 + HTML 엔티티(&quot; 등)가 섞여 나와서 정리."""
    return unescape(_TAG_RE.sub("", raw or "")).strip()


def _parse_naver_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError):
        return None


def _fetch_naver_news(query: str) -> list[dict]:
    resp = requests.get(
        NAVER_NEWS_URL,
        params={"query": query, "display": NAVER_NEWS_DISPLAY, "sort": "date"},
        headers={
            "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
            "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def _detect_language(text: str) -> str:
    """한글이 섞여 있으면 ko, 아니면 en — NewsAPI가 language 필터를 못 거는 한국어 쿼리 결과의
    실제 언어를 판별하는 용도(쿼리 의도와 실제 기사 언어가 다를 수 있어서 결과를 보고 재확인)."""
    return "ko" if _HANGUL_RE.search(text) else "en"


def _parse_newsapi_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").date()
    except ValueError:
        return None


def _fetch_newsapi(query: str, language: str | None) -> list[dict]:
    params = {
        "q": query,
        "sortBy": "publishedAt",
        "pageSize": 100,
        "apiKey": NEWSAPI_KEY,
    }
    if language:
        params["language"] = language
    resp = requests.get(NEWSAPI_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(data.get("message", "NewsAPI 응답 오류"))
    return data.get("articles", [])


def _extract_body(url: str) -> str:
    """기사 본문만 추출 — 광고/메뉴/스크립트는 clean_html.strip_noise_tags()로 먼저 제거."""
    resp = requests.get(url, timeout=10, headers=_BROWSER_HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    strip_noise_tags(soup)
    article = soup.find("article") or soup.find("body")
    text = article.get_text(separator="\n", strip=True) if article else ""
    return normalize_whitespace(text)


def collect() -> list[dict]:
    results: list[dict] = []
    seen_urls: set[str] = set()

    for source_name, feed_url in FEEDS.items():
        parsed = feedparser.parse(feed_url)
        for entry in parsed.entries:
            # entry.link로 직접 접근하면 <link>가 없는 피드(예전 저작권위원회 RSS)에서
            # AttributeError로 collect() 전체가 죽었던 버그가 있었음 — .get()으로 방어.
            link = entry.get("link", "")
            if not link or link in seen_urls:
                continue

            try:
                content = _extract_body(link)
            except Exception as e:  # noqa: BLE001 — 수집 단계에서는 개별 실패를 건너뛰고 계속 진행
                print(f"[news_collector] {link} 수집 실패: {e}")
                continue

            if is_too_short(content):
                print(f"[news_collector] {link} 본문이 너무 짧아 스킵 ({len(content)}자)")
                continue

            seen_urls.add(link)
            published_at = date.today()
            if entry.get("published_parsed"):
                try:
                    published_at = date(*entry.published_parsed[:3])
                except (TypeError, ValueError):
                    pass

            results.append(
                {
                    "title": entry.get("title", ""),
                    "content": content,
                    "url": link,
                    "author": entry.get("author", None),
                    "category": CATEGORY_HINT_DEFAULT,
                    "document_type": "news",
                    "published_at": published_at,
                    "language": FEED_LANGUAGE.get(source_name, "ko"),
                    "source_name": source_name,
                }
            )

    # NewsAPI — NEWSAPI_KEY(.env) 없으면 건너뜀 (case_collector.py와 동일 패턴)
    if not NEWSAPI_KEY:
        print("[news_collector] NEWSAPI_KEY 미설정 — NewsAPI 검색 건너뜀 (newsapi.org 가입 후 .env에 추가할 것)")
    else:
        for category, queries in NEWSAPI_QUERIES.items():
            for query, language in queries:
                try:
                    articles = _fetch_newsapi(query, language)
                except Exception as e:  # noqa: BLE001 — 한 쿼리 실패해도 나머지는 계속 진행
                    print(f"[news_collector] NewsAPI '{query}' 조회 실패: {e}")
                    continue

                for article in articles:
                    url = article.get("url")
                    # NewsAPI는 원문이 내려간 기사를 title/source.name="[Removed]", url="https://removed.com"
                    # 으로 채워서 그대로 돌려줌 — 실제 내용이 없으니 미리 걸러냄(안 걸러도 _extract_body에서
                    # 실패하긴 하겠지만, 매번 불필요한 요청을 보내는 걸 막기 위해 여기서 먼저 체크).
                    if not url or url in seen_urls or article.get("title") == "[Removed]":
                        continue

                    try:
                        content = _extract_body(url)
                    except Exception as e:  # noqa: BLE001
                        print(f"[news_collector] {url} 수집 실패: {e}")
                        continue

                    if is_too_short(content):
                        print(f"[news_collector] {url} 본문이 너무 짧아 스킵 ({len(content)}자)")
                        continue

                    seen_urls.add(url)
                    title = article.get("title") or ""
                    source_label = (article.get("source") or {}).get("name") or "알 수 없음"
                    results.append(
                        {
                            "title": title,
                            "content": content,
                            "url": url,
                            "author": article.get("author"),
                            "category": category,
                            "document_type": "news",
                            "published_at": _parse_newsapi_date(article.get("publishedAt")),
                            "language": _detect_language(title + " " + content[:200]),
                            "source_name": f"NewsAPI: {source_label}",
                        }
                    )

                time.sleep(NEWSAPI_INTERVAL_SEC)

    # 네이버 뉴스 검색 API — NAVER_CLIENT_ID/SECRET(.env) 없으면 건너뜀
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        print(
            "[news_collector] NAVER_CLIENT_ID/NAVER_CLIENT_SECRET 미설정 — 네이버 뉴스 검색 건너뜀 "
            "(developers.naver.com 애플리케이션 등록 후 .env에 추가할 것)"
        )
    else:
        for category, queries in NAVER_NEWS_QUERIES.items():
            for query in queries:
                try:
                    items = _fetch_naver_news(query)
                except Exception as e:  # noqa: BLE001
                    print(f"[news_collector] 네이버뉴스 '{query}' 조회 실패: {e}")
                    continue

                for item in items:
                    # originallink(실제 언론사 원문)을 우선 사용 — link는 네이버뉴스 미러 URL이라
                    # 원문이 더 안정적인 출처 표시가 됨. 일부 기사는 originallink가 비어있어서 폴백.
                    url = item.get("originallink") or item.get("link")
                    if not url or url in seen_urls:
                        continue

                    try:
                        content = _extract_body(url)
                    except Exception as e:  # noqa: BLE001
                        print(f"[news_collector] {url} 수집 실패: {e}")
                        continue

                    if is_too_short(content):
                        print(f"[news_collector] {url} 본문이 너무 짧아 스킵 ({len(content)}자)")
                        continue

                    seen_urls.add(url)
                    title = _clean_naver_text(item.get("title", ""))
                    domain = urlparse(url).netloc.replace("www.", "")
                    results.append(
                        {
                            "title": title,
                            "content": content,
                            "url": url,
                            "author": None,
                            "category": category,
                            "document_type": "news",
                            "published_at": _parse_naver_date(item.get("pubDate")),
                            "language": "ko",
                            "source_name": f"네이버뉴스: {domain}",
                        }
                    )

                time.sleep(NAVER_NEWS_INTERVAL_SEC)

    return results


if __name__ == "__main__":
    docs = collect()
    print(f"{len(docs)}건 수집")
