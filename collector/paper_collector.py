"""
논문 데이터 수집기 — arXiv API 사용 (API 키 불필요, 무료).

news_collector.py와 같은 규약: collect() -> list[dict] (documents 컬럼과 1:1 대응).
content는 논문 원문 전체가 아니라 초록(abstract)임 — 전체 PDF 본문까지 수집하려면
scripts/ingest_pdfs.py로 PDF를 직접 내려받아 data/<category>/ 에 넣는 방식을 병행할 것.

arXiv API 공식 문서: https://info.arxiv.org/help/api/user-manual.html
- 키 불필요. 단, 공식 권장 사항으로 요청 사이 최소 3초 간격을 둠(과호출 시 차단될 수 있음).
- 응답이 Atom XML이라 RSS와 동일하게 feedparser로 파싱 가능(추가 의존성 없음).

⚠️ 참고: 이 API는 export.arxiv.org 도메인이라 일부 네트워크 환경(예: 샌드박스형 격리 VM)의
egress allowlist에 없으면 막힐 수 있음. 일반 PC/서버 환경에서는 문제없이 접속됨.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from urllib.parse import quote

import feedparser  # pip install feedparser

ARXIV_API = "http://export.arxiv.org/api/query"

# 주제(생성형 AI와 음악 창작)의 4개 하위쟁점별 검색 쿼리.
# abs: = 초록(abstract) 안에서 검색. 필요하면 팀 논의로 쿼리 문구를 더 좁히거나 넓힐 것.
QUERIES: dict[str, str] = {
    "저작권": 'abs:"music generation" AND abs:copyright',
    "창작자성": 'abs:"AI music" AND (abs:authorship OR abs:"co-creation" OR abs:"computational creativity")',
    "음성복제": 'abs:"voice cloning" OR abs:"voice conversion" OR abs:"singing voice synthesis"',
    "AI작곡": '(abs:"music composition" OR abs:"symbolic music generation" OR abs:"text-to-music") AND (abs:neural OR abs:transformer OR abs:generative)',
}

MAX_RESULTS_PER_QUERY = 30
REQUEST_INTERVAL_SEC = 3  # arXiv 공식 권장 최소 간격


def _fetch_query(query: str) -> list:
    url = (
        f"{ARXIV_API}?search_query={quote(query)}"
        f"&start=0&max_results={MAX_RESULTS_PER_QUERY}"
        f"&sortBy=submittedDate&sortOrder=descending"
    )
    parsed = feedparser.parse(url)
    return parsed.entries


def collect() -> list[dict]:
    results: list[dict] = []
    seen_ids: set[str] = set()

    for category, query in QUERIES.items():
        try:
            entries = _fetch_query(query)
        except Exception as e:  # noqa: BLE001 — 한 쿼리 실패해도 나머지는 계속 진행
            print(f"[paper_collector] '{category}' 쿼리 실패: {e}")
            continue

        for entry in entries:
            arxiv_id = entry.get("id", "")
            if not arxiv_id or arxiv_id in seen_ids:
                continue
            seen_ids.add(arxiv_id)

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

    return results


if __name__ == "__main__":
    docs = collect()
    print(f"{len(docs)}건 수집")
    for d in docs[:10]:
        print(f"- [{d['category']}] {d['title']} ({d['url']})")
