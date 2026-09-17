from __future__ import annotations

import json
import re
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = ROOT / "data" / "raw"
PDF_DIR = RAW_DIR / "pdfs"

META_WITH_LICENSE = RAW_DIR / "collected_metadata_with_license.jsonl"
META_FALLBACK = RAW_DIR / "collected_metadata.jsonl"

OUT_DIR = ROOT / "data" / "processed" / "papers_json"
SUMMARY_PATH = ROOT / "data" / "processed" / "papers_json_summary.json"

ABSTRACT_PATTERNS = [
    r"^\s*(?:abstract|초록|요약)\s*$",
]

INTRO_PATTERNS = [
    r"^\s*(?:\d+(?:\.\d+)*)?[\.\)\s\-:]*(?:introduction|서론)\s*$",
    r"^\s*(?:i|I)\.?\s+(?:introduction)\s*$",
    r"^\s*1[\.\)\s\-:]+(?:introduction|서론)\s*$",
]

CONCLUSION_PATTERNS = [
    r"^\s*(?:\d+(?:\.\d+)*)?[\.\)\s\-:]*(?:conclusion|conclusions|결론)\s*$",
    r"^\s*(?:concluding remarks)\s*$",
    r"^\s*(?:discussion and conclusion)\s*$",
    r"^\s*(?:conclusion and discussion)\s*$",
    r"^\s*(?:summary and conclusion)\s*$",
    r"^\s*(?:summary and conclusions)\s*$",
]

REFERENCE_PATTERNS = [
    r"^\s*(?:references|bibliography|참고문헌)\s*$",
]

GENERIC_HEADING = re.compile(
    r"(?im)^\s*(?:"
    r"(?:\d+(?:\.\d+)*)[\.\)\s\-:]+[A-Z가-힣][^\n]{1,110}"
    r"|(?:[IVXLC]+)\.?\s+[A-Z][^\n]{1,110}"
    r")\s*$"
)


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # PDF 줄바꿈 하이픈 연결
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def load_jsonl(path: Path) -> list[dict]:
    rows = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    return rows


def find_heading(text: str, patterns: list[str]):
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.M)
        if match:
            return match
    return None


def next_heading_after(text: str, pos: int):
    match = GENERIC_HEADING.search(text, pos)
    return match.start() if match else None


def strip_references(text: str) -> str:
    for pattern in REFERENCE_PATTERNS:
        matches = list(re.finditer(pattern, text, re.I | re.M))

        if matches:
            match = matches[-1]

            # 뒤쪽의 참고문헌만 제거
            if match.start() > len(text) * 0.45:
                return text[:match.start()].strip()

    return text


def extract_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    pages = []

    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")

    return clean_text("\n".join(pages))


def locate_pdf(arxiv_id: str) -> Path | None:
    base_id = arxiv_id.split("v")[0]

    candidates = [
        PDF_DIR / f"{arxiv_id.replace('/', '_')}.pdf",
        PDF_DIR / f"{base_id.replace('/', '_')}.pdf",
    ]

    for path in candidates:
        if path.exists():
            return path

    prefix = base_id.replace("/", "_")

    for path in PDF_DIR.glob("*.pdf"):
        if path.stem.startswith(prefix):
            return path

    return None


def extract_abstract(text: str, metadata_abstract: str = "") -> str:
    heading = find_heading(text, ABSTRACT_PATTERNS)

    if heading:
        start = heading.end()
        end = next_heading_after(text, start)

        if end is None:
            end = min(len(text), start + 3500)

        value = text[start:end].strip()

        if len(value) >= 80:
            return value

    # PDF에서 못 찾으면 API 초록 사용
    return clean_text(metadata_abstract)


def extract_sections(text: str) -> tuple[str, str, str, str]:
    """
    반환:
    introduction, body, conclusion, section_status

    section_status:
    - exact
    - partial
    - unparsed
    """
    no_refs = strip_references(text)

    intro_h = find_heading(no_refs, INTRO_PATTERNS)
    conc_h = find_heading(no_refs, CONCLUSION_PATTERNS)

    if intro_h and conc_h:
        intro_start = intro_h.end()
        intro_end = next_heading_after(no_refs, intro_start)

        if intro_end is None or intro_end >= conc_h.start():
            intro_end = min(
                conc_h.start(),
                intro_start + max(2500, int(len(no_refs) * 0.15)),
            )

        conc_start = conc_h.end()
        conc_end = next_heading_after(no_refs, conc_start) or len(no_refs)

        introduction = no_refs[intro_start:intro_end].strip()
        body = no_refs[intro_end:conc_h.start()].strip()
        conclusion = no_refs[conc_start:conc_end].strip()

        return introduction, body, conclusion, "exact"

    # 일부만 찾은 경우도 원문은 보존
    if intro_h or conc_h:
        return "", "", "", "partial"

    return "", "", "", "unparsed"


