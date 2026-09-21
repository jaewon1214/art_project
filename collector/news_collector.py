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

import json
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

from rag.preprocessing.clean_html import (
    is_too_short,
    normalize_whitespace,
    strip_boilerplate_lines,
    strip_noise_tags,
)

from database.config import get_connection

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
    # 2026-09-16: 뉴스와이어(newswire.co.kr) — 보도자료 배급사라 원래 RSS로 재배포되는 용도로
    # 만들어진 곳(api.newswire.co.kr는 robots.txt가 전체 허용). 키/가입 없이 바로 쓸 수 있고
    # 실시간(당일 몇 시간 단위)으로 갱신됨. "인공지능"/"음악" 전용 카테고리가 따로 있어서 주제
    # 적중률도 기대할 만함 — 다만 보도자료 특성상 무관한 공연/행사 홍보성 글도 섞여 나옴
    # (LLM 관련성판정 호출이 그만큼 더 늚 — LLM_PROVIDER 미설정이면 전부 그대로 저장되니 주의).
    "뉴스와이어(인공지능)": "https://api.newswire.co.kr/rss/industry/615",
    "뉴스와이어(음악)": "https://api.newswire.co.kr/rss/industry/1205",
    # 2026-09-16: "피드 최대한 많이, 한국에서만 관련된 걸로" 요청으로 추가 조사.
    # 뉴스와이어 산업(1200번대)/테마 카테고리를 전부 훑어보고 실제 최근 항목까지 확인해봤는데,
    # 아래는 넣고 아래아래는 일부러 뺀 것 — 실제로 fetch해서 내용을 보고 판단함:
    #   뺀 것: 소송(theme/124, 대부분 해외 반도체/제약 특허소송이라 "한국 관련"에 안 맞음),
    #          연예인(industry/1207, 실제로는 패션/건강기능식품 협찬 홍보성 글이 대부분이라
    #          AI/저작권과 관련성이 거의 없었음), 방송(industry/1213, TV 편성 홍보 위주).
    #   넣은 것: 지식재산(주제 전체는 특허 위주로 노이즈가 있지만, 저작권 카테고리와 그나마
    #          제일 가까운 테마라 추가 — LLM 관련성판정이 잘 걸러줄 거라고 기대).
    "뉴스와이어(지식재산)": "https://api.newswire.co.kr/rss/theme/129",
    # 한국콘텐츠진흥원(KOCCA) — 콘텐츠산업 정책/지원 주관 정부기관 보도자료. AI/음악 전용은
    # 아니지만 콘텐츠산업 전반(게임/애니/음악 등)을 다뤄서 관련 정책 발표를 잡을 가능성이 있음.
    "한국콘텐츠진흥원 보도자료": "http://www.kocca.kr/xml/notice/newreport/newrss.xml",
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
    "뉴스와이어(인공지능)": "ko",
    "뉴스와이어(음악)": "ko",
    "뉴스와이어(지식재산)": "ko",
    "한국콘텐츠진흥원 보도자료": "ko",
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
    "저작권": [
        ("AI music copyright lawsuit", "en"),
        ("인공지능 음악 저작권", None),
        # 2026-09-17: "Concord Music Group v. Anthropic"(2023년 제소, UMG/ABKCO 공동)처럼
        # 랜드마크 사건 자체를 직접 겨냥한 쿼리 — 일반 카테고리 쿼리("AI music copyright
        # lawsuit")만으로는 이런 특정 사건의 1차 기사가 안 걸리고, 나중에 터진 후속 소송
        # 기사 안에 배경으로만 짧게 언급되는 형태로만 코퍼스에 들어오는 문제가 있었음
        # (rag/tests에서 확인). NewsAPI 무료 플랜은 최근 ~1개월 기사만 검색되므로 2023년
        # 원문 기사 자체는 이 쿼리로도 못 얻을 수 있음 — 과거 사건은
        # seed_concord_case_document.py 같은 수동 시드로 보강하고, 이 쿼리는 향후 나오는
        # 후속 보도(판결/화해 등)를 놓치지 않기 위한 용도.
        ("Concord Music Group Anthropic lawsuit", "en"),
        ("Universal Music Publishing ABKCO Anthropic", "en"),
    ],
    "창작자성": [
        ("AI generated music authorship", "en"),
        ("인공지능 창작물 저작자", None),
        # 2026-09-19 추가: 창작자성 카테고리 보강 요청 — US Copyright Office의 공식 authorship
        # 가이드라인/판단 보도까지 직접 겨냥(위 저작권 카테고리의 "랜드마크 사건 직접 쿼리"와
        # 같은 이유).
        ("US Copyright Office AI authorship", "en"),
    ],
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
NAVER_NEWS_DISPLAY = 100  # 요청당 최대치 — 데이터는 많을수록 좋다는 방침이라 축소하지 않음.
# 2026-09-16: 한때 20으로 줄였다가 되돌림. 대신 _load_known_urls()로 이미 DB에 있는
# url은 fetch 자체를 건너뛰게 해서, 볼륨은 유지하면서 중복 재수집만 막음.
NAVER_NEWS_INTERVAL_SEC = 1  # 무료 한도 보호용 — 쿼리 8개면 초 단위로도 충분히 여유있음

