"""
수집된 논문(document_type='paper')을 2번(모델/파인튜닝 담당)에게 공유하기 위한 내보내기 스크립트.

왜 DB 계정을 직접 공유하지 않고 파일로 내보내는가:
- 2번은 RAG용 chunks/embedding까지 필요 없고 title+abstract(+메타데이터)만 있으면 됨 —
  DB 스키마 전체(다른 담당자 테이블 포함)에 접근 권한을 줄 필요가 없음.
- JSONL은 pandas/HuggingFace datasets 등에서 바로 읽을 수 있어서 파인튜닝 파이프라인에 넣기 쉬움.
- 논문이 계속 쌓이는 구조(paper_collector.py, 성장형)라 이 스크립트를 그때그때 다시 돌려서
  최신 파일을 다시 넘겨주면 됨 — 매번 수동으로 DB를 뒤질 필요 없음.

출력: rag/exports/papers_YYYYMMDD_HHMMSS.jsonl — 한 줄에 논문 하나(JSON object).
필드: id(document_id, 나중에 RAG쪽 chunk/citation과 대조하고 싶을 때 대조키로 쓸 수 있음),
      title, abstract(=documents.content), content_type("abstract" | "full_text" — 아래 설명),
      url, author, category, published_at, language,
      source(발행처/플랫폼 — arXiv | Semantic Scholar | 로컬 PDF 업로드), created_at.

⚠️ content_type 구분 — abstract 필드 이름과 달리 실제로는 두 종류가 섞여 있음:
  - source가 "arXiv"/"Semantic Scholar"인 논문 -> 초록(abstract)만 수집됨(원문 API가
    그렇게 줌), content_type="abstract"
  - source가 "로컬 PDF 업로드"(rag/scripts/ingest_pdfs.py로 직접 넣은 논문) -> PDF
    전체 텍스트가 들어있음, content_type="full_text"
  파인튜닝 데이터로 쓸 때 이 구분을 무시하고 전부 "전체 본문"이라고 가정하면 안 됨.

실행 (secondpj 루트에서, 서버 DB 접속 가능한 PC에서):
    python -m rag.scripts.export_papers
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rag import config

EXPORTS_DIR = Path(__file__).resolve().parent.parent / "exports"


def main() -> None:
    with config.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.id, d.title, d.content, d.url, d.author, d.category,
                       d.published_at, d.language, s.name AS source_name, d.created_at
                FROM documents d
                JOIN sources s ON s.id = d.source_id
                WHERE d.document_type = 'paper'
                ORDER BY d.published_at DESC NULLS LAST, d.created_at DESC;
                """
            )
            rows = cur.fetchall()

    if not rows:
        print("document_type='paper' 문서가 아직 없습니다 — 먼저 paper_collector로 수집하세요.")
        return

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = EXPORTS_DIR / f"papers_{timestamp}.jsonl"

    # arXiv/Semantic Scholar는 API 자체가 초록만 주고, 로컬 PDF 업로드는 전체 텍스트가 들어있음 —
    # 이 차이를 모르고 전부 "전체 본문"이라고 가정하면 파인튜닝 데이터 품질에 영향을 줄 수 있어서
    # 명시적으로 필드를 나눔.
    _ABSTRACT_ONLY_SOURCES = {"arXiv", "Semantic Scholar"}

    with open(out_path, "w", encoding="utf-8") as f:
        for doc_id, title, doc_content, url, author, category, published_at, language, source_name, created_at in rows:
            content_type = "abstract" if source_name in _ABSTRACT_ONLY_SOURCES else "full_text"
            record = {
                "id": str(doc_id),
                "title": title,
                "abstract": doc_content,
                "content_type": content_type,
                "url": url,
                "author": author,
                "category": category,
                "published_at": published_at.isoformat() if published_at else None,
                "language": language,
                "source": source_name,
                "created_at": created_at.isoformat(),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 카테고리별 개수도 같이 보여줘서 공유 전에 분포를 바로 확인할 수 있게.
    by_category: dict[str, int] = {}
    for row in rows:
        by_category[row[5]] = by_category.get(row[5], 0) + 1

    print(f"논문 {len(rows)}건 내보냄 -> {out_path}")
    print("카테고리별 분포:")
    for category, count in sorted(by_category.items(), key=lambda x: -x[1]):
        print(f"  {category}: {count}건")


if __name__ == "__main__":
    main()
