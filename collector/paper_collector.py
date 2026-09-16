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
"""
from __future__ import annotations

import time
from datetime import date, datetime
from urllib.parse import quote

import feedparser  # pip install feedparser
import requests  # pip install requests

ARXIV_API = "http://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"

# 2026-09-16: "최신 데이터 위주로 수집" 전략 — 오래된 논문이 검색 결과 상위를 차지해서
# 최신 논문이 덜 잡히는 문제를 줄이기 위해 연도 필터를 추가. arXiv/Semantic Scholar 둘 다
# 이 연도 '이후' 논문만 수집(과거 논문을 아예 안 모으는 게 아니라, 최신 쪽으로 비중을 옮기는 것).
# 필요하면 팀 논의로 조정할 것.
PAPER_YEAR_FROM = 2023

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

# 보수적으로 조정 — 처음엔 200/300까지 잡았다가, rate limit 리스크/비용 안전마진을 위해
# 한 단계 낮춤. 그래도 원래(30/20)보다는 넉넉해서 수집량은 여전히 늘어남.
MAX_RESULTS_PER_QUERY = 100  # 200 -> 100
REQUEST_INTERVAL_SEC = 3  # arXiv 공식 권장 최소 간격

SEMANTIC_SCHOLAR_MAX_RESULTS = 100  # API가 한 번에 주는 최대치(페이지당) — 이건 그대로 둠
SEMANTIC_SCHOLAR_MAX_PAGES = 2  # 3 -> 2 (쿼리당 최대 200건), 무료 풀 rate limit 부담 줄임
SEMANTIC_SCHOLAR_INTERVAL_SEC = 4  # 3 -> 4, 안전마진 더 둠
SEMANTIC_SCHOLAR_MAX_RETRIES = 3
SEMANTIC_SCHOLAR_RETRY_BACKOFF_SEC = 5  # 429 맞으면 5, 10, 20초... 늘려가며 재시도


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


def _arxiv_short_id(raw_id: str) -> str:
    """arXiv entry id('http://arxiv.org/abs/2309.01234v1')에서 순수 ID('2309.01234')만 뽑음.
    Semantic Scholar의 externalIds.ArXiv 값과 비교해서 중복을 걸러내는 데 씀."""
    tail = raw_id.rstrip("/").rsplit("/", 1)[-1]
    return tail.split("v")[0] if "v" in tail else tail


def collect() -> list[dict]:
    results: list[dict] = []
    seen_arxiv_ids: set[str] = set()

    # ---------------- arXiv ----------------
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

                published_at = date.today()
                if entry.get("published"):
                    try:
                        published_at = datetime.strptime(entry.published[:10], "%Y-%m-%d").date()
                    except ValueError:
                        pass

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

    # ---------------- Semantic Scholar ----------------
    for category, queries in SEMANTIC_SCHOLAR_QUERIES.items():
        for query in queries:
            try:
                papers = _fetch_semantic_scholar_paginated(query)
            except Exception as e:  # noqa: BLE001
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

    return results


if __name__ == "__main__":
    docs = collect()
    print(f"{len(docs)}건 수집")
    for d in docs[:10]:
        print(f"- [{d['source_name']}/{d['category']}] {d['title']} ({d['url']})")