# 검색어는 한국어로 — NAVER는 한국 매체 전용이라 한국어 쿼리가 훨씬 잘 맞음.
NAVER_NEWS_QUERIES: dict[str, list[str]] = {
    "저작권": [
        "AI 음악 저작권",
        "생성형 AI 음악 저작권 침해",
        "콩코드뮤직그룹 앤스로픽",  # 위 NEWSAPI_QUERIES 주석 참고 — 랜드마크 사건 직접 쿼리
    ],
    "창작자성": ["AI 창작물 저작자", "인공지능 창작 주체성", "AI 저작물 인간 창작 기여"],
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
    # 데이터는 많을수록 좋다는 방침이라 pageSize는 최대치(100) 유지.
    # 2026-09-16: 한때 20으로 줄였다가 되돌림 — 대신 _load_known_urls()로 이미 DB에
    # 있는 url은 fetch 자체를 건너뛰게 해서, 볼륨은 유지하면서 중복 재수집만 막음.
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


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _parse_iso_like_date(raw: str | None) -> date | None:
    """meta 태그/JSON-LD에서 나오는 "2023-12-13T09:00:00+09:00" 류의 ISO 8601(비슷한) 문자열에서
    날짜만 뽑아냄. 초/타임존까지 파싱할 필요는 없고(우리가 저장하는 건 DATE 컬럼), 앞 10자리
    "YYYY-MM-DD"만 있으면 충분 — 사이트마다 초/타임존 표기가 제각각이라 datetime.fromisoformat()로
    엄격하게 파싱하면 실패하는 경우가 많아서 정규식으로 앞부분만 잘라 쓰는 쪽이 더 안정적임."""
    if not raw:
        return None
    raw = raw.strip()
    m = _ISO_DATE_RE.match(raw)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(0))
    except ValueError:
        return None


# 2026-09-19 추가: NewsAPI의 publishedAt이 실제로는 NewsAPI 자체의 크롤링/색인 시각을 반영하는
# 경우가 확인됨(NMPA 기사 — 실제 게재일 2023-12-13인데 published_at이 수집 당일로 저장된 사고).
# NewsAPI/RSS/네이버가 주는 날짜를 무조건 신뢰하지 않고, 기사 원문 페이지 자체의 메타데이터에서
# 게재일을 직접 뽑아서 있으면 그걸 최우선으로 씀. 아래 우선순위로 확인(매체마다 쓰는 태그가 달라서
# 여러 후보를 순서대로 시도) — 흔히 쓰이는 것부터.
_META_DATE_ATTRS: list[tuple[str, str]] = [
    ("property", "article:published_time"),
    ("property", "og:article:published_time"),
    ("name", "article:published_time"),
    ("name", "publish-date"),
    ("name", "publishdate"),
    ("name", "sailthru.date"),
    ("name", "date"),
    ("name", "pubdate"),
    ("itemprop", "datePublished"),
]
_JSONLD_DATE_KEYS = ("datePublished", "dateCreated", "uploadDate")


