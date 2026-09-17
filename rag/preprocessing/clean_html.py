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
#
# 2026-09-17 추가: "이전 기사보기 다음 기사보기" 같은 기사 내비게이션 링크, "[사진: 유디오
# 홈페이지] ◆" 같은 사진 캡션 줄도 같은 방식(정형화된 텍스트 패턴)으로 잡아서 제거.
#
# 2026-09-17 추가 2: "댓글 좋아요 슬퍼요 화나요 ... 폰트 1단계 13px ... 프린트 제보"처럼
# 댓글반응바/공유위젯/글자크기 조절 등 여러 UI 컴포넌트 텍스트가 사이트 마크업 구조상
# 줄바꿈 없이 한 줄에 통째로 붙어서 나오는 경우가 있음(예: 네이버 뉴스 계열). 이런 줄은
# "공유하기 카카오톡/페이스북/..." 처럼 어구가 고정돼 있지 않고 사이트마다 조합이 달라서
# 정규식 하나로는 못 잡음 — 대신 UI 위젯에서 흔히 쓰는 단어 사전을 만들어두고, 한 줄 안에서
# 그 사전에 속하는 토큰의 비율이 높으면(_looks_like_ui_widget_line) 잡음으로 판단.

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

# "이전 기사보기", "다음 기사보기"가 한 줄에 하나 또는 둘 다(순서 무관) 붙어 나오는 페이지
# 내비게이션 줄. 실제 기사 문장에서 이 정확한 어구가 이런 식으로 반복될 일은 없다고 보고
# 정형 패턴으로 처리.
_ARTICLE_NAV_RE = re.compile(
    r"^(?:이전\s*기사\s*보기|다음\s*기사\s*보기)"
    r"(?:\s+(?:이전\s*기사\s*보기|다음\s*기사\s*보기))*\s*$"
)

# "[사진: 유디오 홈페이지]"처럼 대괄호로 감싼 사진 출처/캡션 표기. 뒤에 "◆" 구분자와 짧은
# 크레딧(사진기자명 등)이 붙는 경우까지 포함. 대괄호 안 내용은 80자로 제한해서, 본문 중간에
# 우연히 대괄호가 쓰인 긴 인용구까지 잘못 지우는 걸 피함.
_PHOTO_CAPTION_RE = re.compile(
    r"^\[\s*사진\s*[:：]?\s*[^\[\]\n]{0,80}\]\s*(◆.{0,40})?$"
)

_BOILERPLATE_LINE_PATTERNS = [
    _BYLINE_EMAIL_RE,
    _DATE_BANNER_RE,
    _GOOGLE_PREFERRED_SOURCE_RE,
    _SHARE_WIDGET_RE,
    _SNS_SOLO_RE,
    _ARTICLE_NAV_RE,
    _PHOTO_CAPTION_RE,
]

_CATEGORY_TOKEN_RE = re.compile(r"^[가-힣A-Za-z0-9]{1,8}(/[가-힣A-Za-z0-9]{1,8})?$")


def _looks_like_menu_line(line: str) -> bool:
    """"생활/문화 건강정보 자동차/시승기 ..."처럼 슬래시 섞인 짧은 명사가 한 줄에 몰려있는
    카테고리 메뉴로 보이면 True. 토큰 6개 이상 + 전부 8자 이하 + 문장부호(마침표 등) 없음일
    때만 True로 판단 — 실제 문장을 오탐으로 지우는 걸 최대한 피하기 위한 보수적인 기준."""
    tokens = line.split()
    if len(tokens) < 6:
        return False
    if any(ch in line for ch in ".!?\"'“”「」"):
        return False
    return all(_CATEGORY_TOKEN_RE.match(tok) for tok in tokens)


# 댓글반응바(좋아요/슬퍼요/화나요/...), 공유위젯(페이스북/카카오톡/...), 글자크기 조절 UI,
# 프린트/제보 버튼처럼 기사 페이지에 흔히 붙는 UI 컴포넌트에서 쓰는 단어 사전. 실제 기사
# 문장에는 조사가 붙어서("페이스북과", "댓글이") 여기 있는 "정확한" 형태 그대로 나오는 경우가
# 드물기 때문에, 오탐 위험 없이 일치율만으로 판단 가능.
_UI_WIDGET_TOKENS = {
    "댓글", "좋아요", "싫어요", "슬퍼요", "화나요", "후속요청", "공감", "비공감",
    "최고예요", "응원해요", "북마크", "스크랩", "공유", "공유하기", "페이스북",
    "메신저", "트위터", "카카오톡", "네이버", "밴드", "닫기", "복사", "프린트",
    "제보", "폰트", "글자크기", "본문",
}
# "1단계"/"13px"처럼 글자크기 조절 위젯에 나오는 숫자+단위 토큰, "URL이"/"복사되었습니다."
# 같은 복사완료 토스트 메시지 조각.
_UI_WIDGET_TOKEN_PATTERN_RE = re.compile(r"^\d단계$|^\d+px$|^URL이?$|^복사(되었습니다|됨)\.?$")


def _looks_like_ui_widget_line(line: str) -> bool:
    """"음악 댓글 좋아요 슬퍼요 화나요 ... 폰트 1단계 13px ... 프린트 제보"처럼, 여러 UI
    컴포넌트 텍스트가 (사이트 마크업 구조상 줄바꿈 없이) 한 줄에 다 붙어서 나오는 경우를
    감지. _looks_like_menu_line과 달리 대상 어휘가 사이트마다 제각각이라 정규식 하나로
    못 잡으므로, 토큰 중 _UI_WIDGET_TOKENS/패턴에 해당하는 비율이 60% 이상(최소 3토큰)이면
    잡음으로 판단 — 일반 문장은 조사가 붙어 정확히 일치하는 토큰이 드물어 이 비율에 도달하기
    어려움."""
    tokens = line.split()
    if len(tokens) < 3:
        return False
    hits = sum(
        1
        for t in tokens
        if t in _UI_WIDGET_TOKENS or _UI_WIDGET_TOKEN_PATTERN_RE.match(t)
    )
    return hits / len(tokens) >= 0.6


def strip_boilerplate_lines(text: str) -> str:
    """기자 바이라인+이메일, "입력/수정" 날짜배너, "구글 검색 선호 출처로 추가", 공유하기
    위젯(카카오톡/페이스북/...), 기사 내비게이션("이전/다음 기사보기"), 사진 캡션("[사진: ...]"),
    댓글반응바/글자크기조절 등 UI 위젯 줄, 카테고리 메뉴 나열처럼 한국 언론사 CMS 대부분이
    공통으로 쓰는 정형화된 잡음 줄을 제거. strip_noise_tags()가 태그 기반이라 못 잡는,
    class/구조가 사이트마다 다른 잡음을 텍스트 패턴으로 보완하는 두 번째 방어선.
    collector들이 get_text()로 뽑은 직후, normalize_whitespace() 전후로 호출할 것."""
    kept = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if any(p.match(stripped) for p in _BOILERPLATE_LINE_PATTERNS):
            continue
        if _looks_like_menu_line(stripped) or _looks_like_ui_widget_line(stripped):
            continue
        kept.append(line)
    return "\n".join(kept)
