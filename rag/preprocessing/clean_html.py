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


# 2026-09-19 추가: livemint.com 등 일부 사이트는 본문 일부(기자 소개 문단 등)가 실제 <br> DOM
# 태그가 아니라 API/JSON 응답에 박혀있던 리터럴 "<br>" 문자열 그대로 내려와서, BeautifulSoup의
# 태그 파싱을 안 거치고 텍스트로 그대로 남는 경우가 확인됨 — strip_noise_tags()는 진짜 DOM
# 태그만 지우므로 이런 리터럴 문자열은 못 잡음. 정상 기사 본문에 "<br>" 문자열 자체가 그대로
# 쓰일 일은 없다고 보고 텍스트 레벨에서 공백으로 치환.
_LITERAL_BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)

# 2026-09-19 추가(감사 2차): 연합뉴스/톱스타뉴스/한국일보/KOTRA/국방일보 등 국내 언론사 다수가
# 기사 맨 끝에 "<저작권자(c) 연합뉴스, 무단 전재-재배포...>"/"<Copyright ⓒ 한국일보....>"
# 형태로 저작권 고지를 꺾쇠(<>)로 감싸서 붙임 — 실제 HTML 태그가 아니라 그 매체가 관습적으로
# 쓰는 표기라 strip_noise_tags()로는 못 잡고, 텍스트에 "<...>" 형태로 그대로 남음. 이 마커는
# 종종 앞뒤의 바이라인/관련기사 목록과 한 줄에 뒤섞여 있어서(문장부호 없이 끝나는 조각들이
# _reflow_fragmented_lines()에서 다음 줄과 이어붙기 때문) 줄 단위 필터로는 못 골라내서,
# normalize_whitespace()에서 리터럴 <br>과 같은 방식으로 텍스트 레벨에서 곧장 제거함 — 15개
# 이상의 서로 다른 매체에서 공통으로 관찰된 "<...Copyright/저작권.../무단전재...>" 패턴이라
# 매체별로 따로 등록하지 않고 하나의 일반 패턴으로 잡음.
_BRACKETED_COPYRIGHT_FOOTER_RE = re.compile(
    r"<[^<>]{0,80}(?:Copyright|저작권|무단\s?전재)[^<>]{0,120}>",
    re.IGNORECASE,
)


def normalize_whitespace(text: str) -> str:
    text = _LITERAL_BR_TAG_RE.sub(" ", text)
    text = _BRACKETED_COPYRIGHT_FOOTER_RE.sub(" ", text)
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
# 2026-09-17 추가: "이전 기사보기" 이전 기사보기" 같은 기사 볭님게이션 링크, "[사진: 유디오
# 홈페이짅]!◆" 같은 사진캡션 줄도 같은 방식(정형화된 텍스트 패턴)으로 잡아서 제거.
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

# 2026-09-17 추가 4: 정부/공공기관 게시판(한국저작권위원회 보도자료 상세페이지 등) 공통
# 필드 라벨. "제목"/"담당부서"/"등록일"/"첨부문서"/"미리보기" 처럼 라벨과 값이 줄바꿈으로만
# 구분돼 나오는 구조라, _strip_menu_runs()의 "8줄 이상 연속" 기준에 못 미치는 경우(예: 라벨이
# 실제 본문 사이사이 1~2줄씩만 끼어있는 경우)는 못 걸러짐 — 근래서 알려진 라벨 이름 자체를
# 정형 패턴으로 등록해서 한 줄 전체가 라벨 단어와 정확히 일치할 때만 제거(가운데 "담당부서"라는
# 단어가 실제 문장 일부로 나올 일은 거의 없다고 보고 SNS_SOLO_RE와 동일한 보수적 기준 적용).
# 라벨에 딸린 값(부서명/전화번호/날짜/파일명)은 문서 내용으로 남겨둠 — 근거자료로 쓸모가
# 있을 수 있어 라벨만 제거하고 값은 보존.
_BOARD_FIELD_LABEL_RE = re.compile(
    r"^(제목|담당부서|담당자|등록일|작성일|작성자|수정일|조회수|조회|"
    r"첨부문서|첨부파일|미리보기|다운로드|이전글|다음글|이전\s*글|다음\s*글|"
    r"목록|목록으로|인쇄|공유하기)\s*$"
)

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

# 2026-09-19 추가: 네이버뉴스로 연동된 일부 사이트(newsen.com 등)에서, 본문 앞에 "관련기사"
# 위젯이 자바스크립트로 나중에 채워지기 전 자리표시자였던 "Loading..." 문자열이 그대로
# 텍스트로 딸려 들어오는 경우가 실측 확인됨. 실제 기사 문장에 이 정확한 형태가 나올 일은 없음.
_LOADING_PLACEHOLDER_RE = re.compile(r"^Loading\.\.\.$")

