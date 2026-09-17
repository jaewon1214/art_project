"""
판례 수집기 — 국가법령정보 공동활용 Open API(law.go.kr)의 판례 검색/본문조회를 사용.

⚠️ 이 API는 사전 승인(OC 발급)이 필요함 — .env에 LAW_API_OC가 없으면 collect()가 빈 리스트를
반환하고 아무 것도 안 함(다른 수집기들의 LLM_PROVIDER/EMBEDDING_PROVIDER 미설정 시 동작과 동일한
"설정 있으면 쓰고 없으면 건너뛴다" 패턴). open.law.go.kr 승인 나서 발급받은 OC 값을 .env에
LAW_API_OC=... 로 넣으면 바로 활성화됨 (보통 신청 시 등록한 이메일의 @ 앞부분이 OC 값).

document_type="case"는 database/init/01_schema.sql에 이미 허용값으로 예약돼 있었음
(주석에 "(필요시) 'paper' | 'case'"로 명시) — 스키마 변경 없이 바로 씀.

[API 참고]
공식 가이드: https://open.law.go.kr/LSO/openApi/guideList.do
- 판례 목록 조회: GET http://www.law.go.kr/DRF/lawSearch.do
    ?OC=...&target=prec&type=JSON&query=...&search=2&display=100
    (search=2 는 본문검색 — 판례명이 아니라 전체 텍스트에서 검색어를 찾음. 기본값 1은 판례명만 검색)
- 판례 본문 조회: GET http://www.law.go.kr/DRF/lawService.do
    ?OC=...&target=prec&ID=<판례일련번호>&type=JSON

⚠️ 공식 문서가 필드명만 알려주고 정확한 JSON 중첩 구조(래핑 key 이름 등)는 안 나와 있어서,
law.go.kr Open API의 일반적인 응답 패턴을 기준으로 작성함(_fetch_list/_fetch_detail 안의 주석
참고). OC 발급받아서 처음 돌려보면 실제 JSON 구조가 다를 수 있으니, 그러면 그 결과를 보고
파싱 부분만 손보면 됨 — 나머지 흐름(카테고리 매핑, ingest 연결 등)은 그대로 유효함.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime

import requests
from dotenv import load_dotenv

from rag.preprocessing.clean_html import is_too_short, strip_html

# 다른 collector들은 database.config/rag.config를 거치면서 거기서 load_dotenv()가 이미
# 호출되지만, case_collector는 DB 모듈을 안 거치는 독립 모듈이라 .env가 전혀 안 읽히고
# LAW_API_OC가 항상 빈 값으로 남는 버그가 있었음 — 여기서 직접 로드해서 고침.
load_dotenv()

LAW_API_OC = os.environ.get("LAW_API_OC", "").strip()
LAW_SEARCH_URL = "http://www.law.go.kr/DRF/lawSearch.do"
LAW_SERVICE_URL = "http://www.law.go.kr/DRF/lawService.do"

# 카테고리별 검색어. search=2(본문검색)라 판례 전문 어딘가에 이 단어가 있으면 걸림.
# 국내에 "AI 음악"/"음성복제" 자체를 다룬 판례는 아직 거의 없을 걸로 예상돼서 일부러 조금
# 넓게 잡음(예: "인공지능 저작권") — 관련 없는 건 다른 수집기와 동일하게 LLM 관련성판정에서 걸러짐.
#
# 2026-09-16: paper_collector.py와 동일한 패턴으로 카테고리당 쿼리 2개로 확장(원래 1개씩).
# case 카테고리는 원천적으로 판례 자체가 적어서(실측: 12건 중 신규 5건) 쿼리를 더 넓혀서 recall을
# 늘리는 게 official/policy처럼 "새 URL 찾기"보다 효율적 — 동일 판례가 여러 쿼리에 잡혀도
# collect()의 seen_ids로 중복 제거되니 안전함.
QUERIES: dict[str, list[str]] = {
    "저작권": ["인공지능 저작권", "생성형 AI 저작권"],
    "창작자성": ["인공지능 저작물 창작", "AI 창작물 저작자"],
    "음성복제": ["음성권 침해", "AI 음성 합성"],
    "AI작곡": ["인공지능 음악", "AI 작곡 저작권"],
}

MAX_RESULTS_PER_QUERY = 100  # display 파라미터 최대값(100)까지 올림 — 쿼리 2배로 늘었으니 상한도 맞춤
REQUEST_INTERVAL_SEC = 1


def _fetch_list(query: str) -> list[dict]:
    resp = requests.get(
        LAW_SEARCH_URL,
        params={
            "OC": LAW_API_OC,
            "target": "prec",
            "type": "JSON",
            "query": query,
            "search": 2,  # 본문검색
            "display": MAX_RESULTS_PER_QUERY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    # law.go.kr 계열 API의 통상적인 래핑 패턴: {"PrecSearch": {"prec": [...] 또는 {...}}}
    items = data.get("PrecSearch", data).get("prec", [])
    if isinstance(items, dict):  # 결과가 1건뿐이면 리스트가 아니라 dict 단건으로 오는 경우가 흔함
        items = [items]
    return items


def _fetch_detail(prec_id: str) -> dict:
    resp = requests.get(
        LAW_SERVICE_URL,
        params={"OC": LAW_API_OC, "target": "prec", "type": "JSON", "ID": prec_id},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("PrecService", data)


def _parse_date(raw) -> date | None:
    if not raw:
        return None
    raw = str(raw).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def collect() -> list[dict]:
    if not LAW_API_OC:
        print("[case_collector] LAW_API_OC 미설정 — 판례 수집 건너뜀 (open.law.go.kr 승인 후 .env에 추가할 것)")
        return []

    results: list[dict] = []
    seen_ids: set[str] = set()

    for category, queries in QUERIES.items():
        for query in queries:
            try:
                items = _fetch_list(query)
            except Exception as e:  # noqa: BLE001 — 한 쿼리 실패해도 나머지는 계속 진행
                print(f"[case_collector] '{category}' / '{query}' 목록 조회 실패: {e}")
                continue

            for item in items:
                prec_id = str(item.get("판례일련번호", "")).strip()
                if not prec_id or prec_id in seen_ids:
                    continue
                seen_ids.add(prec_id)

                try:
                    detail = _fetch_detail(prec_id)
                except Exception as e:  # noqa: BLE001
                    print(f"[case_collector] 본문 조회 실패 (ID={prec_id}): {e}")
                    continue

                # 판시사항 + 판결요지 + 판례내용을 이어붙여서 content로 — 셋 다 없으면 빈 문서라 스킵.
                # law.go.kr류 국내 공공 API는 원래 HTML로 렌더링하던 판결문을 텍스트 필드로 그대로
                # 내려주는 경우가 있어서 <br/>, &nbsp; 같은 HTML 잔재가 섞여 나올 수 있음 — news/
                # official/policy_collector와 동일하게 strip_html()로 한 번 걸러줌(이미 순수 텍스트여도
                # strip_html은 원문을 그대로 통과시키니 손해볼 게 없음).
                parts = [
                    detail.get("판시사항", ""),
                    detail.get("판결요지", ""),
                    detail.get("판례내용", ""),
                ]
                doc_content = strip_html("\n\n".join(p for p in parts if p).strip())
                if not doc_content or is_too_short(doc_content):
                    continue

                results.append(
                    {
                        "title": item.get("사건명") or detail.get("사건명") or f"판례 {prec_id}",
                        "content": doc_content,
                        "url": item.get("판례상세링크") or f"https://www.law.go.kr/precInfoP.do?precSeq={prec_id}",
                        "author": item.get("법원명") or detail.get("법원명"),
                        "category": category,
                        "document_type": "case",
                        "published_at": _parse_date(item.get("선고일자") or detail.get("선고일자")),
                        "language": "ko",
                        "source_name": "국가법령정보 공동활용(판례)",
                    }
                )

                time.sleep(REQUEST_INTERVAL_SEC)

            time.sleep(REQUEST_INTERVAL_SEC)

    return results


if __name__ == "__main__":
    docs = collect()
    print(f"{len(docs)}건 수집")
    for d in docs[:10]:
        print(f"- [{d['category']}] {d['title']} ({d['url']})")