def safe_filename(arxiv_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", arxiv_id)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    meta_path = META_WITH_LICENSE if META_WITH_LICENSE.exists() else META_FALLBACK

    if not meta_path.exists():
        raise FileNotFoundError(
            "collected_metadata_with_license.jsonl 또는 "
            "collected_metadata.jsonl 파일이 data/raw/에 없습니다."
        )

    rows = load_jsonl(meta_path)

    summary = {
        "metadata_file": str(meta_path.relative_to(ROOT)),
        "total_metadata": len(rows),
        "json_created": 0,
        "pdf_not_found": 0,
        "section_exact": 0,
        "section_partial": 0,
        "section_unparsed": 0,
        "categories": {},
        "licenses": {},
    }

    for index, meta in enumerate(rows, start=1):
        arxiv_id = str(meta.get("arxiv_id") or "").strip()

        if not arxiv_id:
            continue

        pdf_path = locate_pdf(arxiv_id)

        if not pdf_path:
            summary["pdf_not_found"] += 1
            print(f"[{index}/{len(rows)}] PDF 없음: {arxiv_id}")
            continue

        try:
            full_text = extract_pdf_text(pdf_path)

            abstract = extract_abstract(
                full_text,
                metadata_abstract=meta.get("abstract", ""),
            )

            introduction, body, conclusion, section_status = extract_sections(
                full_text
            )

            category = meta.get("category") or "unknown"
            license_name = (
                meta.get("license_name")
                or meta.get("license_url")
                or "UNKNOWN"
            )

            record = {
                "id": f"arxiv_{arxiv_id}",
                "arxiv_id": arxiv_id,

                "title": meta.get("title", ""),
                "topic": meta.get("title", ""),

                "abstract": abstract,
                "introduction": introduction,
                "body": body,
                "conclusion": conclusion,

                # 어떤 section 추출법을 쓰더라도 원문 전체는 항상 보존
                "full_text": full_text,

                "metadata": {
                    "authors": meta.get("authors", []),
                    "published_at": meta.get("published_at"),
                    "updated_at": meta.get("updated_at"),

                    "category": category,
                    "language": meta.get("language", "en"),

                    "source": meta.get("source", "arxiv"),
                    "source_url": meta.get("source_url"),
                    "pdf_url": meta.get("pdf_url"),

                    "license_name": meta.get("license_name"),
                    "license_url": meta.get("license_url"),
                    "license_decision": meta.get("license_decision"),
                    "license_status": meta.get("license_status"),

                    "local_pdf": str(pdf_path.relative_to(ROOT)),
                    "section_status": section_status,
                },
            }

            output_path = OUT_DIR / f"{safe_filename(arxiv_id)}.json"

            with output_path.open("w", encoding="utf-8") as f:
                json.dump(
                    record,
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

            summary["json_created"] += 1
            summary[f"section_{section_status}"] += 1

            summary["categories"][category] = (
                summary["categories"].get(category, 0) + 1
            )

            summary["licenses"][license_name] = (
                summary["licenses"].get(license_name, 0) + 1
            )

            print(
                f"[{index}/{len(rows)}] 저장 "
                f"{arxiv_id} | {category} | section={section_status}"
            )

        except Exception as exc:
            print(f"[{index}/{len(rows)}] ERROR {arxiv_id}: {exc}")

    with SUMMARY_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            summary,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print("=" * 60)
    print("완료")
    print("=" * 60)
    print("메타데이터:", summary["total_metadata"])
    print("JSON 생성:", summary["json_created"])
    print("PDF 없음:", summary["pdf_not_found"])
    print("section exact:", summary["section_exact"])
    print("section partial:", summary["section_partial"])
    print("section unparsed:", summary["section_unparsed"])
    print()
    print("JSON 폴더:", OUT_DIR)
    print("요약:", SUMMARY_PATH)


if __name__ == "__main__":
    main()