# 2026-09-19 추가(감사 2차): inthenews.co.kr류 일부 사이트는 "한국어 English 中文 日本語
# ... news is the result of applying Google Translate. <매체명> is not responsible for the
# content of ... news." 형태의 자동번역 안내/면책 문구를 기사에 끼워 넣음 — 실제 기사 내용과
# 무관한 사이트 UI 문구. 매체명 부분은 사이트마다 달라서 그 앞의 고정 문구만으로 잡음.
_TRANSLATION_DISCLAIMER_RE = re.compile(r"^.{0,60}is the result of applying Google Translate\.")

_BOILERPLATE_LINE_PATTERNS = [
    _BYLINE_EMAIL_RE,
    _DATE_BANNER_RE,
    _GOOGLE_PREFERRED_SOURCE_RE,
    _SHARE_WIDGET_RE,
    _SNS_SOLO_RE,
    _ARTICLE_NAV_RE,
    _PHOTO_CAPTION_RE,
    _BOARD_FIELD_LABEL_RE,
    _LOADING_PLACEHOLDER_RE,
    _TRANSLATION_DISCLAIMER_RE,
]

# 2026-09-19 추가: "Loading..." 뒤에 따라오는 "관련기사/인기기사" 사이드바 위젯 항목들은
# 대부분 "이름, 자극적인 문구…" 형태의 연예 가십 헤드라인이라 하트 기호(♥)가 유독 자주
# 섞여 나옴(실측: newsen.com). 이 프로젝트 주제(생성형 AI·음악저작권) 기사 본문에 ♥ 기호가
# 정상적으로 쓰일 일은 사실상 없다고 보고, 이 기호가 포함된 줄은 위젯 잡음으로 간주해 제거.
# (같은 위젯의 ♥ 없는 줄까지 전부 잡진 못하지만, 나머지는 각 문서 재수집 시 개별 확인.)
_HEART_SYMBOL = "♥"

# 2026-09-19 추가: "최신 기사"/"주간 인기 기사"/"많이 본 뉴스" 같은 사이트 하단 관련기사·인기
# 기사 위젯은, 마커 줄 하나만 지워서는 안 되고 그 뒤로 쭉 이어지는 기사 제목 목록+댓글창+
# 등록번호 푸터까지 전부 잡음(실측: gamechosun.co.kr — 기사 본문이 끝난 뒤 "최신 기사" ->
# 기사 제목 6개 -> "주간 인기 기사" -> 기사 제목 6개 -> 댓글위젯 -> "많이 본 뉴스" -> 순위
# 목록 -> 인터뷰 위젯 -> "인터넷 신문 등록 번호" 푸터까지 쭉 이어짐). 이런 목록 항목은 실제
# 기사 제목이라 문장부호(따옴표/말줄임표 등)가 섞여 있어서 _strip_menu_runs()의 "짧고 문장
# 부호 없는 줄 연속" 기준에는 안 걸림 — 그래서 별도로, 이 마커들 중 하나가 줄 전체와 정확히
# 일치하면 그 줄부터 문서 끝까지 통째로 잘라내는 방식으로 처리(마커 자체가 본문 문장으로
# 우연히 등장할 가능성은 낮다고 보고 채택).
_FOOTER_WIDGET_MARKERS = ("최신 기사", "주간 인기 기사", "많이 본 뉴스", "인터넷 신문 등록 번호")


def _truncate_at_footer_widgets(text: str) -> str:
    # startswith 기준 — "인터넷 신문 등록 번호"류는 같은 줄에 등록번호/발행인 등이 이어붙어
    # 나와서(예: "인터넷 신문 등록 번호 : 서울 아00014 등록일 : ...") 완전일치로는 못 잡음.
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if any(stripped == marker or stripped.startswith(marker) for marker in _FOOTER_WIDGET_MARKERS):
            return "\n".join(lines[:i])
    return text

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


# ---------------------------------------------------------------------
# 2026-09-17 추가 3: 여러 줄에 걸쳐 "한 줄에 항목 하나씩" 나열되는 메뉴/내비게이션 블록 제거
# ---------------------------------------------------------------------
# 지금까지의 _looks_like_menu_line/_looks_like_ui_widget_line은 "한 줄 안에" 짧은 명사가
# 여러 개 뭉쳐있는 경우만 잡는데, YTN처럼 메뉴 항목이 한 줄에 하나씩 쭉 나열되는 사이트
# (예: "정치\n경제\n사회\n전국\n...", "YTN 사이언스\nYTN 라디오\n..." 처럼 브랜드/채널명까지
# 섞여 나옴)는 줄 하나만 보면 그냥 평범한 단어라 기존 필터로는 못 걸러짐. 이런 메뉴는
# 사이트 브랜드명(YTN 사이언스, INSIDE YTN, 남산서울타워 등)까지 섞여 있어서 단어 사전으로
# 다 못 외우므로, 대신 "짧고 문장부호 없는 줄이 일정 개수 이상 연속으로 나온다"는 구조적
# 신호로 감지 — 실제 기사 본문은 보통 문장 단위(마침표 등)라 이런 긴 스트릭이 잘 안 나옴.
_MENU_RUN_MIN_LINES = 8       # 이 이상 연속되면 메뉴 블록으로 간주(오탐 방지를 위해 보수적으로)
_MENU_CANDIDATE_MAX_LEN = 20  # 이보다 길면 메뉴 항목이라기보단 실제 문장일 가능성이 높음


