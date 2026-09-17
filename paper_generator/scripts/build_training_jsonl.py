from __future__ import annotations

import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PAPERS_DIR = ROOT / "data" / "processed" / "papers_json"
OUT_DIR = ROOT / "data" / "processed" / "training"

RANDOM_SEED = 42
VAL_RATIO = 0.15

# 너무 짧은 section 제외 기준
MIN_INTRO = 250
MIN_BODY = 800
MIN_CONCLUSION = 180

# 긴 본론은 내용을 버리지 않고 여러 샘플로 분할
BODY_CHUNK_CHARS = 3000
BODY_OVERLAP_CHARS = 250

# 현재 학교 프로젝트 기준에서 허용할 라이선스 판정
ALLOWED_LICENSE_DECISIONS = {
    "KEEP",
    "KEEP_NONCOMMERCIAL_ONLY",
    None,   # 과거 JSON 호환용
    "",
}


def clean_text(text: str) -> str:
    text = text or ""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_papers() -> list[dict]:
    papers = []

    for path in sorted(PAPERS_DIR.glob("*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            obj["_source_file"] = path.name
            papers.append(obj)
        except Exception as e:
            print(f"[JSON ERROR] {path.name}: {e}")

    return papers


def split_body(text: str) -> list[str]:
    text = clean_text(text)

    if len(text) <= BODY_CHUNK_CHARS:
        return [text] if text else []

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + BODY_CHUNK_CHARS, len(text))
        piece = text[start:end]

        if end < len(text):
            candidates = [
                piece.rfind("\n\n"),
                piece.rfind(". "),
                piece.rfind(".\n"),
                piece.rfind("다. "),
            ]
            cut = max(candidates)

            if cut >= int(BODY_CHUNK_CHARS * 0.65):
                end = start + cut + 1
                piece = text[start:end]

        piece = piece.strip()

        if piece:
            chunks.append(piece)

        if end >= len(text):
            break

        start = max(0, end - BODY_OVERLAP_CHARS)

    return chunks


def make_samples(paper: dict) -> list[dict]:
    title = clean_text(paper.get("title"))
    abstract = clean_text(paper.get("abstract"))
    intro = clean_text(paper.get("introduction"))
    body = clean_text(paper.get("body"))
    conclusion = clean_text(paper.get("conclusion"))

    meta = paper.get("metadata", {})
    paper_id = paper.get("id") or paper.get("arxiv_id") or title

    samples = []

    # title
    if title:
        samples.append({
            "instruction": "주어진 연구 주제에 맞는 학술 논문 제목을 작성하시오.",
            "input": title,
            "output": title,
            "section": "title",
            "paper_id": paper_id,
            "metadata": meta,
        })

    # abstract
    if len(abstract) >= 80:
        samples.append({
            "instruction": "주어진 연구 주제를 바탕으로 학술 논문의 초록을 작성하시오.",
            "input": title,
            "output": abstract,
            "section": "abstract",
            "paper_id": paper_id,
            "metadata": meta,
        })

    # introduction
    if len(intro) >= MIN_INTRO:
        samples.append({
            "instruction": (
                "주어진 연구 주제를 바탕으로 학술 논문의 서론을 작성하시오. "
                "연구 배경, 문제 제기, 연구 필요성이 자연스럽게 이어지도록 작성하시오."
            ),
            "input": title,
            "output": intro,
            "section": "introduction",
            "paper_id": paper_id,
            "metadata": meta,
        })

    # body
    if len(body) >= MIN_BODY:
        body_parts = split_body(body)

        for idx, part in enumerate(body_parts, start=1):
            samples.append({
                "instruction": (
                    "주어진 연구 주제를 바탕으로 학술 논문의 본론을 작성하시오. "
                    "핵심 논점과 근거를 논리적인 순서로 전개하시오."
                    if idx == 1 else
                    "주어진 연구 주제의 학술 논문 본론을 이어서 작성하시오."
                ),
                "input": title,
                "output": part,
                "section": f"body_{idx}",
                "paper_id": paper_id,
                "metadata": {
                    **meta,
                    "body_part": idx,
                    "body_parts_total": len(body_parts),
                },
            })

    # conclusion
    if len(conclusion) >= MIN_CONCLUSION:
        samples.append({
            "instruction": (
                "주어진 연구 주제를 바탕으로 학술 논문의 결론을 작성하시오. "
                "핵심 논의를 정리하고 연구의 의미와 시사점을 제시하시오."
            ),
            "input": title,
            "output": conclusion,
            "section": "conclusion",
            "paper_id": paper_id,
            "metadata": meta,
        })

    return samples


def split_by_paper(samples: list[dict]) -> tuple[list[dict], list[dict]]:
    grouped: dict[str, list[dict]] = {}

    for sample in samples:
        grouped.setdefault(sample["paper_id"], []).append(sample)

    paper_ids = list(grouped.keys())
    random.Random(RANDOM_SEED).shuffle(paper_ids)

    if len(paper_ids) <= 2:
        return samples, []

    val_count = max(1, round(len(paper_ids) * VAL_RATIO))
    val_ids = set(paper_ids[:val_count])

    train = []
    validation = []

    for paper_id, rows in grouped.items():
        if paper_id in val_ids:
            validation.extend(rows)
        else:
            train.extend(rows)

    return train, validation


def write_jsonl(path: Path, rows: list[dict]):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    papers = load_papers()

    # 1차: exact section만
    stage1_papers = [
        p for p in papers
        if p.get("metadata", {}).get("section_status") == "exact"
        and p.get("metadata", {}).get("license_decision") in ALLOWED_LICENSE_DECISIONS
    ]

    # 2차: exact + partial 중 실제 section 값이 들어있는 것까지
    stage2_papers = [
        p for p in papers
        if p.get("metadata", {}).get("section_status") in {"exact", "partial"}
        and p.get("metadata", {}).get("license_decision") in ALLOWED_LICENSE_DECISIONS
    ]

    def build(name: str, selected_papers: list[dict]):
        samples = []

        for paper in selected_papers:
            samples.extend(make_samples(paper))

        train, validation = split_by_paper(samples)

        target = OUT_DIR / name
        target.mkdir(parents=True, exist_ok=True)

        write_jsonl(target / "all_samples.jsonl", samples)
        write_jsonl(target / "train.jsonl", train)
        write_jsonl(target / "validation.jsonl", validation)

        summary = {
            "paper_count": len(selected_papers),
            "sample_count": len(samples),
            "train_sample_count": len(train),
            "validation_sample_count": len(validation),
            "section_counts": {},
        }

        for sample in samples:
            section = sample["section"].split("_")[0]
            summary["section_counts"][section] = (
                summary["section_counts"].get(section, 0) + 1
            )

        (target / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"\n[{name}]")
        print("논문 수:", len(selected_papers))
        print("전체 sample:", len(samples))
        print("Train:", len(train))
        print("Validation:", len(validation))
        print("Section:", summary["section_counts"])

    print("=" * 60)
    print("papers_json -> 학습 JSONL 변환")
    print("=" * 60)
    print("전체 JSON 논문:", len(papers))

    build("stage1_exact", stage1_papers)
    build("stage2_expanded", stage2_papers)

    print("\n완료")
    print("출력:", OUT_DIR)


if __name__ == "__main__":
    main()
