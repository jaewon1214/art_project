"""
현재 DB에 저장된 documents를 통째로(또는 필터링해서) JSON 파일 하나로 내보내는 범용 스크립트.

export_papers.py는 document_type='paper'만, 2번(모델팀)에게 넘길 용도로 JSONL을 내보내는
전용 스크립트라 다른 타입(news/webpage/policy/official/case)은 못 봄 — "지금까지 뭐가
얼마나 쌓였는지 전체를 한 번에 확인하고 싶다"는 요청엔 이 스크립트를 씀.

JSONL이 아니라 JSON 배열 하나로 내보내는 이유: pandas/파인튜닝 파이프라인에 흘려넣는 게
목적인 export_papers.py와 달리, 이건 사람이 열어서 훑어보거나(VSCode/브라우저) 다른 곳에
붙여넣는 "현재 상태 스냅샷" 용도라 배열 하나가 더 편함.

사용법 (secondpj 루트에서, venv 활성화 상태로):
    python -m rag.scripts.export_documents                        # 전체 documents
    python -m rag.scripts.export_documents --type case            # document_type='case'만
    python -m rag.scripts.export_documents --type news,official    # 여러 타입(콤마 구분)
    python -m rag.scripts.export_documents --category 음성복제      # category만
    python -m rag.scripts.export_documents --no-content            # content(본문 전체) 빼고
                                                                     # 메타데이터만 (파일 용량↓, 훑어보기 용도)
    python -m rag.scripts.export_documents --only-content          # 반대로 content(본문)만
                                                                     # — id/title 등 메타데이터 없이 본문
                                                                     # 문자열 배열만 (기본 JSON)
    python -m rag.scripts.export_documents --only-content --format txt
                                                                     # 위와 같되 문서 사이 구분선을 넣은
                                                                     # 텍스트 파일(.txt)로. 사람이 읽거나
                                                                     # 다른 곳에 그대로 붙여넣을 때 편함.
    python -m rag.scripts.export_documents --out my_export.json    # 출력 경로 직접 지정

출력: rag/exports/documents_YYYYMMDD_HHMMSS.json (--out 지정 안 하면. --only-content --format txt면
      확장자만 .txt로 바뀜).
필드(기본): id, title, content(--no-content 시 생략), document_type, category, url, author,
      published_at, language, source(=sources.name), chunk_count(청킹/임베딩된 chunk 개수 —
      0이면 아직 청킹 전이거나 임베딩 실패), created_at.
--only-content일 때는 위 필드 없이 content만 나옴(json=문자열 배열, txt=구분선으로 이어붙인
파일) — --no-content와 반대 방향 옵션이라 두 개를 같이 쓰면 에러로 막음(둘 다 켜면 아무것도
안 남으므로).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from rag import config

EXPORTS_DIR = Path(__file__).resolve().parent.parent / "exports"


def _json_default(value):
    # date/datetime은 기본 json.dump가 못 다루니 isoformat 문자열로 변환.
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="documents 테이블을 JSON 파일로 내보내기")
    parser.add_argument(
        "--type", dest="document_types", default=None,
        help="document_type 필터, 콤마로 여러 개 (예: news,case). 생략 시 전체.",
    )
    parser.add_argument(
        "--category", dest="category", default=None, choices=sorted(config.CATEGORIES) if config.CATEGORIES else None,
        help="category 필터. 생략 시 전체.",
    )
    parser.add_argument(
        "--no-content", dest="include_content", action="store_false",
        help="본문(content) 필드를 빼고 메타데이터만 내보냄 — 파일이 훨씬 가벼워짐.",
    )
    parser.add_argument(
        "--only-content", dest="only_content", action="store_true",
        help="반대로 본문(content)만 내보냄 — id/title 등 메타데이터 없이. --format으로 json/txt 선택.",
    )
    parser.add_argument(
        "--format", dest="out_format", choices=["json", "txt"], default="json",
        help="--only-content일 때 출력 형식. json(기본)=문자열 배열, txt=문서 사이 구분선을 넣은 텍스트 파일.",
    )
    parser.add_argument("--out", dest="out_path", default=None, help="출력 파일 경로 직접 지정")
    args = parser.parse_args()

    if args.only_content and not args.include_content:
        parser.error("--only-content와 --no-content를 같이 쓰면 아무것도 안 남습니다 — 하나만 쓰세요.")

    where_clauses: list[str] = []
    params: list = []

    if args.document_types:
        types = [t.strip() for t in args.document_types.split(",") if t.strip()]
        where_clauses.append("d.document_type = ANY(%s)")
        params.append(types)

    if args.category:
        where_clauses.append("d.category = %s")
        params.append(args.category)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    if args.only_content:
        # 메타데이터 없이 content만 — JOIN도 필요 없음(source_name/chunk_count는 메타데이터라
        # 이 모드에선 안 뽑음).
        with config.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT d.content
                    FROM documents d
                    {where_sql}
                    ORDER BY d.created_at DESC;
                    """,
                    params,
                )
                rows = cur.fetchall()

        if not rows:
            print("조건에 맞는 documents가 없습니다 (필터를 확인하거나, 아직 아무것도 수집 안 됐을 수 있음).")
            return

        contents = [row[0] for row in rows]

        if args.out_path:
            out_path = Path(args.out_path)
        else:
            EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = "txt" if args.out_format == "txt" else "json"
            out_path = EXPORTS_DIR / f"documents_content_{timestamp}.{ext}"

        out_path.parent.mkdir(parents=True, exist_ok=True)

        if args.out_format == "txt":
            # 문서 사이를 구분선으로 나눔 — 구분선이 실제 본문과 헷갈리지 않게 흔치 않은 문자열 사용.
            separator = "\n\n" + ("=" * 20) + " [문서 구분선] " + ("=" * 20) + "\n\n"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(separator.join(contents))
        else:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(contents, f, ensure_ascii=False, indent=2)

        print(f"{len(contents)}건의 content만 내보냄 -> {out_path}")
        return

    content_select = "d.content," if args.include_content else ""

    with config.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT d.id, d.title, {content_select} d.document_type, d.category, d.url,
                       d.author, d.published_at, d.language, s.name AS source_name,
                       (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count,
                       d.created_at
                FROM documents d
                JOIN sources s ON s.id = d.source_id
                {where_sql}
                ORDER BY d.created_at DESC;
                """,
                params,
            )
            rows = cur.fetchall()
            colnames = [desc[0] for desc in cur.description]

    if not rows:
        print("조건에 맞는 documents가 없습니다 (필터를 확인하거나, 아직 아무것도 수집 안 됐을 수 있음).")
        return

    records = [dict(zip(colnames, row)) for row in rows]
    # colnames의 "content"/"source_name" 등은 SELECT에 쓴 별칭 그대로라 그대로 JSON 키로 씀.

    if args.out_path:
        out_path = Path(args.out_path)
    else:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = EXPORTS_DIR / f"documents_{timestamp}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=_json_default)

    print(f"{len(records)}건 내보냄 -> {out_path}")

    # document_type별 개수도 같이 보여줌 — 지금까지 뭐가 얼마나 쌓였는지 한눈에 확인용.
    by_type: dict[str, int] = {}
    for r in records:
        by_type[r["document_type"]] = by_type.get(r["document_type"], 0) + 1
    for doc_type, count in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"  - {doc_type}: {count}건")


if __name__ == "__main__":
    main()
