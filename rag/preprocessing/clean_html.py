"""
HTML 노이즈(광고/메뉴/스크립트) 제거 / 공백 정리 / 너무 짧은 문서 걸러내기.

collector/news_collector.py, official_collector.py, policy_collector.py가 페이지를 가져올 때
이 모듈의 strip_noise_tags()/normalize_whitespace()/is_too_short()를 가져다 씀 — 전에는 각
collector가 BeautifulSoup으로 각자 본문만 대충 추출하고 이 모듈은 어디서도 호출되지 않던 상태였는데,
이번에 실제로 연결함.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

MIN_CONTENT_LENGTH = 200  # 이보다 짧으면 근거로 쓰기엔 정보가 부족하다고 보고 버림

_NOISE_TAGS = ["script", "style", "nav", "header", "footer", "aside", "form", "iframe"]


def strip_noise_tags(soup: BeautifulSoup) -> None:
    """광고/메뉴/스크립트로 추정되는 태그를 soup에서 제자리 제거(in-place).
    collector들이 soup 만든 직후, .find("article") 등으로 본문 범위를 좁히기 전에 호출할 것."""
    for tag in soup(_NOISE_TAGS):
        tag.decompose()


def normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_too_short(content: str) -> bool:
    return len(content) < MIN_CONTENT_LENGTH


def strip_html(raw_html: str) -> str:
    """HTML 문자열 전체 -> 노이즈 제거 + 정리된 텍스트. 본문 범위를 따로 좁힐 필요 없을 때 사용."""
    soup = BeautifulSoup(raw_html, "html.parser")
    strip_noise_tags(soup)
    return normalize_whitespace(soup.get_text(separator="\n"))


# ---------------------------------------------------------------------
# 2026-09-16 추가: 텍스트 패턴 기반 보일러플레이트 제거
# ---------------------------------------------------------------------
# strip_noise_tags()는 <nav>/<header>/<footer> 등 "태그 이름"으로만 걸러내는데, 실제로는
# 카테고리 메뉴/바이라인/공유 위젯 같은 잡음이 <article> 태그 안쪽에 class="xxx" div/ul로
# 박혀있는 사이트가 많아서(예: 데일리안) 그 방식으로는 못 걸러짐. 대신 한국 언론사 CMS
# 대부분이 공통으로 쓰는 정형화된 줄(기자 바이라인+이메일, "입력/수정" 날짜배너, "구글 검색
# 선호 출처로 추가", "공유하기 카카오톡/페이스북/..." 위젯, 슬래시 섞인 카테고리 메뉴 나열)을
# 텍스트 패턴으로 잡아서 제거.

_BYLINE_EMAIL_RE = re.compile(
    r"^.{0,20}(기자|특파원|인턴기자)\s*\([^()\n]{0,60}@[^()\n]{0,60}\)\s*$"
)
_DATE_BANNER_RE = re.compile(
    r"^입력\s*\d{4}[.\-]\d{2}[.\-]\d{2}\.?\s*\d{1,2}:\d{2}"
    r"(\s*수정\s*\d{4}[.\-]\d{2}[.\-]\d{2}\.?\s*\d{1,2}:\d{2})?\s*$"
)
_GOOGLE_PREFERRED_SOURCE_RE = re.compile(r"^구글\s*검색\s*선호\s*출처로\s*추가.*$")
_SHARE_WIDGET_RE = re.compile(
    r"^공유하기\b.*(카카오톡|페이스북|트위터|블로그|URL\s*복사|주소\s*복사).*$"
)
_SNS_SOLO_RE = re.compile(r"^(카카오톡|페이스북|트위터|블로그|URL\s*복사|주소\s*복사|X)$")

_BOILERPLATE_LINE_PATTERNS = [
    _BYLINE_EMAIL_RE,
    _DATE_BANNER_RE,
    _GOOGLE_PREFERRED_SOURCE_RE,
    _SHARE_WIDGET_RE,
    _SNS_SOLO_RE,
]

_CATEGORY_TOKEN_RE = re.compile(r"^[가-힣A-Za-z0-9]{1,8}(/[가-힣A-Za-z0-9]{1,8})?$")


def _looks_like_menu_line(line: str) -> bool:
    """"생활/문화 건강정보 자동차/시승기 ..."처럼 슬래시 섞인 짧은 명사가 한 줄에 몰려있는
    카테고리 메뉴로 보이면 True. 토큰 6개 이상 + 전부 8자 이하 + 문장부호(마침표 등) 없음일
    때만 True로 판단 — 실제 문장을 오탐으로 지우는 걸 최대한 피하기 위한 보수적인 기준."""
    tokens = line.split()
    if len(tokens) < 6:
        return False
    if any(ch in line for ch in ".!?\"'\u201c\u201d\u300c\u300d"):
        return False
    return all(_CATEGORY_TOKEN_RE.match(tok) for tok in tokens)


def strip_boilerplate_lines(text: str) -> str:
    """기자 바이라인+이메일, "입력/수정" 날짜배너, "구글 검색 선호 출처로 추가", 공유하기
    위젯(카카오톡/페이스북/...), 카테고리 메뉴 나열처럼 한국 언론사 CMS 대부분이 공통으로
    쓰는 정형화된 잡음 줄을 제거. strip_noise_tags()가 태그 기반이라 못 잡는, class/구조가
    사이트마다 다른 잡음을 텍스트 패턴으로 보완하는 두 번째 방어선.
    collector들이 get_text()로 뽑은 직후, normalize_whitespace() 전후로 호출할 것."""
    kept = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if any(p.match(stripped) for p in _BOILERPLATE_LINE_PATTERNS):
            continue
        if _looks_like_menu_line(stripped):
            continue
        kept.append(line)
    return "\n".join(kept)
