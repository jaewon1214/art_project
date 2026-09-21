"""
논문 데이터 수집기 — arXiv API + Semantic Scholar API (둘 다 API 키 불필요, 무료).

news_collector.py와 같은 규약: collect() -> list[dict] (documents 컬럼과 1:1 대응).
content는 논문 원문 전체가 아니라 초록(abstract)임 — 전체 PDF 본문까지 수집하려면
scripts/ingest_pdfs.py로 PDF를 직접 내려받아 data/<category>/ 에 넣는 방식을 병행할 것.

[arXiv]
공식 문서: https://info.arxiv.org/help/api/user-manual.html
- 키 불필요. 단, 공식 권장 사항으로 요청 사이 최소 3초 간격을 둠(과호출 시 차단될 수 있음).
- 응답이 Atom XML이라 RSS와 동일하게 feedparser로 파싱 가능(추가 의존성 없음).
⚠️ 참고: 이 API는 export.arxiv.org 도메인이라 일부 네트워크 환경(예: 샌드박스형 격리 VM)의
egress allowlist에 없으면 막힐 수 있음. 일반 PC/서버 환경에서는 문제없이 접속됨.

[Semantic Scholar]
공식 문서: https://api.semanticscholar.org/api-docs/
- 키 없이도 사용 가능(무료, 요청 제한은 공유 풀이라 빡빡함 — 요청 사이 최소 1초 간격을 둠).
  나중에 트래픽 늘리려면 https://www.semanticscholar.org/product/api 에서 무료 API 키 신청 가능
  (발급되면 .env에 SEMANTIC_SCHOLAR_API_KEY로 넣고 헤더에 실어서 rate limit 완화).
- arXiv에 없는 저널/학회 논문까지 커버하고 인용수(citationCount)도 같이 줌.
- arXiv랑 겹치는 논문은 externalIds.ArXiv 값으로 걸러서 중복 저장 방지.

[OpenAlex] (2026-09-16 추가)
공식 문서: https://docs.openalex.org/
- 키 불필요, 완전 무료. 예전 Microsoft Academic Graph를 이어받은 오픈 학술 그래프로,
  arXiv/Semantic Scholar 둘 다 안 잡는 저널·학회 논문까지 커버 범위가 훨씬 넓음. Semantic
  Scholar가 공유 풀이라 429(rate limit)로 쿼리가 통째로 날아가는 일이 잦았던 것과 달리,
  OpenAlex는 기본 풀(초당 10회)만으로도 이 프로젝트 요청량(8쿼리 x 최대 2페이지)엔 충분히
  여유로움 — Semantic Scholar가 막히는 날의 보완재 역할도 함.
- .env에 OPENALEX_MAILTO=<이메일>을 넣으면 "polite pool"로 승격돼 더 넉넉한 한도를 받음
  (선택사항 — 없어도 기본 풀로 정상 동작).
- abstract는 원문이 아니라 abstract_inverted_index(단어->위치 인덱스) 형태로 옴 —
  _reconstruct_abstract()로 원래 문장 순서로 복원해서 씀. 이 필드가 아예 없는(초록 비공개)
  논문은 content가 없어서 스킵.
- DOI가 "10.48550/arXiv.XXXX" 형태면 arXiv 프리프린트를 OpenAlex가 다시 색인한 것 —
  seen_arxiv_ids로 걸러서 중복 저장 방지(Semantic Scholar와 동일한 패턴).

[OpenAlex 한국 논문] (2026-09-17 추가)
- KCI Open API는 인증키 발급이 수동 심사라 오늘 바로 못 씀(신청은 해둔 상태, 승인 대기 중).
  그 사이 공백을 메우려고, 이미 연결돼 있던 OpenAlex에 filter=language:ko를 추가해서
  "한국어로 작성된" 논문만 별도로 검색하는 패스를 만듦 — 키/승인 필요 없이 오늘 바로 동작.
  단, OpenAlex는 Crossref/DOI 기반 색인이라 DOI 없는 국내 학회지(특히 KCI 전용 등재지)는
  안 잡힐 수 있음 — 커버리지가 KCI보다 좁을 걸로 예상되지만, 승인 기다리는 동안의 임시
  보완재로는 충분함. KCI 승인되면 그쪽이 주력, 이건 계속 병행(중복은 겹치는 DOI가 거의
  없어서 사실상 안 남).
- 쿼리는 SEMANTIC_SCHOLAR_QUERIES와 같은 카테고리/의미를 한국어 키워드로 옮긴 것.
- 이 패스로 수집된 문서는 language="ko"로 태그 — ingest.py가 document_type=="paper"인
  문서는 애초에 번역을 안 시키므로(원문 그대로 저장) 동작에 영향 없고, 메타데이터만
  정확해짐(나중에 language 기준으로 필터링/집계할 때 필요).

[KCI OAI-PMH] (2026-09-17 추가, 한국어 논문 커버리지 탐색 결과)
한국어 논문 소스를 최대한 찾아본 결과:
- KCI REST Open API(articleSearch, title 키워드 검색 지원 — 위 [OpenAlex 한국 논문] 항목에
  적은 그 API): 승인 수동 심사라 아직 대기 중. 승인되면 이 파일에 REST 기반 검색 패스를
  추가해서 이 OAI-PMH 패스와 병행/대체할 것(REST가 키워드 검색이 가능해서 더 정밀함).
- DBpia/RISS: 둘 다 유료 구독 기반이거나 공개 검색 API를 제공하지 않음 — 제외.
- KCI가 REST와 별개로 제공하는 OAI-PMH(Open Archives Initiative 표준 메타데이터 수확
  프로토콜) 엔드포인트는 **인증키 없이 즉시 사용 가능**함을 2026-09-17 실제 호출로 확인함
  (verb=Identify/ListSets/ListRecords 직접 테스트 — 정상 응답, KCI 저장소 확인됨).
  다만 REST와 달리 제목/키워드로 "검색"하는 게 아니라 set(자료유형: ARTI=일반논문/
  ARTI_CONF=학회논문/JOUR=학술지 — 주제별 구분은 없음) + 날짜범위(datestamp=등록·수정일
  기준, 발행일 아님) 기준의 "대량 수확"만 지원함. 그래서 이 모듈은:
    1. set=ARTI, 최근 KCI_OAI_LOOKBACK_DAYS일치 datestamp를 통째로 수확
    2. dc:language가 "한국어"인 것만 남김(이 필드가 실제로 채워져 나오는 것까지 라이브로
       확인함 — 예: 중국어/영어 논문도 섞여 나와서 이 필터가 꼭 필요함)
    3. 제목+초록에 _KCI_KEYWORD_RE(음악/AI/저작권 등 최소 키워드)가 하나도 없으면 LLM
       호출(비용) 없이 바로 스킵 — arXiv RSS 패스(위 [arXiv] 항목)와 동일한 이유/패턴.
  이렇게 하면 REST API 키 승인을 기다리지 않고 바로 한국어 논문 수집이 가능함. 단점:
  KCI 전체(모든 학문분야) 중 최근 등록분만 훑는 방식이라, REST의 정밀 키워드 검색보다
  주제 적중률은 낮음(그래서 로컬 키워드 필터로 최대한 걸러냄) — 승인 나면 REST로 이관.
  ⚠️ 이 OAI-PMH 파싱 코드는 KCI가 공개한 문서(OAI-PMH 2.0 표준 + oai_dc 포맷)와 실제 라이브
  호출로 직접 검증한 응답 구조를 기준으로 작성했지만, 이 프로젝트 네트워크 환경(Cowork VM/
  샌드박스)에서 open.kci.go.kr 자체가 막혀있어(egress allowlist) 로컬에서 실행 테스트는
  못 해봄 — 서버 DB 접속 가능한 실제 PC에서 처음 실행할 때 결과(수집 건수/에러)를 꼭 확인할 것.

[KCI REST] (2026-09-21 추가 — 키워드검색 인증키 승인 완료 후 실제 연동)
articleSearch API(제목 키워드 정밀검색)를 사용하는 `_fetch_kci_rest()`를 추가하고 collect()의
새 단계(6/7)로 연결함. OPENALEX_KOREAN_QUERIES(이미 카테고리별로 다듬어둔 한국어 검색어)를
title 파라미터로 그대로 재사용 — 쿼리 세트를 따로 관리할 필요가 없게 함. 요청/응답 스펙(파라미터
전체 목록, record 하나당 필드 경로 등)은 KCI_REST_BASE 바로 위 주석에 정리해둠.
⚠️ OAI-PMH와 마찬가지로 이 파싱 코드도 이 네트워크 환경에서 open.kci.go.kr이 막혀있어 라이브
응답으로 직접 실행 테스트는 못 함(공개된 파라미터/응답 구조 문서 기준으로만 작성) — 실제 PC에서
처음 실행할 때 수집 건수·에러 로그를 꼭 확인할 것. 문제가 있으면(필드 경로가 실제 응답과
다르다거나) `_kci_rest_record_to_row()`만 손보면 되고, OAI-PMH 경로는 그대로 병행 동작하니
REST 쪽이 당장 안 되더라도 전체 수집이 막히지는 않음(collect()가 각 소스를 독립적으로
try/except 처리).
"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.parse import quote

import feedparser  # pip install feedparser
import requests  # pip install requests
from dotenv import load_dotenv  # pip install python-dotenv

# news_collector.py/case_collector.py와 동일한 이유로 직접 로드 — 이 모듈은 database.config를
# 안 거치는 독립 모듈이라 .env가 자동으로는 안 읽힘.
load_dotenv()

ARXIV_API = "http://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_API = "https://api.openalex.org/works"
OPENALEX_MAILTO = os.environ.get("OPENALEX_MAILTO", "").strip()  # 선택 — 있으면 polite pool로 승격

# 2026-09-16: "최신 데이터 위주로 수집" 전략 — 오래된 논문이 검색 결과 상위를 차지해서
# 최신 논문이 덜 잡히는 문제를 줄이기 위해 연도 필터를 추가. arXiv/Semantic Scholar 둘 다
# 이 연도 '이후' 논문만 수집(과거 논문을 아예 안 모으는 게 아니라, 최신 쪽으로 비중을 옮기는 것).
# 필요하면 팀 논의로 조정할 것.
PAPER_YEAR_FROM = 2023

# 2026-09-16: arXiv RSS 피드 추가 — 검색 API(쿼리+연도필터)는 "그 시점까지 쌓인 것 중 검색"이라
# 매번 똑같은 과거 논문이 잡힐 수 있는데, RSS는 그 카테고리에 "그날 새로 올라온" 논문만 나옴.
# 검색어 필터가 없어서 카테고리 전체가 다 오니까(대부분 무관한 오디오처리 논문), LLM 관련성판정
# 호출 비용을 아끼려고 최소한의 키워드로 1차 거름.
ARXIV_RSS_BASE = "https://rss.arxiv.org/rss"
ARXIV_RSS_CATEGORIES = ["cs.SD", "eess.AS"]
_RSS_KEYWORD_RE = re.compile(
    r"music|song|singing|singer|compos|melody|lyric|"
    r"voice clon|voice conversion|speaker anonymiz|synthetic voice|"
    r"copyright|generative music",
    re.IGNORECASE,
)

# 주제(생성형 AI와 음악 창작)의 4개 하위쟁점별 검색 쿼리.
# abs: = 초록(abstract) 안에서 검색. 필요하면 팀 논의로 쿼리 문구를 더 좁히거나 넓힐 것.
# 카테고리당 쿼리 1개 -> 2개(기존 좁은 쿼리 + 더 넓은 변형)로 늘려서 수집 폭을 넓힘.
# 카테고리 값 자체(저작권/창작자성/음성복제/AI작곡)는 DB category 컬럼 제약과 맞춰야 해서 안 바꿈 —
# 대신 각 카테고리 안에서 검색어만 넓혀서 더 많은 관련 논문을 잡아내는 방향.
QUERIES: dict[str, list[str]] = {
    "저작권": [
        'abs:"music generation" AND abs:copyright',
        'abs:"generative music" AND (abs:copyright OR abs:"intellectual property" OR abs:licensing)',
    ],
    "창작자성": [
        'abs:"AI music" AND (abs:authorship OR abs:"co-creation" OR abs:"computational creativity")',
        '(abs:"human-AI collaboration" OR abs:"AI-assisted composition") AND abs:music',
        # 2026-09-19 추가: 창작자성 카테고리 보강 요청 — "저작권/저작자성" 자체를 정면으로
        # 다루는 논문(음악에 국한되지 않는 일반 AI-저작권 authorship 논의도 포함)까지 넓힘.
        '(abs:"human authorship" OR abs:"authorship requirement") AND (abs:copyright OR abs:"generative AI")',
    ],
    "음성복제": [
        'abs:"voice cloning" OR abs:"voice conversion" OR abs:"singing voice synthesis"',
        'abs:"voice conversion" AND (abs:singer OR abs:speaker OR abs:identity)',
    ],
    "AI작곡": [
        '(abs:"music composition" OR abs:"symbolic music generation" OR abs:"text-to-music") AND (abs:neural OR abs:transformer OR abs:generative)',
        'abs:"music generation" AND (abs:diffusion OR abs:"language model")',
    ],
}

# Semantic Scholar는 arXiv 같은 필드 검색(abs:) 문법을 지원하지 않아서 일반 키워드로 따로 둠.
SEMANTIC_SCHOLAR_QUERIES: dict[str, list[str]] = {
    "저작권": [
        "music generation copyright",
        "generative music intellectual property licensing",
    ],
    "창작자성": [
        "AI music authorship computational creativity",
        "human-AI collaboration music composition",
        "generative AI copyright authorship human creativity",
    ],
    "음성복제": [
        "voice cloning singing voice synthesis",
        "voice conversion singer identity",
    ],
    "AI작곡": [
        "text-to-music generation transformer",
        "music generation diffusion language model",
    ],
}

# 2026-09-17 추가: OpenAlex 한국어 논문(language=ko) 전용 패스에 쓰는 쿼리 — 위
# SEMANTIC_SCHOLAR_QUERIES와 같은 카테고리/의도를 한국어 키워드로 옮긴 것. 모듈 docstring
# [OpenAlex 한국 논문] 항목 참고.
OPENALEX_KOREAN_QUERIES: dict[str, list[str]] = {
    "저작권": [
        "생성형 AI 음악 저작권",
        "AI 음악 학습데이터 저작권 라이선스",
    ],
    "창작자성": [
        "AI 음악 창작 저작자성",
        "인간과 AI 공동창작 음악",
        "AI 저작물 인간 창작 기여도 판단",
    ],
    "음성복제": [
        "AI 보이스 클로닝 음성권",
        "목소리 무단 학습 음성복제",
    ],
    "AI작곡": [
        "텍스트 기반 AI 작곡",
        "생성형 AI 작곡 서비스",
    ],
}

# 보수적으로 조정 — 처음엔 200/300까지 잡았다가, rate limit 리스크/비용 안전마진을 위해
# 한 단계 낮춤. 그래도 원래(30/20)보다는 넉넉해서 수집량은 여전히 늘어남.
MAX_RESULTS_PER_QUERY = 100  # 200 -> 100
REQUEST_INTERVAL_SEC = 3  # arXiv 공식 권장 최소 간격

SEMANTIC_SCHOLAR_MAX_RESULTS = 100  # API가 한 번에 주는 최대치(페이지당) — 이건 그대로 둠
SEMANTIC_SCHOLAR_MAX_PAGES = 2  # 3 -> 2 (쿼리당 최대 200건), 무료 풀 rate limit 부담 줄임
SEMANTIC_SCHOLAR_INTERVAL_SEC = 4  # 3 -> 4, 안전마진 더 둠
SEMANTIC_SCHOLAR_MAX_RETRIES = 3
SEMANTIC_SCHOLAR_RETRY_BACKOFF_SEC = 5  # 429 맞으면 5, 10, 20초... 늘려가며 재시도

OPENALEX_MAX_RESULTS = 100  # per-page 최대치
OPENALEX_MAX_PAGES = 2  # 쿼리당 최대 200건 — Semantic Scholar와 동일한 상한
OPENALEX_INTERVAL_SEC = 1  # 기본 풀 기준(초당 10회)으로도 충분히 여유있는 간격

# 2026-09-17 추가: KCI(한국학술지인용색인) OAI-PMH — 모듈 docstring [KCI OAI-PMH] 참고.
KCI_OAI_BASE = "https://open.kci.go.kr/oai/request"

# 2026-09-21: KCI REST API(키워드검색) 인증키 승인 완료 + 연동 함수 구현 완료. .env에
# KCI_API_KEY가 있으면 collect()의 KCI REST 단계가 OPENALEX_KOREAN_QUERIES를 title 키워드로
# 써서 실제 검색을 돌림(카테고리당 정밀 키워드 검색 — 아래 [KCI REST] 항목 참고). 키가 없으면
# 이 단계는 조용히 스킵되고 OAI-PMH(무인증) 경로만 그대로 동작 — 기존 동작과 100% 호환.
KCI_API_KEY = os.environ.get("KCI_API_KEY", "").strip()

# [KCI REST] (2026-09-21 추가) — 키워드검색(articleSearch). OAI-PMH가 "최근 등록분을 통째로
# 훑고 로컬 키워드로 거르는" 방식인 것과 반대로, 여기는 title 파라미터로 정밀 검색이 가능해서
# 검색 폭은 좁지만(제목에 매치되는 것만) 후보 품질이 높음(=ingest.py LLM 호출 낭비가 적음).
# 요청 파라미터: key(필수)/apiCode=articleSearch(필수)/title(필수, 검색어)/author/journal/
# doi/institution/affiliation/keyword/abstract/dateFrom·dateTo(YYYYMM)/page/displayCount(최대
# 100)/sortNm/sortDir. 응답은 XML, 루트 MetaData > outputData > record 반복 —
# record/journalInfo(journal-name/pub-year/pub-mon 등), record/articleInfo(title-group/
# article-title[lang=original|english], author-group/author, abstract-group/
# abstract[lang=original|english], doi, url, article-id 속성). articleSearch는 keyword를
# 검색 필터로는 받지만 결과에 키워드 자체는 안 실어줌 — 우리는 abstract만 쓰므로 무관.
KCI_REST_BASE = "https://open.kci.go.kr/po/openapi/openApiSearch.kci"
KCI_REST_DISPLAY_COUNT = 100  # 페이지당 최대치(API 상한)
KCI_REST_MAX_PAGES = 3  # 쿼리당 최대 300건 안전 상한(OAI-PMH만큼 넓게 훑을 필요 없음 — 정밀검색이라)
KCI_REST_INTERVAL_SEC = 2  # OAI-PMH와 동일하게 공식 rate limit 문서가 없어 보수적으로
KCI_OAI_SET = "ARTI"  # 일반논문(학회논문/학술지 자체 메타는 별도 set — 우선 일반논문만)
# 2026-09-19: "한국논문 더 많아야되는데" 요청으로 7 -> 180(6개월)로 확장. 원래 7일은 "매번
# 조금씩 꾸준히" 쌓는 용도였는데, 그 방식으로는 KCI REST API(키워드검색) 승인 전까지 volume이
# 너무 안 늘어남. 180일치를 한 번 크게 수확해서 그동안 쌓인 백로그를 메우는 쪽으로 바꿈.
# 주의: SET=ARTI가 모든 학문분야를 다 포함해서(주제 필터가 API 레벨엔 없음) 기간을 넓히면
# _KCI_KEYWORD_RE를 통과하는 후보 자체가 늘어나고, 그만큼 ingest.py의 LLM 관련성판정 호출도
# 늘어남(=시간/비용 증가) — 한 번 크게 돌려보고 너무 오래 걸리면 이 값을 낮춰서 나눠 돌릴 것.
# 재실행해도 이미 있는 문서는 dedupe로 스킵되니 겹치는 기간을 다시 돌려도 안전함.
KCI_OAI_LOOKBACK_DAYS = 180  # datestamp(등록/수정일) 기준 최근 며칠치를 매 실행마다 수확할지
KCI_OAI_MAX_PAGES = 80  # resumptionToken 페이지네이션 안전 상한(무한루프 방지) — 기간 늘어난 만큼 같이 올림
KCI_OAI_INTERVAL_SEC = 2  # 공식 rate limit 문서가 없어서 arXiv 권장치(3초)에 준하는 보수적 간격

_OAI_DC_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}

# 제목+초록에 이 중 하나도 없으면 LLM 호출(비용) 없이 바로 스킵 — arXiv RSS 패스와 동일한
# "최소 키워드 1차 거름 -> ingest.py의 LLM 관련성판정이 최종 판단" 패턴.
_KCI_KEYWORD_RE = re.compile(
    r"인공지능|AI|생성형|딥러닝|머신러닝|음악|작곡|음원|음성|보이스|목소리|"
    r"저작권|저작자|창작|딥페이크|생성 AI",
    re.IGNORECASE,
)


def _fetch_query(query: str) -> list:
    # PAPER_YEAR_FROM 이후로 제출된 논문만 — arXiv 날짜 범위 문법은 YYYYMMDDHHMMSS 14자리.
    date_filter = f"submittedDate:[{PAPER_YEAR_FROM}0101000000 TO 99991231235959]"
    full_query = f"({query}) AND {date_filter}"
    url = (
        f"{ARXIV_API}?search_query={quote(full_query)}"
        f"&start=0&max_results={MAX_RESULTS_PER_QUERY}"
        f"&sortBy=submittedDate&sortOrder=descending"
    )
    parsed = feedparser.parse(url)
    return parsed.entries


def _fetch_arxiv_rss(feed_category: str) -> list:
    """카테고리 전체의 "오늘/최근 새로 제출된" 논문 목록 — 검색어 없이 그대로 옴."""
    url = f"{ARXIV_RSS_BASE}/{feed_category}"
    parsed = feedparser.parse(url)
    return parsed.entries


def _fetch_semantic_scholar(query: str, offset: int = 0) -> list[dict]:
    """429(rate limit) 맞으면 지수 백오프로 재시도 — 예전엔 재시도 없이 바로 포기해서
    무료 공유 풀이 바쁠 때(=거의 항상) 쿼리 4개 중 다수가 통째로 날아갔었음."""
    last_error: Exception | None = None
    for attempt in range(SEMANTIC_SCHOLAR_MAX_RETRIES):
        try:
            resp = requests.get(
                SEMANTIC_SCHOLAR_API,
                params={
                    "query": query,
                    "offset": offset,
                    "limit": SEMANTIC_SCHOLAR_MAX_RESULTS,
                    "fields": "title,abstract,authors,year,publicationDate,externalIds,url",
                    # "2023-" 형태 = PAPER_YEAR_FROM 연도부터 최신까지. 이 엔드포인트는 sort
                    # 파라미터는 안 되지만(정렬은 /paper/search/bulk 전용) year 필터는 지원됨.
                    "year": f"{PAPER_YEAR_FROM}-",
                },
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", SEMANTIC_SCHOLAR_RETRY_BACKOFF_SEC * (attempt + 1)))
                print(f"[paper_collector] Semantic Scholar 429 — {wait}초 대기 후 재시도 ({attempt + 1}/{SEMANTIC_SCHOLAR_MAX_RETRIES})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json().get("data", [])
        except requests.exceptions.RequestException as e:
            last_error = e
            time.sleep(SEMANTIC_SCHOLAR_RETRY_BACKOFF_SEC)
    raise last_error or RuntimeError("Semantic Scholar 요청 반복 실패")


def _fetch_semantic_scholar_paginated(query: str) -> list[dict]:
    """SEMANTIC_SCHOLAR_MAX_PAGES까지 offset 페이지네이션 — 한 페이지가 MAX_RESULTS보다
    적게 오면(더 이상 결과 없음) 거기서 멈춤."""
    all_papers: list[dict] = []
    for page in range(SEMANTIC_SCHOLAR_MAX_PAGES):
        offset = page * SEMANTIC_SCHOLAR_MAX_RESULTS
        papers = _fetch_semantic_scholar(query, offset=offset)
        all_papers.extend(papers)
        if len(papers) < SEMANTIC_SCHOLAR_MAX_RESULTS:
            break
        if page < SEMANTIC_SCHOLAR_MAX_PAGES - 1:
            time.sleep(SEMANTIC_SCHOLAR_INTERVAL_SEC)
    return all_papers


def _fetch_openalex(query: str, page: int, language: str | None = None) -> list[dict]:
    """language를 주면(예: "ko") OpenAlex의 language 필터를 같이 걸어서 그 언어로 작성된
    논문만 받음 — 2026-09-17 KCI 승인 대기 중 임시 대체용으로 추가 (모듈 docstring
    [OpenAlex 한국 논문] 참고). 필터는 콤마로 이어붙이면 AND 조건이 됨."""
    filters = [f"from_publication_date:{PAPER_YEAR_FROM}-01-01"]
    if language:
        filters.append(f"language:{language}")
    params = {
        "search": query,
        "filter": ",".join(filters),
        "sort": "publication_date:desc",
        "per-page": OPENALEX_MAX_RESULTS,
        "page": page,
    }
    if OPENALEX_MAILTO:
        params["mailto"] = OPENALEX_MAILTO  # polite pool 승격용(선택)
    resp = requests.get(OPENALEX_API, params=params, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.json().get("results", [])


def _fetch_openalex_paginated(query: str, language: str | None = None) -> list[dict]:
    """OPENALEX_MAX_PAGES까지 page 파라미터로 페이지네이션 — Semantic Scholar와 동일한 패턴."""
    all_works: list[dict] = []
    for page in range(1, OPENALEX_MAX_PAGES + 1):
        works = _fetch_openalex(query, page, language=language)
        all_works.extend(works)
        if len(works) < OPENALEX_MAX_RESULTS:
            break
        if page < OPENALEX_MAX_PAGES:
            time.sleep(OPENALEX_INTERVAL_SEC)
    return all_works


def _kci_oai_request(params: dict) -> ET.Element:
    """OAI-PMH는 인증키가 없어서 requests.get()에 params만 실어 보내면 됨. 응답은 XML —
    ET.fromstring()으로 바로 파싱(추가 의존성 없이 표준 라이브러리만 사용)."""
    resp = requests.get(KCI_OAI_BASE, params=params, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return ET.fromstring(resp.content)


def _kci_oai_check_error(root: ET.Element) -> str | None:
    """OAI-PMH는 결과가 없어도 HTTP 200을 주고 <error code="noRecordsMatch">로 알림 —
    이건 에러가 아니라 "그 날짜엔 없음"이라 조용히 빈 리스트로 처리해야 함. 그 외 에러
    코드(badArgument 등)는 진짜 문제라 메시지를 반환해서 호출부가 로그를 남기게 함."""
    error = root.find("oai:error", _OAI_DC_NS)
    if error is None:
        return None
    code = error.get("code", "")
    if code == "noRecordsMatch":
        return None  # 결과 없음 — 정상 케이스
    return f"{code}: {(error.text or '').strip()}"


def _kci_dc_text(dc_el: ET.Element, tag: str, lang: str | None = None) -> str:
    """<dc:{tag} lang="...">를 찾아서 텍스트 반환. lang을 주면 그 lang 우선(없으면 아무거나
    첫 번째), 여러 개(title/description처럼 lang별로 여러 번 나오는 필드) 중 하나 고를 때 씀."""
    candidates = dc_el.findall(f"dc:{tag}", _OAI_DC_NS)
    if not candidates:
        return ""
    if lang:
        for c in candidates:
            if c.get("lang") == lang and (c.text or "").strip():
                return c.text.strip()
    for c in candidates:
        if (c.text or "").strip():
            return c.text.strip()
    return ""


def _kci_dc_identifier(dc_el: ET.Element, id_type: str) -> str:
    """<dc:identifier type="...">는 artiId/doi/journalInfo/citedCnt 등 여러 종류가 type
    속성으로만 구분돼서 나옴 — type으로 찾아서 텍스트 반환."""
    for el in dc_el.findall("dc:identifier", _OAI_DC_NS):
        if el.get("type") == id_type and (el.text or "").strip():
            return el.text.strip()
    return ""


def _kci_parse_date(dc_date: str) -> date:
    """dc:date는 "YYYY-MM" 형태(일자 없음) — 월의 1일로 맞춰서 date 객체로 변환.
    형식이 안 맞으면(예상 밖 값) 오늘 날짜로 폴백."""
    m = re.match(r"^(\d{4})-(\d{2})", dc_date or "")
    if not m:
        return date.today()
    try:
        return date(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return date.today()


def _kci_record_to_row(record: ET.Element) -> dict | None:
    """OAI-PMH <record> 1건 -> collect() 결과 row. 한국어가 아니거나, 초록이 없거나,
    주제 키워드가 하나도 없으면 None(스킵)."""
    header = record.find("oai:header", _OAI_DC_NS)
    if header is not None and header.get("status") == "deleted":
        return None  # 삭제된 레코드(OAI-PMH 표준: status="deleted") — 내용 없음

    dc = record.find(".//oai_dc:dc", _OAI_DC_NS)
    if dc is None:
        return None

    language = _kci_dc_text(dc, "language")
    if language != "한국어":
        return None  # 이 패스는 한국어 논문 전용 — 다른 언어는 OpenAlex 등 다른 패스가 커버

    title = _kci_dc_text(dc, "title", lang="original")
    abstract = _kci_dc_text(dc, "description", lang="original")
    if not title or not abstract:
        return None  # content 필수 — 초록 없는 논문은 스킵

    if not _KCI_KEYWORD_RE.search(f"{title} {abstract}"):
        return None  # 주제 키워드조차 없으면 LLM 호출(비용) 없이 바로 스킵

    # 2026-09-17 수정: dc:url은 OAI_DC 표준에 없는 태그라 _kci_dc_text로는 항상 빈 값이었음
    # (오프라인 합성 XML 테스트로 발견) -- 실제 URL은 dc:identifier type="url"로 들어옴.
    # 이 버그 상태로는 DOI 없는 국내 학회지 논문(흔함)이 전부 url="" 처리돼 스킵됐을 것.
    url = _kci_dc_identifier(dc, "url") or _kci_dc_identifier(dc, "doi")
    if not url:
        return None  # url은 documents 테이블 필수 컬럼 겸 dedup 기준

    return {
        "title": title,
        "content": abstract,
        "url": url,
        "author": _kci_dc_text(dc, "creator") or None,
        "category": "AI작곡",  # 1차 힌트일 뿐 — arXiv RSS 패스와 동일하게 LLM 관련성판정이 덮어씀
        "document_type": "paper",
        "published_at": _kci_parse_date(_kci_dc_text(dc, "date")),
        "language": "ko",
        "source_name": "KCI",
    }


def _kci_rest_request(params: dict) -> ET.Element:
    """REST는 OAI-PMH와 달리 인증키가 필요 — params에 key를 포함해서 보냄. 응답은 XML."""
    resp = requests.get(KCI_REST_BASE, params=params, timeout=30)
    resp.raise_for_status()
    return ET.fromstring(resp.content)


def _kci_rest_check_error(root: ET.Element) -> str | None:
    """키 미승인/파라미터 오류 등은 error 또는 resultMsg 태그로 옴(정식 스펙 문서에 명시된
    코드 목록이 없어 텍스트가 있으면 일단 에러로 취급 — test_kci_key.py와 동일한 판정 방식)."""
    for tag in ("error", "resultMsg"):
        el = root.find(f".//{tag}")
        if el is not None and (el.text or "").strip():
            return el.text.strip()
    return None


def _kci_rest_pick_lang_text(parent: ET.Element | None, child_tag: str) -> str:
    """title-group/article-title, abstract-group/abstract처럼 lang="original"/"english"로
    여러 번 나오는 필드에서 original 우선(없으면 아무거나 첫 값) 텍스트를 뽑음."""
    if parent is None:
        return ""
    candidates = parent.findall(child_tag)
    if not candidates:
        return ""
    for c in candidates:
        if c.get("lang") == "original" and (c.text or "").strip():
            return c.text.strip()
    for c in candidates:
        if (c.text or "").strip():
            return c.text.strip()
    return ""


def _kci_rest_parse_date(pub_year: str, pub_mon: str) -> date:
    """journalInfo/pub-year(YYYY) + pub-mon(MM) -> date. pub-mon이 없거나 범위를 벗어나면
    1월로 폴백, pub-year 자체가 없으면(예상 밖 응답) 오늘 날짜로 폴백."""
    try:
        year = int((pub_year or "").strip())
    except ValueError:
        return date.today()
    try:
        mon = int((pub_mon or "").strip())
        if not 1 <= mon <= 12:
            mon = 1
    except ValueError:
        mon = 1
    try:
        return date(year, mon, 1)
    except ValueError:
        return date.today()


def _kci_rest_record_to_row(record: ET.Element, category: str) -> dict | None:
    """REST <record> 1건 -> collect() 결과 row. 제목/초록/URL 중 하나라도 없으면 None(스킵) —
    구조는 [KCI REST] 모듈 상단 주석 참고."""
    article = record.find("articleInfo")
    if article is None:
        return None

    title = _kci_rest_pick_lang_text(article.find("title-group"), "article-title")
    if not title:
        return None

    abstract = _kci_rest_pick_lang_text(article.find("abstract-group"), "abstract")
    if not abstract:
        return None  # content 필수 — 초록 없는 논문은 스킵(OAI-PMH 경로와 동일한 정책)

    doi = (article.findtext("doi") or "").strip()
    url = (article.findtext("url") or "").strip() or (f"https://doi.org/{doi}" if doi else "")
    if not url:
        article_id = article.get("article-id") or ""
        if article_id:
            url = (
                "https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci"
                f"?sereArticleSearchBean.artiId={article_id}"
            )
    if not url:
        return None  # url은 documents 테이블 필수 컬럼 겸 dedup 기준

    author_group = article.find("author-group")
    authors = None
    if author_group is not None:
        names = [(a.text or "").strip() for a in author_group.findall("author") if (a.text or "").strip()]
        authors = ", ".join(names) or None

    journal = record.find("journalInfo")
    journal_name = (journal.findtext("journal-name") or "").strip() if journal is not None else ""
    pub_year = (journal.findtext("pub-year") or "") if journal is not None else ""
    pub_mon = (journal.findtext("pub-mon") or "") if journal is not None else ""

    return {
        "title": title,
        "content": abstract,
        "url": url,
        "author": authors,
        "category": category,  # 검색 쿼리 자체가 카테고리별이라 OAI-PMH보다 신뢰도 높은 1차 힌트
        "document_type": "paper",
        "published_at": _kci_rest_parse_date(pub_year, pub_mon),
        "language": "ko",
        "source_name": journal_name or "KCI",
    }


def _fetch_kci_rest(query: str, category: str) -> list[dict]:
    """title=query로 키워드 검색, displayCount만큼씩 페이지네이션. KCI_API_KEY 없으면 호출부에서
    아예 안 부름(collect() 참고)."""
    rows: list[dict] = []
    for page in range(1, KCI_REST_MAX_PAGES + 1):
        params = {
            "apiCode": "articleSearch",
            "key": KCI_API_KEY,
            "title": query,
            "page": page,
            "displayCount": KCI_REST_DISPLAY_COUNT,
        }
        try:
            root = _kci_rest_request(params)
        except Exception as e:  # noqa: BLE001 — 이 쿼리만 실패, 나머지 쿼리는 계속 진행
            print(f"[paper_collector] KCI REST '{query}' {page}페이지 요청 실패: {e}")
            break

        error = _kci_rest_check_error(root)
        if error:
            print(f"[paper_collector] KCI REST '{query}' 에러: {error}")
            break

        records = root.findall(".//outputData/record")
        if not records:
            break

        for record in records:
            row = _kci_rest_record_to_row(record, category)
            if row:
                rows.append(row)

        total_el = root.find(".//result/total")
        total_text = (total_el.text or "").strip() if total_el is not None else ""
        total = int(total_text) if total_text.isdigit() else None
        if total is not None and page * KCI_REST_DISPLAY_COUNT >= total:
            break  # 이미 전체를 다 받았으면 더 돌 필요 없음
        if page < KCI_REST_MAX_PAGES:
            time.sleep(KCI_REST_INTERVAL_SEC)

    return rows


def _fetch_kci_oai() -> list[dict]:
    """set=ARTI, 최근 KCI_OAI_LOOKBACK_DAYS일치를 resumptionToken으로 페이지네이션하며 수확.
    자세한 배경은 모듈 docstring [KCI OAI-PMH] 참고."""
    until = date.today()
    since = until - timedelta(days=KCI_OAI_LOOKBACK_DAYS)
    params: dict = {
        "verb": "ListRecords",
        "metadataPrefix": "oai_dc",
        "set": KCI_OAI_SET,
        "from": since.isoformat(),
        "until": until.isoformat(),
    }

    rows: list[dict] = []
    print(
        f"[paper_collector] KCI OAI-PMH 수확 시작 "
        f"(최근 {KCI_OAI_LOOKBACK_DAYS}일, 최대 {KCI_OAI_MAX_PAGES}페이지 — "
        f"응답이 느릴 수 있으니 중간에 출력 없어도 Ctrl+C 하지 말 것)"
    )
    for page in range(KCI_OAI_MAX_PAGES):
        root = _kci_oai_request(params)
        print(f"[paper_collector] KCI OAI page {page + 1}/{KCI_OAI_MAX_PAGES} 응답 수신 (누적 {len(rows)}건)")

        error = _kci_oai_check_error(root)
        if error:
            print(f"[paper_collector] KCI OAI-PMH 에러: {error}")
            break

        records = root.findall(".//oai:record", _OAI_DC_NS)
        for record in records:
            row = _kci_record_to_row(record)
            if row:
                rows.append(row)

        token_el = root.find(".//oai:resumptionToken", _OAI_DC_NS)
        token = (token_el.text or "").strip() if token_el is not None else ""
        if not token:
            break  # 더 이상 페이지 없음

        params = {"verb": "ListRecords", "resumptionToken": token}  # 재요청 시 이 두 파라미터만 허용(OAI-PMH 표준)
        if page < KCI_OAI_MAX_PAGES - 1:
            time.sleep(KCI_OAI_INTERVAL_SEC)

    print(f"[paper_collector] KCI OAI-PMH 수확 종료 — 총 {len(rows)}건 (로컬 키워드 필터링 전)")
    return rows


def _arxiv_short_id(raw_id: str) -> str:
    """arXiv entry id('http://arxiv.org/abs/2309.01234v1')에서 순수 ID('2309.01234')만 뽑음.
    Semantic Scholar의 externalIds.ArXiv 값과 비교해서 중복을 걸러내는 데 씀."""
    tail = raw_id.rstrip("/").rsplit("/", 1)[-1]
    return tail.split("v")[0] if "v" in tail else tail


_ARXIV_ID_YYMM_RE = re.compile(r"^(\d{2})(\d{2})\.\d{4,5}")


def _arxiv_id_month_date(raw_id_or_url: str) -> date | None:
    """arXiv 새 형식 ID(YYMM.NNNNN)에서 연-월만 뽑아 그 달 1일로 반환.
    2026-09-21 추가: arXiv RSS 응답에 published_parsed/updated_parsed가 둘 다 없는 경우가
    실측으로 확인됨(예: cs.SD/eess.AS 피드 다수 — 실제 게재월(예: 2026-01)이 수집일(예:
    2026-09)로 통째로 잘못 저장되던 사고로 발견). news_collector.py의 URL 날짜 폴백과 같은
    발상 — 피드가 주는 날짜 필드를 못 믿을 때, 정확한 일자는 몰라도 ID 자체에 항상 박혀있는
    연-월만이라도 건지는 최후의 폴백. day=1로 고정하는 건 부정확하지만(정확한 일자는 알 수
    없음), 몇 달씩 틀린 수집일보다는 훨씬 낫다는 판단 — KCI 경로(_kci_parse_date 등)가 이미
    쓰는 것과 같은 "연-월만 있으면 1일로" 패턴."""
    short_id = _arxiv_short_id(raw_id_or_url)
    m = _ARXIV_ID_YYMM_RE.match(short_id)
    if not m:
        return None
    yy, mm = int(m.group(1)), int(m.group(2))
    if not (1 <= mm <= 12):
        return None
    try:
        return date(2000 + yy, mm, 1)
    except ValueError:
        return None


_OPENALEX_ARXIV_DOI_RE = re.compile(r"48550/arxiv\.([a-z0-9.]+)", re.IGNORECASE)


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """OpenAlex는 저작권 문제로 초록 원문을 안 주고 abstract_inverted_index(단어 -> 등장 위치
    리스트)만 줌 — 위치 기준으로 정렬해서 원래 문장으로 복원. 이 필드가 없으면(초록 비공개
    논문) 빈 문자열 반환 — 호출부에서 content 없는 항목으로 스킵됨."""
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for idx in idxs:
            positions.append((idx, word))
    positions.sort(key=lambda p: p[0])
    return " ".join(word for _, word in positions)


def _openalex_arxiv_id(doi: str | None) -> str | None:
    """OpenAlex work의 doi가 "https://doi.org/10.48550/arXiv.2309.01234" 형태면 arXiv
    프리프린트를 다시 색인한 것 — seen_arxiv_ids와 비교할 순수 arXiv ID만 뽑아서 반환."""
    if not doi:
        return None
    m = _OPENALEX_ARXIV_DOI_RE.search(doi)
    return m.group(1) if m else None


def _openalex_work_to_row(work: dict, category: str, seen_arxiv_ids: set[str], language: str) -> dict | None:
    """OpenAlex work 1건 -> collect() 결과 row. 초록 없음/arXiv 중복이면 None.
    영어 패스와 한국어 패스(language=ko) 둘 다 이 함수를 공유 — 2026-09-17 한국어 패스 추가
    하면서 중복 로직을 안 늘리려고 뽑아냄."""
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
    if not abstract:
        return None  # 초록 비공개 항목은 스킵 (content 필수)

    arxiv_id = _openalex_arxiv_id(work.get("doi"))
    if arxiv_id and arxiv_id in seen_arxiv_ids:
        return None  # arXiv에서 이미 수집한 프리프린트와 중복

    published_at = None
    pub_date = work.get("publication_date")
    if pub_date:
        try:
            published_at = datetime.strptime(pub_date, "%Y-%m-%d").date()
        except ValueError:
            pass
    if published_at is None and work.get("publication_year"):
        # publication_date가 없고 publication_year만 있으면 그 해 1월 1일로(일자는 모름) —
        # 실측상 OpenAlex는 둘 중 하나는 거의 항상 줌(same-day-as-수집일 0/213으로 확인됨).
        published_at = date(int(work["publication_year"]), 1, 1)
    if published_at is None:
        # 2026-09-21 추가: 위 두 필드가 다 없는 극히 드문 경우도 arXiv/뉴스와 동일하게 조용히
        # 넘기지 않고 경고 로그를 남김 — 지금까지는 발생 안 했지만 재발 시 바로 알아채려는 목적.
        published_at = date.today()
        print(
            f"[paper_collector] OpenAlex work {work.get('id') or work.get('doi')} — "
            "게재일 정보 없음(publication_date/publication_year 둘 다 없음), 수집일로 대체합니다."
        )

    authors = (
        ", ".join(
            (a.get("author") or {}).get("display_name", "")
            for a in work.get("authorships", [])
        ).strip(", ")
        or None
    )

    url = work.get("doi") or work.get("id") or ""

    return {
        "title": (work.get("title") or work.get("display_name") or "").strip(),
        "content": abstract,
        "url": url,
        "author": authors,
        "category": category,
        "document_type": "paper",
        "published_at": published_at,
        "language": language,
        "source_name": "OpenAlex",
    }


def collect() -> list[dict]:
    results: list[dict] = []
    seen_arxiv_ids: set[str] = set()

    # ---------------- arXiv ----------------
    print("[paper_collector] 1/7 arXiv 검색 시작")
    for category, queries in QUERIES.items():
        for query in queries:
            try:
                entries = _fetch_query(query)
            except Exception as e:  # noqa: BLE001 — 한 쿼리 실패해도 나머지는 계속 진행
                print(f"[paper_collector] arXiv '{category}' 쿼리 실패: {e}")
                continue

            for entry in entries:
                arxiv_id = entry.get("id", "")
                if not arxiv_id or arxiv_id in seen_arxiv_ids:
                    continue
                seen_arxiv_ids.add(arxiv_id)
                seen_arxiv_ids.add(_arxiv_short_id(arxiv_id))

                published_at = None
                if entry.get("published"):
                    try:
                        published_at = datetime.strptime(entry.published[:10], "%Y-%m-%d").date()
                    except ValueError:
                        pass
                if published_at is None:
                    # 2026-09-21 추가: 검색 API는 지금까지 실측상 entry.published가 항상 있었지만
                    # (RSS 경로와 달리), 혹시 없는 경우에도 조용히 수집일로 떨어지지 않도록 RSS
                    # 경로와 동일한 방어선(ID 연-월 폴백 + 경고 로그)을 여기도 맞춰둠.
                    published_at = _arxiv_id_month_date(arxiv_id)
                if published_at is None:
                    published_at = date.today()
                    print(
                        f"[paper_collector] {arxiv_id} — 게재일 추출 실패(entry.published/ID 전부 실패), "
                        "수집일로 대체합니다."
                    )

                authors = ", ".join(a.get("name", "") for a in entry.get("authors", [])) or None

                results.append(
                    {
                        "title": entry.get("title", "").replace("\n", " ").strip(),
                        "content": entry.get("summary", "").replace("\n", " ").strip(),
                        "url": arxiv_id,
                        "author": authors,
                        "category": category,
                        "document_type": "paper",
                        "published_at": published_at,
                        "language": "en",
                        "source_name": "arXiv",
                    }
                )

            time.sleep(REQUEST_INTERVAL_SEC)

    # ---------------- arXiv RSS (검색어 없이, 카테고리 전체 최신 논문) ----------------
    print(f"[paper_collector] 2/7 arXiv RSS 시작 (누적 {len(results)}건)")
    for feed_category in ARXIV_RSS_CATEGORIES:
        try:
            entries = _fetch_arxiv_rss(feed_category)
        except Exception as e:  # noqa: BLE001
            print(f"[paper_collector] arXiv RSS '{feed_category}' 조회 실패: {e}")
            continue

        for entry in entries:
            link = entry.get("link", "")
            if not link:
                continue
            short_id = _arxiv_short_id(link)
            if short_id in seen_arxiv_ids:
                continue

            title = entry.get("title", "").replace("\n", " ").strip()
            abstract = entry.get("summary", "").replace("\n", " ").strip()
            # description이 "arXiv:2609.12432v1 Announce Type: new  Abstract: ..." 형태라
            # 실제 초록만 남김(패턴이 안 맞으면 원문 그대로 둠 — 손실보다 원문 보존이 낫다).
            if "Abstract:" in abstract:
                abstract = abstract.split("Abstract:", 1)[-1].strip()

            if not _RSS_KEYWORD_RE.search(f"{title} {abstract}"):
                continue  # 주제 키워드조차 없으면 LLM 호출(비용) 없이 바로 스킵

            seen_arxiv_ids.add(short_id)

            # 2026-09-21 수정: arXiv RSS(cs.SD/eess.AS) 응답에서 published_parsed가 실측상
            # 거의 항상 비어있는 것으로 확인됨 — 조용히 date.today()로 떨어져서 실제 게재월이
            # 몇 달씩 틀린 채로 저장되던 사고 발견(예: 2026-01 게재 논문이 2026-09 수집일로
            # 저장됨). news_collector.py의 RSS 폴백 수정과 동일한 순서로: published_parsed ->
            # updated_parsed(혹시 있을 Atom 스타일 필드) -> arXiv ID의 연-월(_arxiv_id_month_date,
            # 일자는 모르지만 최소한 연-월은 정확) -> 그래도 없으면 수집일 + 경고 로그.
            published_at = None
            for date_field in ("published_parsed", "updated_parsed"):
                parsed_time = entry.get(date_field)
                if parsed_time:
                    try:
                        published_at = date(*parsed_time[:3])
                        break
                    except (TypeError, ValueError):
                        continue
            if published_at is None:
                published_at = _arxiv_id_month_date(short_id)
            if published_at is None:
                published_at = date.today()
                print(
                    f"[paper_collector] {link} — 게재일 추출 실패(published_parsed/updated_parsed/ID 전부 실패), "
                    "수집일로 대체합니다."
                )

            authors = entry.get("author") or None

            results.append(
                {
                    "title": title,
                    "content": abstract,
                    "url": link,
                    "author": authors,
                    "category": "AI작곡",  # 1차 힌트 — LLM 관련성판정이 실제 내용 기준으로 덮어씀
                    "document_type": "paper",
                    "published_at": published_at,
                    "language": "en",
                    "source_name": "arXiv",
                }
            )

        time.sleep(REQUEST_INTERVAL_SEC)

    # ---------------- Semantic Scholar ----------------
    # 2026-09-19: 연속으로 계속 429가 나면(공유 풀 자체가 이번 세션 내내 막혀있는 상황일
    # 가능성이 높음) 남은 쿼리를 전부 재시도해봐야 몇 분만 더 날리고 결과는 똑같을 확률이
    # 높아서, 연속 실패 N회 넘어가면 이번 실행은 Semantic Scholar를 통째로 건너뜀
    # (다음 실행 때 다시 시도하면 됨 — 여기서 스킵해도 arXiv/OpenAlex/KCI는 그대로 진행).
    print(f"[paper_collector] 3/7 Semantic Scholar 시작 (누적 {len(results)}건)")
    SEMANTIC_SCHOLAR_CIRCUIT_BREAKER = 3
    consecutive_failures = 0
    for category, queries in SEMANTIC_SCHOLAR_QUERIES.items():
        if consecutive_failures >= SEMANTIC_SCHOLAR_CIRCUIT_BREAKER:
            break
        for query in queries:
            if consecutive_failures >= SEMANTIC_SCHOLAR_CIRCUIT_BREAKER:
                print(
                    f"[paper_collector] Semantic Scholar {consecutive_failures}연속 실패 — "
                    "이번 실행은 건너뜀 (다음 실행에서 재시도)"
                )
                break
            try:
                papers = _fetch_semantic_scholar_paginated(query)
                consecutive_failures = 0
            except Exception as e:  # noqa: BLE001
                consecutive_failures += 1
                print(f"[paper_collector] Semantic Scholar '{category}' 쿼리 실패: {e}")
                continue

            for paper in papers:
                abstract = (paper.get("abstract") or "").strip()
                if not abstract:
                    continue  # 초록 없는 항목은 스킵 (content 필수)

                arxiv_ref = (paper.get("externalIds") or {}).get("ArXiv")
                if arxiv_ref and arxiv_ref in seen_arxiv_ids:
                    continue  # arXiv에서 이미 수집한 논문과 중복

                published_at = date.today()
                pub_date = paper.get("publicationDate")
                if pub_date:
                    try:
                        published_at = datetime.strptime(pub_date, "%Y-%m-%d").date()
                    except ValueError:
                        pass
                elif paper.get("year"):
                    published_at = date(int(paper["year"]), 1, 1)

                authors = ", ".join(a.get("name", "") for a in paper.get("authors", [])) or None

                results.append(
                    {
                        "title": (paper.get("title") or "").strip(),
                        "content": abstract,
                        "url": paper.get("url") or f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}",
                        "author": authors,
                        "category": category,
                        "document_type": "paper",
                        "published_at": published_at,
                        "language": "en",
                        "source_name": "Semantic Scholar",
                    }
                )

            time.sleep(SEMANTIC_SCHOLAR_INTERVAL_SEC)

    # ---------------- OpenAlex (영어/기본) ----------------
    print(f"[paper_collector] 4/7 OpenAlex(EN) 시작 (누적 {len(results)}건)")
    # 쿼리 세트는 Semantic Scholar와 동일하게 재사용 — 둘 다 필드검색 문법(arXiv의 abs: 같은)
    # 없이 일반 키워드로 검색하는 API라 같은 쿼리 문구를 그대로 쓸 수 있음.
    for category, queries in SEMANTIC_SCHOLAR_QUERIES.items():
        for query in queries:
            try:
                works = _fetch_openalex_paginated(query)
            except Exception as e:  # noqa: BLE001 — 한 쿼리 실패해도 나머지는 계속 진행
                print(f"[paper_collector] OpenAlex '{category}' 쿼리 실패: {e}")
                continue

            for work in works:
                row = _openalex_work_to_row(work, category, seen_arxiv_ids, language="en")
                if row:
                    results.append(row)

            time.sleep(OPENALEX_INTERVAL_SEC)

    # ---------------- OpenAlex (한국어 논문, language=ko) ----------------
    print(f"[paper_collector] 5/7 OpenAlex(KO) 시작 (누적 {len(results)}건)")
    # 2026-09-17 추가: KCI Open API 인증키 승인 대기 중 — 그동안 국내 논문 공백을 메우는 임시
    # 대체 경로. 모듈 docstring [OpenAlex 한국 논문] 참고. KCI 승인되면 그쪽이 주력이 되고
    # 이 패스는 계속 병행(겹치는 DOI가 거의 없어 중복 걱정 없음).
    for category, queries in OPENALEX_KOREAN_QUERIES.items():
        for query in queries:
            try:
                works = _fetch_openalex_paginated(query, language="ko")
            except Exception as e:  # noqa: BLE001
                print(f"[paper_collector] OpenAlex(한국어) '{category}' 쿼리 실패: {e}")
                continue

            for work in works:
                row = _openalex_work_to_row(work, category, seen_arxiv_ids, language="ko")
                if row:
                    results.append(row)

            time.sleep(OPENALEX_INTERVAL_SEC)

    # ---------------- KCI REST (한국어 논문, 키워드 정밀검색) ----------------
    if KCI_API_KEY:
        print(f"[paper_collector] 6/7 KCI REST(키워드검색) 시작 (누적 {len(results)}건)")
        # 2026-09-21 추가: 모듈 상단 [KCI REST] 주석 참고. OPENALEX_KOREAN_QUERIES를 그대로
        # title 검색어로 재사용 — 이미 카테고리별로 다듬어둔 한국어 쿼리라 그대로 쓸 수 있음.
        seen_kci_rest_urls: set[str] = set()
        for category, queries in OPENALEX_KOREAN_QUERIES.items():
            for query in queries:
                try:
                    rows = _fetch_kci_rest(query, category)
                except Exception as e:  # noqa: BLE001 — 이 쿼리만 실패, 나머지는 계속 진행
                    print(f"[paper_collector] KCI REST '{category}' 쿼리 실패: {e}")
                    continue

                for row in rows:
                    if row["url"] in seen_kci_rest_urls:
                        continue  # 같은 실행 안에서 쿼리끼리 겹치는 것만 1차로 거름(완전중복은 ingest.py가 최종 처리)
                    seen_kci_rest_urls.add(row["url"])
                    results.append(row)

                time.sleep(KCI_REST_INTERVAL_SEC)
    else:
        print("[paper_collector] 6/7 KCI REST — KCI_API_KEY 없음, 스킵")

    # ---------------- KCI OAI-PMH (한국어 논문, 최근 등록분 수확) ----------------
    print(f"[paper_collector] 7/7 KCI OAI-PMH 시작 (누적 {len(results)}건, 수 분 걸릴 수 있음)")
    # 2026-09-17 추가: 모듈 docstring [KCI OAI-PMH] 참고. REST(위 단계)가 title 키워드로 못
    # 잡는 논문(제목엔 안 나오지만 본문/초록에 주제가 있는 경우 등)까지 폭넓게 보완하는 역할로
    # 계속 병행 — 둘 다 같은 KCI 저장소라 겹치는 논문이 나올 수 있지만 url이 같으면 ingest.py
    # 단계의 content_hash/근접중복 검사가 최종적으로 걸러줌.
    try:
        kci_rows = _fetch_kci_oai()
    except Exception as e:  # noqa: BLE001 — 이 소스 실패해도 나머지 결과는 그대로 반환
        print(f"[paper_collector] KCI OAI-PMH 수확 실패: {e}")
        kci_rows = []
    results.extend(kci_rows)

    print(f"[paper_collector] 전체 수집 완료 — 총 {len(results)}건 (ingest 단계로 넘어감)")
    return results


if __name__ == "__main__":
    docs = collect()
    print(f"{len(docs)}건 수집")
    for d in docs[:10]:
        print(f"- [{d['source_name']}/{d['category']}/{d['language']}] {d['title']} ({d['url']})")