def _is_menu_candidate_line(stripped: str) -> bool:
    """짧고 문장부호가 없는 줄 — 메뉴 항목 스트릭의 구성원 후보. 이 함수 하나만으로는 지우지
    않고, _strip_menu_runs()에서 연속 개수를 보고 최종 판단함(단독으로는 오탐 위험이 큼 —
    예: 실제 기사의 짧은 인용구 한 줄)."""
    if not stripped or len(stripped) > _MENU_CANDIDATE_MAX_LEN:
        return False
    if any(ch in stripped for ch in ".!?\"'“”「」,"):
        return False
    return True


def _strip_menu_runs(lines: list[str]) -> list[str]:
    """_is_menu_candidate_line()이 참인 줄이 _MENU_RUN_MIN_LINES개 이상 연속되면(빈 줄은
    스트릭을 끊지 않고 건너뜀) 그 구간 전체(빈 줄 포함)를 제거. strip_boilerplate_lines()가
    한 줄씩 보는 필터들을 다 적용해서 명백한 잡음 줄을 먼저 걷어낸 뒤, 남은 줄들에 대해
    마지막으로 이 함수로 다중 줄 구조를 한 번 더 훑음."""
    n = len(lines)
    keep = [True] * n
    i = 0
    while i < n:
        stripped_i = lines[i].strip()
        if stripped_i and not _is_menu_candidate_line(stripped_i):
            i += 1
            continue
        j = i
        candidate_count = 0
        while j < n:
            s = lines[j].strip()
            if not s:
                j += 1
                continue
            if not _is_menu_candidate_line(s):
                break
            candidate_count += 1
            j += 1
        if candidate_count >= _MENU_RUN_MIN_LINES:
            for k in range(i, j):
                keep[k] = False
        i = j if j > i else i + 1
    return [line for line, k in zip(lines, keep) if k]


# ---------------------------------------------------------------------
# 2026-09-17 추가 5: 인라인 태그(<a>/<span>/<b> 등) 경계에서 문장이 여러 줄로 쪼개지는
# 문제 복구 (영어 policy/official 문서에서 발견 — 한국어 기사와 달리 이쪽은 "잡음 줄
# 추가"가 아니라 "정상 문장이 조각남"이 문제였음)
# ---------------------------------------------------------------------
# collector들의 _fetch_page()가 soup.get_text(separator="\n", strip=True)로 본문을 뽑는데,
# 이 separator는 <p>/<div> 같은 블록 태그뿐 아니라 문장 중간의 <a>/<span> 같은 인라인 태그
# 경계에도 그대로 삽입됨. WIPO 페이지 실제 수집 결과에서 한 문장이 "WIPO held the / First
# Session of the WIPO Conversation on IP and AI / in September 2019..." 처럼 3줄로 쪼개져
# 나오는 게 확인됨(링크가 문장 중간에 박혀있는 구조). 문장부호로 안 끝나는 줄은 다음 줄과
# 이어붙여서 원래 문장으로 복구 — collector별 _fetch_page()를 다 손보는 대신 공용
# strip_boilerplate_lines()에서 한 번에 처리.
_PIPE_SEPARATOR_LINE_RE = re.compile(r"^[|•·»▶>\-–—]+$")
_SENTENCE_END_RE = re.compile(r'[.!?:;"\'”’)\]』」]\s*$')
_REFLOW_MAX_BUFFER_CHARS = 400  # 문장부호가 계속 안 나오는 이상 페이지에서 무한정 이어붙이는 걸 막는 안전장치


