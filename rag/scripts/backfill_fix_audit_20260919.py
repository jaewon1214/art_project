"""
2026-09-19 데이터 감사(JSON 전체 export 1193건 검토)에서 발견된 문제 문서들만 골라 고치는
일회성 타겟 백필 스크립트.

배경 — 감사에서 찾은 문제들:
  1. language 필드 오분류 (news 53건 + official 2건 + paper 1건, 총 56건): 번역 정책 폐지
     (2026-09-17, rag/pipeline/ingest.py) 이전에 번역됐던 문서들의 language 잔재.
     backfill_restore_original.py와 원인이 같음.
  2. 사이드바/위젯 노이즈 오염: newsen.com류의 "Loading..." 플레이스홀더 + ♥ 가십 헤드라인,
     gamechosun.co.kr/theguru.co.kr류의 "최신 기사"/"주간 인기 기사"/"많이 본 뉴스" 꼬리말
     위젯. → 이번에 rag/preprocessing/clean_html.py에 4가지 필터 추가로 해결
     (normalize_whitespace의 리터럴 <br> 제거, Loading... 패턴, ♥ 라인 필터,
     _truncate_at_footer_widgets). 이 스크립트는 그 개선된 clean_html.py를 통해 재수집하는
     방식으로 실제 데이터에 적용함.
  3. 리터럴 "<br><br>" 텍스트 잔존(livemint.com) — 위 2번과 같은 clean_html.py 수정으로 함께
     해결됨(별도 처리 불필요).

document_type in ('news','official','policy') 전체 756건을 재수집하는 기존
backfill_restore_original.py / backfill_fix_encoding.py를 그대로 돌리기엔 시간이 너무 걸려서
(device_bash 1콜 180초 제한), 감사로 실제 문제라고 확인된 108건만 골라 재수집하는 축소판.
재수집 로직 자체는 news_collector._extract_body / official_collector._fetch_page를 그대로
재사용 — 이 함수들이 내부적으로 clean_html.strip_boilerplate_lines/normalize_whitespace를
호출하므로, 재수집만 해도 개선된 클리닝 로직이 자동 적용됨.

paper 타입 1건은 예외: paper_collector가 페이지 스크래핑이 아니라 arXiv/Semantic
Scholar/OpenAlex API 기반이라 이 스크립트의 재수집 방식으로 다시 못 가져옴. 감사에서 이미
해당 문서의 content 자체는 정상(한국어)이라고 직접 확인했으므로, 재수집 없이 language
필드만 'ko'로 직접 UPDATE.

대상 목록: rag/scripts/audit_20260919_targets.json ([{"url":..., "document_type":...}, ...],
108건 — url만으로 documents 테이블에서 실제 행을 조회함. document_type은 재수집 함수 선택 및
확인용).

문서 하나당 처리:
  1. url로 documents에서 조회(없으면 스킵 — url이 그새 바뀌었거나 감사 이후 삭제된 경우).
  2. document_type == 'paper' → 재수집 없이 language를 'ko'로 UPDATE하고 종료(이미 'ko'면
     변경 없음으로 카운트).
  3. 그 외(news/official) → _refetch()로 재수집.
     - 재수집 실패/빈 본문 → 스킵(기존 값 유지), 실패 목록에 기록.
  4. new_hash = content_hash(raw), new_language = 'ko' if _is_already_korean(raw) else 'en'.
     - content_hash가 기존과 다르면: content/content_hash/language 전부 교체 + chunk/embedding
       재생성(_rebuild_chunks).
     - content_hash는 같지만 language만 기존과 다르면: language만 UPDATE(chunk 재생성 불필요 —
       chunks.content는 documents.content 기준이라 안 바뀜).
     - 둘 다 같으면: 변경 없음.
  (이 문서 단위 판단은 backfill_restore_original.py보다 한 단계 더 세밀함 — 원래 스크립트는
  hash가 같으면 language 재계산 자체를 건너뛰었는데, 이 108건 중 일부는 content는 이미
  정상이면서 language만 잘못된 케이스라 language 단독 교정 경로를 추가함.)

기본값은 dry-run(미리보기만, DB 안 건드림). --apply로 실제 반영.
device_bash 180초 제한 대응으로 --limit/--offset 지원 — 예: 먼저 --apply --limit 40으로 앞
40건 처리 후, --apply --offset 40 --limit 40으로 다음 배치 처리하는 식으로 나눠 실행 가능.

실행 (secondpj 루트에서):
    python -m rag.scripts.backfill_fix_audit_20260919                          # 미리보기
    python -m rag.scripts.backfill_fix_audit_20260919 --apply --limit 40       # 앞 40건 반영
    python -m rag.scripts.backfill_fix_audit_20260919 --apply --offset 40      # 41번째부터 전부
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import psycopg2

from rag import config
from rag.chunking.chunker import build_chunk_rows
from rag.embedding.embed import embed_texts, embedding_to_pgvector_literal
from rag.preprocessing.dedupe import content_hash

_HANGUL_RE = re.compile(r"[가-힣]")

TARGETS_PATH = Path(__file__).with_name("audit_20260919_targets.json")

# 재수집 사이 최소 간격 — 다른 백필 스크립트들과 동일한 예의상 간격.
SLEEP_SEC = 1.0


def _refetch(document_type: str, url: str) -> str:
    """document_type에 맞는 collector의 본문 추출 함수로 url을 다시 긁어와 본문 텍스트만 반환.

    2026-09-19 실행 중 발견: news_collector._extract_body()는 (content, page_date) 튜플을
    반환함(backfill_fix_encoding.py의 기존 사용 패턴과 실제 실행 결과로 확인 — 애초에 참고했던
    backfill_restore_original.py의 동명 함수는 이 부분을 안 풀고 그대로 반환하는 버그가 있었고,
    이 스크립트도 그대로 베껴서 같은 버그가 있었음. 여기서 고침 — backfill_restore_original.py
    쪽은 아직 안 고쳐져 있으니 나중에 그 스크립트를 실행할 일이 있으면 같이 고칠 것)."""
    if document_type == "news":
        from collector.news_collector import _extract_body

        content, _page_date = _extract_body(url)
        return content
    if document_type == "official":
        from collector.official_collector import _fetch_page

        _, content = _fetch_page(url)
        return content
    raise ValueError(f"이 스크립트가 재수집을 지원하지 않는 document_type: {document_type}")


def _is_already_korean(text: str, min_ratio: float = 0.2) -> bool:
    """텍스트가 한글 위주면 True — backfill_restore_original.py의 동명 함수와 동일 기준."""
    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return False
    hangul = sum(1 for c in non_space if _HANGUL_RE.match(c))
    return (hangul / len(non_space)) >= min_ratio


def _rebuild_chunks(conn, document_id, content: str) -> int:
    """backfill_restore_original.py / backfill_fix_encoding.py와 동일한 패턴."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE document_id = %s;", (document_id,))

    chunk_rows = build_chunk_rows(document_id, content)
    if not chunk_rows:
        conn.commit()
        return 0

    chunk_id_by_index: dict[int, str] = {}
    with conn.cursor() as cur:
        for row in chunk_rows:
            cur.execute(
                """
                INSERT INTO chunks (document_id, chunk_index, content, content_tokenized, token_count)
                VALUES (%(document_id)s, %(chunk_index)s, %(content)s, %(content_tokenized)s, %(token_count)s)
                RETURNING id;
                """,
                row,
            )
            chunk_id_by_index[row["chunk_index"]] = cur.fetchone()[0]
    conn.commit()

    if config.EMBEDDING_PROVIDER:
        vectors = embed_texts([row["content"] for row in chunk_rows])
        with conn.cursor() as cur:
            for row, vec in zip(chunk_rows, vectors):
                cur.execute(
                    "UPDATE chunks SET embedding = %s::vector WHERE id = %s;",
                    (embedding_to_pgvector_literal(vec), chunk_id_by_index[row["chunk_index"]]),
                )
        conn.commit()

    return len(chunk_rows)


