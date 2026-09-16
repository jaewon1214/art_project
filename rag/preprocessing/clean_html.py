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
