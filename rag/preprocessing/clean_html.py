"""
HTML 제거 / 본문만 추출 / 너무 짧은 문서 걸러내기.
collectors/*.py가 이미 어느 정도 본문을 뽑아오지만, 광고/메뉴/스크립트 잔여물을 한 번 더 정리하는 용도.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

MIN_CONTENT_LENGTH = 200  # 이보다 짧으면 근거로 쓰기엔 정보가 부족하다고 보고 버림

_NOISE_TAGS = ["script", "style", "nav", "header", "footer", "aside", "form", "iframe"]


def strip_html(raw_html: str) -> str:
    """HTML 태그 제거 + 광고/메뉴로 추정되는 태그 제거."""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return normalize_whitespace(text)


def normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_too_short(content: str) -> bool:
    return len(content) < MIN_CONTENT_LENGTH
