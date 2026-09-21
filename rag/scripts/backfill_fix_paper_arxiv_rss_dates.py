"""
document_type='paper' 문서 중 arXiv RSS 경로(collector/paper_collector.py의 _fetch_arxiv_rss,
"카테고리 전체 최신 논문" — 검색어 없는 cs.SD/eess.AS 피드)로 수집된 문서들의 published_at을
바로잡는 일회성 백필 스크립트.

배경 (2026-09-21 발견): news_collector.py의 Digital Music News 피드 버그(날짜 필드가 조용히
실패해서 매번 수집일로 저장됨)를 고치던 중, document_type='paper' 쪽에도 같은 패턴이 있는지
확인해달라는 요청으로 실제 export(documents_20260921_203317.json, 1365건)를 분석함. arXiv
URL에 버전 접미사(v1/v2...)가 있는지 없는지로 나눠보니:
  - 버전 있음(검색 API 경로, _fetch_query — entry.published가 항상 있었음): 229건, 0건이
    published_at == created_at(수집일)
  - 버전 없음(RSS 경로, _fetch_arxiv_rss — entry.published_parsed가 실측상 항상 비어있었던
    것으로 추정): 9건, **9건 전부** published_at == created_at
신호가 9/9 vs 0/229로 완벽하게 갈려서 RSS 경로의 버그로 확정. 그 중 4건은 arXiv ID 자체
(YYMM.NNNNN — 연-월이 ID에 박혀있음)로 실제 게재월이 수집일과 몇 달씩 다르다는 것까지 직접
증명됨(예: ID 2601.xxxxx=2026년 1월 게재인데 published_at=2026-09-17=수집일로 저장돼 있었음).

paper_collector.py의 _fetch_arxiv_rss 쪽은 이미 고쳐서(published_parsed -> updated_parsed ->
arXiv ID 연-월(_arxiv_id_month_date) -> 그래도 없으면 수집일+경고로그) 앞으로 수집되는 문서는
정상 — 이 스크립트는 그 전에 이미 저장된 9건(및 앞으로 같은 패턴으로 저장될 수 있는 문서 전부)을
바로잡음.

정확도 우선순위 — 이 스크립트는 paper_collector.py의 "ID 연-월(일자=1일)" 폴백보다 한 단계 더
정확하게 고칠 수 있음: arXiv 공식 Atom API(export.arxiv.org)에 id_list로 재조회하면 그 논문의
정확한 entry.published(연-월-일 전체)를 돌려주기 때문(검색 API 경로가 항상 이 필드를 정상적으로
받아온다는 게 위 229건에서 이미 확인됨 — backfill_fix_arxiv_paper_noise.py와 동일한 배치조회
패턴 재사용). 그래서:
  1순위: Atom API 재조회로 얻은 정확한 entry.published(일자까지 정확)
  2순위: API 응답에 그 ID가 없으면(철회된 프리프린트 등) paper_collector.py와 동일한
         _arxiv_id_month_date(연-월만, 일자는 1일로 근사) — 화면에 "근사치"로 표시
  3순위: 그것도 안 되면 손대지 않고 그대로 둠(수동 확인 필요로 표시)

본문(content)/chunks/embedding은 전혀 안 건드림 — documents.published_at 컬럼만 갱신.

대상 필터: document_type='paper' AND url이 "arxiv.org/abs/<YYMM.NNNNN>"로 끝나고 버전
접미사(v1 등)가 없는 문서만 — 이게 바로 위에서 실증한 "RSS 경로로 수집된 문서" 시그니처라
정밀하게 좁혀짐(검색 API로 정상 수집된 229건은 전부 버전 접미사가 있어서 대상에서 자동 제외됨).

실행 (secondpj 루트에서, venv 활성화 상태로):
    python -m rag.scripts.backfill_fix_paper_arxiv_rss_dates              # 미리보기 (기본, 안전)
    python -m rag.scripts.backfill_fix_paper_arxiv_rss_dates --apply      # 실제로 DB에 반영
    python -m rag.scripts.backfill_fix_paper_arxiv_rss_dates --apply --limit=5  # 소규모 확인
"""
from __future__ import annotations

import sys
import time
from datetime import date, datetime

import feedparser  # pip install feedparser

from collector.paper_collector import ARXIV_API, _arxiv_id_month_date, _arxiv_short_id
from rag import config

BATCH_SIZE = 40  # backfill_fix_arxiv_paper_noise.py와 동일 — id_list URL 길이 보수적으로 제한
REQUEST_INTERVAL_SEC = 3  # arXiv 공식 권장 최소 간격, paper_collector.py/다른 백필과 동일