def _extract_page_published_date(soup: BeautifulSoup) -> date | None:
    """페이지 자체(<meta>/<time>/JSON-LD)에서 실제 게재일을 뽑아냄. RSS/API가 주는 날짜보다
    이쪽을 우선시함 — 주의: 이 함수는 반드시 strip_noise_tags(soup) 호출 *이전*에 실행해야 함.
    strip_noise_tags가 <script> 태그를 통째로 decompose()해버려서, 그 뒤에 부르면 JSON-LD
    (<script type="application/ld+json">)가 이미 사라지고 없음."""
    for attr, value in _META_DATE_ATTRS:
        tag = soup.find("meta", attrs={attr: value})
        if tag:
            parsed = _parse_iso_like_date(tag.get("content"))
            if parsed:
                return parsed

    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        parsed = _parse_iso_like_date(time_tag.get("datetime"))
        if parsed:
            return parsed

    for script_tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_json = script_tag.string
        if not raw_json:
            continue
        try:
            data = json.loads(raw_json)
        except (ValueError, TypeError):
            continue
        # JSON-LD는 단일 객체, 배열, 또는 "@graph" 안에 여러 객체가 들어있는 등 형태가 다양해서
        # 후보 객체 목록을 만들어 공통 처리.
        candidates: list[dict] = []
        if isinstance(data, dict):
            candidates.append(data)
            graph = data.get("@graph")
            if isinstance(graph, list):
                candidates.extend(item for item in graph if isinstance(item, dict))
        elif isinstance(data, list):
            candidates.extend(item for item in data if isinstance(item, dict))

        for candidate in candidates:
            for key in _JSONLD_DATE_KEYS:
                parsed = _parse_iso_like_date(candidate.get(key))
                if parsed:
                    return parsed

    # 2026-09-21 추가: 위 _META_DATE_ATTRS 하드코딩 목록에 없는 이름의 meta 태그를 쓰는
    # 사이트 대응(실측: Digital Music News — 위 세 가지 방법 다 실패해서 매번 수집일로
    # 잘못 저장되던 게 발견됨). 정확한 태그 이름을 사이트마다 추가하는 대신, 속성 이름에
    # "date"/"time"/"publish"가 들어간 모든 meta 태그를 느슨하게 훑어서 ISO 날짜로 파싱되는
    # 첫 값을 채택 — 사이트를 몰라도 커버되는 휴리스틱. 위 정확 매칭 목록을 먼저 시도하는
    # 이유는 순서 모호성(예: "modified"용 태그가 "published"보다 먼저 걸릴 위험)을 줄이기
    # 위함이고, 여기는 그게 다 실패했을 때만 쓰는 두 번째 방어선.
    for tag in soup.find_all("meta"):
        attr_val = (tag.get("property") or tag.get("name") or tag.get("itemprop") or "").lower()
        if any(kw in attr_val for kw in ("date", "time", "publish")):
            parsed = _parse_iso_like_date(tag.get("content"))
            if parsed:
                return parsed

    return None


# 2026-09-21 추가: meta/time/JSON-LD가 전부 실패했을 때 마지막으로 시도하는 URL 기반 폴백 —
# 워드프레스 계열 CMS(Digital Music News 등)는 게시물 URL 경로 자체에 "/YYYY/MM/DD/slug"
# 형태로 게재일이 박혀있는 경우가 흔함. 특정 매체를 하드코딩하지 않아도 되는 일반적인 패턴이라
# 사이트 이름을 몰라도 커버됨. 연/월/일 값 범위를 체크(월 1~12, 일 1~31)해서, 우연히 숫자 3개가
# 슬래시로 구분된 다른 경로(상품/기사 번호 등)를 날짜로 오인할 위험을 줄임.
_URL_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")