def _load_targets() -> list[dict]:
    with open(TARGETS_PATH, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    apply_changes = "--apply" in sys.argv

    limit: int | None = None
    offset = 0
    for arg in sys.argv:
        if arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
        elif arg.startswith("--offset="):
            offset = int(arg.split("=", 1)[1])

    targets = _load_targets()
    batch = targets[offset : offset + limit] if limit is not None else targets[offset:]

    mode_label = "실제 반영 모드" if apply_changes else "dry-run (미리보기만, DB는 안 건드림)"
    print(
        f"감사 타겟 {len(targets)}건 중 offset={offset}부터 {len(batch)}건 처리 — {mode_label}"
    )

    content_replaced = 0
    lang_only_fixed = 0
    unchanged = 0
    not_found = 0
    failed: list[tuple[str, str]] = []

    with config.get_connection() as conn:
        for i, target in enumerate(batch, start=1):
            url = target["url"]
            doc_type = target["document_type"]

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, content, content_hash, language FROM documents WHERE url = %s;",
                    (url,),
                )
                row = cur.fetchone()

            if row is None:
                print(f"[{i}/{len(batch)}] NOT FOUND: {url}")
                not_found += 1
                continue

            doc_id, old_content, old_hash, old_language = row

            if doc_type == "paper":
                # 재수집 불가(API 기반 collector) — 감사에서 이미 content는 정상 한국어로
                # 확인됨. language만 직접 교정.
                if old_language == "ko":
                    unchanged += 1
                    continue
                print(f"[{i}/{len(batch)}] {doc_id} (paper): language {old_language!r} -> 'ko'")
                if apply_changes:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE documents SET language = %s WHERE id = %s;", ("ko", doc_id)
                        )
                    conn.commit()
                lang_only_fixed += 1
                continue

            try:
                raw = _refetch(doc_type, url)
            except Exception as e:  # noqa: BLE001
                print(f"[{i}/{len(batch)}] {doc_id} ({doc_type}, {url}): 재수집 실패({e}) — 스킵")
                failed.append((url, str(e)))
                time.sleep(SLEEP_SEC)
                continue

            if not raw or not raw.strip():
                print(f"[{i}/{len(batch)}] {doc_id} ({doc_type}, {url}): 재수집 결과가 비어있음 — 스킵")
                failed.append((url, "빈 본문"))
                time.sleep(SLEEP_SEC)
                continue

            new_hash = content_hash(raw)
            new_language = "ko" if _is_already_korean(raw) else "en"

            if new_hash != old_hash:
                print(
                    f"[{i}/{len(batch)}] {doc_id} ({doc_type}): content 교체 "
                    f"({len(old_content)}자 -> {len(raw)}자), language {old_language!r} -> {new_language!r}"
                )
                if apply_changes:
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE documents SET content = %s, content_hash = %s, language = %s "
                                "WHERE id = %s;",
                                (raw, new_hash, new_language, doc_id),
                            )
                        conn.commit()
                    except psycopg2.errors.UniqueViolation:
                        conn.rollback()
                        print(f"    -> 재수집 후 다른 문서와 내용 중복 — 스킵")
                        failed.append((url, "content_hash unique violation"))
                        time.sleep(SLEEP_SEC)
                        continue

                    try:
                        n_chunks = _rebuild_chunks(conn, doc_id, raw)
                        print(f"    -> chunk {n_chunks}개 재생성 완료")
                    except Exception as e:  # noqa: BLE001
                        conn.rollback()
                        print(f"    -> chunk 재생성 실패({e}) — content는 갱신됐지만 chunk는 옛날 것으로 남음")
                        failed.append((url, str(e)))
                        time.sleep(SLEEP_SEC)
                        continue
                content_replaced += 1

            elif new_language != old_language:
                print(f"[{i}/{len(batch)}] {doc_id} ({doc_type}): language만 교정 {old_language!r} -> {new_language!r}")
                if apply_changes:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE documents SET language = %s WHERE id = %s;",
                            (new_language, doc_id),
                        )
                    conn.commit()
                lang_only_fixed += 1

            else:
                unchanged += 1

            time.sleep(SLEEP_SEC)

    print(
        f"\n끝 — content 교체 {content_replaced}건, language만 교정 {lang_only_fixed}건, "
        f"변경 없음 {unchanged}건, 문서 못 찾음 {not_found}건, 실패 {len(failed)}건"
    )
    if failed:
        print("실패한 URL:")
        for url, reason in failed:
            print(f"  - {url}: {reason}")
    if not apply_changes:
        print("\ndry-run이었습니다 — 실제로 반영하려면 --apply를 붙여서 다시 실행하세요.")


if __name__ == "__main__":
    main()