def _reflow_fragmented_lines(text: str) -> str:
    """문장부호로 끝나지 않는 줄은 다음 줄과 공백으로 이어붙여 원래 문장을 복구.
    "|"/"•" 등 구분자만 있는 줄(네비게이션 링크 사이 구분자로 흔함)은 문단 경계로 보고
    빈 줄로 치환 — 그 앞뒤 내용이 서로 이어붙지 않게 막는 역할. 빈 줄(원래부터 있던 문단
    구분)도 마찬가지로 이어붙이기를 끊음. strip_boilerplate_lines()의 다른 필터들보다
    반드시 나중에(맨 마지막에) 실행해야 함 — 잡음 줄(게시판 라벨/메뉴 항목)이 아직 살아있는
    상태에서 먼저 돌리면 그 잡음이 다음 줄(진짜 본문)에 붙어버려서 한 줄 단위 필터와
    _strip_menu_runs()의 "짧은 줄 연속" 구조 판정을 둘 다 무력화시킴(실측 재현됨)."""
    normalized = [
        "" if _PIPE_SEPARATOR_LINE_RE.match(line.strip()) else line
        for line in text.split("\n")
    ]

    out: list[str] = []
    buffer = ""
    for raw in normalized:
        stripped = raw.strip()
        if not stripped:
            if buffer:
                out.append(buffer)
                buffer = ""
            out.append("")
            continue
        buffer = f"{buffer} {stripped}" if buffer else stripped
        if _SENTENCE_END_RE.search(buffer) or len(buffer) >= _REFLOW_MAX_BUFFER_CHARS:
            out.append(buffer)
            buffer = ""
    if buffer:
        out.append(buffer)
    return "\n".join(out)


def strip_boilerplate_lines(text: str) -> str:
    """기자 바이라인+이메일, "입력/수정" 날짜배너, "구글 검색 선호 출처로 추가", 공유하기
    위젯(카카오톡/페이스북/...), 기사 내비게이션("이전/다음 기사보기"), 사진 캡션("[사진: ...]"),
    댓글반응바/글자크기조절 등 UI 위젯 줄, 카테고리 메뉴 나열처럼 한국 언론사 CMS 대부분이
    공통으로 쓰는 정형화된 잡음 줄을 제거. strip_noise_tags()가 태그 기반이라 못 잡는,
    class/구조가 사이트마다 다른 잡음을 텍스트 패턴으로 보완하는 두 번째 방어선.
    collector들이 get_text()로 뽑은 직후, normalize_whitespace() 전후로 호출할 것.

    2026-09-17: 한 줄씩 보는 필터(정규식/토큰비율)를 다 적용한 뒤, 마지막으로
    _strip_menu_runs()로 "짧은 줄이 길게 연속되는" 구조적 잡음(YTN처럼 메뉴 항목이 한 줄에
    하나씩 나열되는 경우)까지 한 번 더 걸러냄.

    2026-09-17 추가: 맨 마지막에 _reflow_fragmented_lines()로 인라인 태그 때문에 쪼개진
    문장을 복구함(WIPO 등 영어 policy 페이지에서 확인). 주의 — reflow를 맨 앞에서 하면
    안 됨: 게시판 라벨("제목"/"담당부서" 등)이나 메뉴 항목처럼 문장부호 없이 끝나는 잡음
    줄들이 아직 살아있는 상태에서 reflow부터 돌리면, 그 잡음 줄들이 바로 다음 줄(실제 값/
    본문)에 통째로 붙어버려서 한 줄 단위 필터(_BOARD_FIELD_LABEL_RE 등)와 구조적 필터
    (_strip_menu_runs — "짧은 줄 8개 이상 연속" 판정도 병합되면서 깨짐)가 둘 다 무력화됨.
    실제로 한국저작권위원회 샘플로 이 순서 버그가 재현됨 — 대메뉴 블록 전체와 "제목"/
    "담당부서" 라벨이 안 지워지고 본문에 섞여 들어감. 그래서 순서를 "줄 단위 필터 →
    구조적 메뉴런 필터 → reflow"로 고정: 잡음이 아직 낱줄로 살아있을 때 먼저 걷어내고,
    남은 진짜 문장만 마지막에 이어붙임.

    2026-09-19 추가: 맨 처음에 _truncate_at_footer_widgets()로 "최신 기사"/"주간 인기 기사"
    등 하단 관련기사 위젯 마커부터 문서 끝까지를 통째로 잘라냄(gamechosun.co.kr 등에서 확인
    — 위젯 항목이 문장부호 섞인 "짧지 않은" 제목이라 _strip_menu_runs()로는 못 잡히므로 별도
    처리). 다른 필터보다 먼저 해야 위젯 안의 항목들이 이후 필터에 걸려 오탐을 낼 여지도 같이
    없앨 수 있음."""
    text = _truncate_at_footer_widgets(text)
    kept = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if _HEART_SYMBOL in stripped:
            # 연예 가십 사이드바 위젯 항목 의심 줄(위 _HEART_SYMBOL 설명 참고) — 통째로 제거.
            continue
        if any(p.match(stripped) for p in _BOILERPLATE_LINE_PATTERNS):
            continue
        if _looks_like_menu_line(stripped) or _looks_like_ui_widget_line(stripped):
            continue
        kept.append(line)
    kept = _strip_menu_runs(kept)
    return _reflow_fragmented_lines("\n".join(kept))