def _extract_url_date(url: str) -> date | None:
    path = urlparse(url).path
    m = _URL_DATE_RE.search(path)
    if not m:
        return None
    year, month, day = (int(g) for g in m.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_body(url: str) -> tuple[str, date | None]:
    """기사 본문 + 페이지에서 뽑은 게재일(date | None)을 함께 반환.
    광고/메뉴/스크립트는 clean_html.strip_noise_tags()로 먼저 제거.
    2026-09-16: <article> 태그 안쪽에 class로만 박혀있는 카테고리 메뉴/바이라인/공유 위젯
    (예: 데일리안)은 태그 기반 제거로 못 걸러져서 strip_boilerplate_lines()로 한 번 더 정리.
    2026-09-19: strip_noise_tags()가 <script> 태그를 지워버리므로, 페이지 게재일 추출
    (_extract_page_published_date)은 반드시 그 호출 전에 먼저 실행.
    2026-09-21: soup 기반 추출이 다 실패하면 URL 패턴 폴백(_extract_url_date)까지 시도 —
    둘 다 "페이지/URL 자체에서 나온 신호"라 RSS/API가 주는 날짜보다 우선시할 가치가 있어서
    같은 page_date 값으로 합쳐서 반환(호출부 코드를 안 바꿔도 되게)."""
    resp = requests.get(url, timeout=10, headers=_BROWSER_HEADERS)
    resp.raise_for_status()
    # 2026-09-19: resp.text 대신 resp.content(원본 바이트)를 넘김 — 서버가 응답 헤더에
    # charset을 안 밝히면 requests가 ISO-8859-1로 잘못 추측해서 UTF-8 페이지의 스마트
    # 따옴표/줄표(’/–/— 등)가 "â" 같은 글자로 깨지는 버그가 실제로 확인됨(Music Business
    # Worldwide 기사에서 "Dua Lipaâs" 식으로 깨짐). resp.content를 넘기면 BeautifulSoup이
    # 자체 인코딩 감지(UnicodeDammit — meta charset/BOM 등 실제 콘텐츠를 보고 판단)를 써서
    # 훨씬 안정적으로 맞춤.
    soup = BeautifulSoup(resp.content, "html.parser")
    page_date = _extract_page_published_date(soup) or _extract_url_date(url)
    strip_noise_tags(soup)
    article = soup.find("article") or soup.find("body")
    text = article.get_text(separator="\n", strip=True) if article else ""
    content = normalize_whitespace(strip_boilerplate_lines(text))
    return content, page_date


def _load_known_urls() -> set[str]:
    """documents 테이블에 이미 저장된 url을 미리 불러와서, 이미 수집한 기사는
    _extract_body() HTTP 요청 자체를 건너뛰기 위한 캐시.

    2026-09-16 추가: 기존에는 seen_urls가 "이번 실행 안에서"만 중복을 걸렀고,
    DB 레벨 중복(content_hash) 체크는 ingest_document() 안에서 본문을 이미 다
    긁어온 뒤에야 일어났음 — 그래서 RSS/NewsAPI/네이버에서 매번 같은 기사가
    다시 나와도 매일 똑같이 비싼 본문 fetch를 반복하고 있었음(뉴스 DAG가
    거의 1시간 걸린 핵심 원인 중 하나). DB 연결이 안 되는 환경(로컬 개발 등)
    에서는 그냥 빈 set을 반환해서 필터링 없이 기존 동작으로 안전하게 폴백.
    """
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT url FROM documents WHERE url IS NOT NULL")
                return {row[0] for row in cur.fetchall()}
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 — DB 불가 시 필터링 없이 계속 진행
        print(f"[news_collector] 기존 url 목록 로드 실패(필터 없이 진행): {e}")
        return set()


def collect() -> list[dict]:
    results: list[dict] = []
    seen_urls: set[str] = set()
    known_urls = _load_known_urls()  # 이미 DB에 있는 url은 본문 fetch 자체를 스킵

    for source_name, feed_url in FEEDS.items():
        parsed = feedparser.parse(feed_url)
        for entry in parsed.entries:
            # entry.link로 직접 접근하면 <link>가 없는 피드(예전 저작권위원회 RSS)에서
            # AttributeError로 collect() 전체가 죽었던 버그가 있었음 — .get()으로 방어.
            link = entry.get("link", "")
            if not link or link in seen_urls or link in known_urls:
                continue

            try:
                content, page_date = _extract_body(link)
            except Exception as e:  # noqa: BLE001 — 수집 단계에서는 개별 실패를 건너뛰고 계속 진행
                print(f"[news_collector] {link} 수집 실패: {e}")
                continue

            if is_too_short(content):
                print(f"[news_collector] {link} 본문이 너무 짧아 스킵 ({len(content)}자)")
                continue

            seen_urls.add(link)
            # 2026-09-19: 페이지 자체 메타데이터/URL에서 뽑은 게재일(page_date)을 최우선으로
            # 씀 — RSS의 published_parsed도 대체로 신뢰할 만하지만, 피드 자체가 재발행/재색인
            # 시각을 줄 수 있어서 페이지 원본 쪽이 더 정확함.
            # 2026-09-21: published_parsed 하나만 보다가, 그 필드가 없는 Atom 계열 피드 등을
            # 대응하기 위해 updated_parsed도 순서대로 시도하도록 추가. 실측(Digital Music News)
            # 결과 이 피드는 page_date/published_parsed/updated_parsed가 전부 실패해서 매번
            # 조용히 수집일로 대체되고 있었음이 확인됨 — 그래서 셋 다 실패하는 마지막 경우는
            # 더 이상 조용히 넘기지 않고 경고를 남겨서, 날짜가 통째로 틀리는 사고를 나중에
            # 스크린샷으로 우연히 발견하는 대신 로그로 바로 알아챌 수 있게 함.
            published_at = page_date
            if published_at is None:
                for date_field in ("published_parsed", "updated_parsed"):
                    parsed_time = entry.get(date_field)
                    if parsed_time:
                        try:
                            published_at = date(*parsed_time[:3])
                            break
                        except (TypeError, ValueError):
                            continue
            if published_at is None:
                published_at = date.today()
                print(
                    f"[news_collector] {link} — 게재일 추출 실패(meta/URL/RSS 전부 실패), "
                    "수집일로 대체합니다. 이 매체는 날짜 추출 로직 보강이 필요할 수 있습니다."
                )

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
                    if not url or url in seen_urls or url in known_urls or article.get("title") == "[Removed]":
                        continue

                    try:
                        content, page_date = _extract_body(url)
                    except Exception as e:  # noqa: BLE001
                        print(f"[news_collector] {url} 수집 실패: {e}")
                        continue

                    if is_too_short(content):
                        print(f"[news_collector] {url} 본문이 너무 짧아 스킵 ({len(content)}자)")
                        continue

                    seen_urls.add(url)
                    title = article.get("title") or ""
                    source_label = (article.get("source") or {}).get("name") or "알 수 없음"
                    # 2026-09-19: NewsAPI의 publishedAt은 실제로는 NewsAPI 자체의 크롤링/색인
                    # 시각을 반영하는 경우가 확인됨(NMPA 기사 사고 — 실제 게재일 2023-12-13인데
                    # published_at이 수집 당일로 잘못 저장됨). 페이지에서 직접 뽑은 page_date가
                    # 있으면 그걸 우선 쓰고, 없을 때만 NewsAPI가 준 값으로 폴백.
                    resolved_published_at = page_date or _parse_newsapi_date(article.get("publishedAt"))
                    if resolved_published_at is None:
                        # 2026-09-21 추가: page_date도 없고 NewsAPI의 publishedAt 파싱도 실패한
                        # 경우 — RSS 쪽과 동일하게 조용히 넘기지 않고 경고를 남김.
                        resolved_published_at = date.today()
                        print(
                            f"[news_collector] {url} — 게재일 추출 실패(meta/URL/NewsAPI 전부 실패), "
                            "수집일로 대체합니다."
                        )
                    results.append(
                        {
                            "title": title,
                            "content": content,
                            "url": url,
                            "author": article.get("author"),
                            "category": category,
                            "document_type": "news",
                            "published_at": resolved_published_at,
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
                    if not url or url in seen_urls or url in known_urls:
                        continue

                    try:
                        content, page_date = _extract_body(url)
                    except Exception as e:  # noqa: BLE001
                        print(f"[news_collector] {url} 수집 실패: {e}")
                        continue

                    if is_too_short(content):
                        print(f"[news_collector] {url} 본문이 너무 짧아 스킵 ({len(content)}자)")
                        continue

                    seen_urls.add(url)
                    title = _clean_naver_text(item.get("title", ""))
                    domain = urlparse(url).netloc.replace("www.", "")
                    # 2026-09-19: 페이지 자체 메타데이터에서 뽑은 page_date를 최우선으로 쓰고,
                    # 없을 때만 네이버 검색 API의 pubDate로 폴백 (NewsAPI 쪽과 동일한 정책).
                    resolved_published_at = page_date or _parse_naver_date(item.get("pubDate"))
                    if resolved_published_at is None:
                        # 2026-09-21 추가: 다른 두 경로와 동일하게 조용히 넘기지 않고 경고를 남김.
                        resolved_published_at = date.today()
                        print(
                            f"[news_collector] {url} — 게재일 추출 실패(meta/URL/네이버pubDate 전부 실패), "
                            "수집일로 대체합니다."
                        )
                    results.append(
                        {
                            "title": title,
                            "content": content,
                            "url": url,
                            "author": None,
                            "category": category,
                            "document_type": "news",
                            "published_at": resolved_published_at,
                            "language": "ko",
                            "source_name": f"네이버뉴스: {domain}",
                        }
                    )

                time.sleep(NAVER_NEWS_INTERVAL_SEC)

    return results


if __name__ == "__main__":
    docs = collect()
    print(f"{len(docs)}건 수집")
