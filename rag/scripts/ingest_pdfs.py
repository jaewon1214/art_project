"""
논문 PDF 수집 — API로 못 받은 논문은 직접 다운로드해서 data/<쟁점>/*.pdf 로 넣어두고 이 스크립트를
돌리면 텍스트 추출 -> pipeline.ingest.ingest_document()로 청크 생성/임베딩/엔티티 추출/Neo4j 적재까지
자동으로 끝남 (뉴스/정책과 동일한 파이프라인을 그대로 탐).

폴더 구조 (rag/data/ 아래, 폴더명이 곧 category — 반드시 4개 중 하나):
    data/
      저작권/논문1.pdf
      창작자성/논문2.pdf
      음성복제/...
      AI작곡/...

사용법 (secondpj 루트에서 — rag/ 안에서 돌리면 "from rag..." 절대 임포트가 깨짐):
    python -m rag.scripts.ingest_pdfs

이미 넣은 PDF를 다시 돌려도 content_hash로 중복 걸러져서 안전(재실행 가능).
LLM_PROVIDER가 설정돼 있으면 "꼭 관련된 내용으로만 수집" 요건대로 주제와 무관한 PDF는
저장하지 않고 건너뜀(폴더를 잘못 넣었어도 안전장치가 됨).
"""
from __future__ import annotations

import re
from pathlib import Path

from rag.pipeline.ingest import ingest_document
from rag.preprocessing.normalize_metadata import ALLOWED_CATEGORIES

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SOURCE_NAME = "로컬 PDF 업로드"


def _extract_text(pdf_path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def _guess_language(text: str) -> str:
    """한글이 섞여 있으면 ko, 아니면 en — 국내외 논문 섞어서 넣을 때를 위한 아주 단순한 판별."""
    return "ko" if re.search(r"[가-힣]", text[:2000]) else "en"


def build_raw_doc(pdf_path: Path, category: str) -> dict:
    content = _extract_text(pdf_path)
    return {
        "title": pdf_path.stem,
        "content": content,
        "url": None,  # 로컬 파일이라 URL 없음 (documents.url은 UNIQUE지만 NULL은 여러 개 허용됨)
        "author": None,
        "category": category,
        "document_type": "paper",
        "published_at": None,
        "language": _guess_language(content),
        "source_name": SOURCE_NAME,
    }


def main() -> None:
    if not DATA_DIR.exists():
        print(f"{DATA_DIR} 폴더가 없습니다 — data/<쟁점>/ 형태로 만들고 PDF를 넣어주세요.")
        print(f"쟁점 폴더명은 다음 중 하나여야 함: {sorted(ALLOWED_CATEGORIES)}")
        return

    stats = {"found": 0, "inserted": 0, "duplicate": 0, "irrelevant": 0, "failed": 0}

    for category_dir in sorted(DATA_DIR.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        if category not in ALLOWED_CATEGORIES:
            print(f"[건너뜀] '{category}'는 허용된 category가 아님 (허용값: {sorted(ALLOWED_CATEGORIES)})")
            continue

        for pdf_path in sorted(category_dir.glob("*.pdf")):
            stats["found"] += 1
            try:
                raw_doc = build_raw_doc(pdf_path, category)
                if not raw_doc["content"]:
                    print(f"[실패] {pdf_path.name}: 텍스트 추출 결과가 비어있음(스캔본 PDF는 OCR 필요)")
                    stats["failed"] += 1
                    continue

                result = ingest_document(raw_doc)
            except Exception as e:  # noqa: BLE001
                print(f"[실패] {pdf_path.name}: {e}")
                stats["failed"] += 1
                continue

            status = result["status"]
            if status == "inserted":
                stats["inserted"] += 1
                print(f"[저장] {category}/{pdf_path.name}")
            elif status == "duplicate":
                stats["duplicate"] += 1
                print(f"[중복] {category}/{pdf_path.name}")
            elif status == "irrelevant":
                stats["irrelevant"] += 1
                print(f"[주제무관] {category}/{pdf_path.name}: {result.get('reason')}")

    print(
        f"\n총 {stats['found']}개 PDF 처리 — 신규 저장 {stats['inserted']}건, "
        f"중복 스킵 {stats['duplicate']}건, 주제무관 스킵 {stats['irrelevant']}건, "
        f"실패 {stats['failed']}건"
    )


if __name__ == "__main__":
    main()