def _fetch_batch_dates(arxiv_ids: list[str]) -> dict[str, date]:
    """id_list 배치 조회 -> {arxiv_id(버전 없는 순수 ID): entry.published 날짜} 딕셔너리.
    응답에 없는 id는 그냥 빠짐(호출부가 "못 찾음"으로 처리 -> 2순위 폴백으로 넘어감)."""
    id_list = ",".join(arxiv_ids)
    url = f"{ARXIV_API}?id_list={id_list}&max_results={len(arxiv_ids)}"
    parsed = feedparser.parse(url)
    out: dict[str, date] = {}
    for entry in parsed.entries:
        short_id = _arxiv_short_id(entry.get("id", ""))
        published = entry.get("published")
        if not short_id or not published:
            continue
        try:
            out[short_id] = datetime.strptime(published[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
    return out


def main() -> None:
    apply_changes = "--apply" in sys.argv

    limit: int | None = None
    offset = 0
    for arg in sys.argv:
        if arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
        elif arg.startswith("--offset="):
            offset = int(arg.split("=", 1)[1])

    with config.get_connection() as conn:
        with conn.cursor() as cur:
            # 버전 접미사(v\d+)가 URL 끝에 없는 것만 — 이게 RSS 경로로 수집된 문서의 시그니처
            # (실증: 1789990415645_documents_20260921_203317.json 분석, 9/9 vs 0/229).
            cur.execute(
                r"""
                SELECT id, url, published_at, title
                FROM documents
                WHERE document_type = 'paper'
                  AND url ~ 'arxiv\.org/abs/\d{4}\.\d{4,5}$'
                ORDER BY created_at;
                """
            )
            rows = cur.fetchall()

        targets = [(doc_id, url, old_pub, title, _arxiv_short_id(url)) for doc_id, url, old_pub, title in rows]
        batch = targets[offset : offset + limit] if limit is not None else targets[offset:]

        mode_label = "실제 반영 모드" if apply_changes else "dry-run (미리보기만, DB는 안 건드림)"
        print(f"대상(버전 접미사 없는 arXiv 논문) {len(targets)}건 중 offset={offset}부터 {len(batch)}건 처리 — {mode_label}")

        corrected_exact = 0
        corrected_approx = 0
        unchanged = 0
        not_found_needs_manual = 0

        for batch_start in range(0, len(batch), BATCH_SIZE):
            chunk = batch[batch_start : batch_start + BATCH_SIZE]
            arxiv_ids = [t[4] for t in chunk]
            try:
                fetched = _fetch_batch_dates(arxiv_ids)
            except Exception as e:  # noqa: BLE001 — 배치 하나 실패해도 나머지 배치는 계속 진행
                print(f"배치 조회 실패({arxiv_ids[0]}...{arxiv_ids[-1]}): {e}")
                fetched = {}
            time.sleep(REQUEST_INTERVAL_SEC)

            for doc_id, url, old_pub, title, arxiv_id in chunk:
                new_pub = fetched.get(arxiv_id)
                approx = False
                if new_pub is None:
                    # 1순위(API 정확 날짜) 실패 -> 2순위(ID 연-월 근사치)로
                    new_pub = _arxiv_id_month_date(arxiv_id)
                    approx = True

                if new_pub is None:
                    print(f"  {doc_id} ({url}): 근사치도 못 뽑음 — 수동 확인 필요 (기존값 유지: {old_pub})")
                    not_found_needs_manual += 1
                    continue

                if new_pub == old_pub:
                    unchanged += 1
                    continue

                tag = "(근사치, 일자=1일)" if approx else "(정확)"
                print(f"  {doc_id} ({title[:40]!r}): {old_pub} -> {new_pub} {tag}  ({url})")
                if apply_changes:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE documents SET published_at = %s WHERE id = %s;",
                            (new_pub, doc_id),
                        )
                    conn.commit()
                if approx:
                    corrected_approx += 1
                else:
                    corrected_exact += 1

    print(
        f"\n끝 — 정확히 교정 {corrected_exact}건, 근사치로 교정 {corrected_approx}건, "
        f"변경 없음 {unchanged}건, 수동 확인 필요 {not_found_needs_manual}건"
    )
    if not apply_changes and (corrected_exact or corrected_approx):
        print("dry-run이었습니다 — 실제로 반영하려면 --apply를 붙여서 다시 실행하세요:")
        print("    python -m rag.scripts.backfill_fix_paper_arxiv_rss_dates --apply")


if __name__ == "__main__":
    main()
