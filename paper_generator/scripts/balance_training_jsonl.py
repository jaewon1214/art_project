from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

# ============================================================
# 경로
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "data" / "processed" / "training" / "stage1_exact"

TRAIN_IN = DATA_DIR / "train.jsonl"
VAL_IN = DATA_DIR / "validation.jsonl"

TRAIN_OUT = DATA_DIR / "train_balanced.jsonl"
VAL_OUT = DATA_DIR / "validation_balanced.jsonl"

SUMMARY_OUT = DATA_DIR / "balanced_summary.json"

# ============================================================
# 설정
# ============================================================

# 논문 1편당 사용할 body 샘플 최대 개수
MAX_BODY_PER_PAPER = 5

# title / abstract / introduction / conclusion은 전부 유지
ALWAYS_KEEP_PREFIXES = {
    "title",
    "abstract",
    "introduction",
    "conclusion",
}


def load_jsonl(path: Path) -> list[dict]:
    rows = []

    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"[JSON ERROR] {path.name}:{line_no} -> {exc}")

    return rows


def write_jsonl(path: Path, rows: list[dict]):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def get_section(sample: dict) -> str:
    return str(sample.get("section", "")).strip()


def get_paper_id(sample: dict) -> str:
    return str(
        sample.get("paper_id")
        or sample.get("metadata", {}).get("arxiv_id")
        or sample.get("input")
        or "unknown"
    )


def evenly_select(items: list[dict], max_count: int) -> list[dict]:
    """
    body가 너무 많을 때 앞부분만 남기지 않고
    논문 전체 흐름에서 최대 max_count개를 고르게 선택.
    """
    if len(items) <= max_count:
        return items

    if max_count == 1:
        return [items[len(items) // 2]]

    positions = [
        round(i * (len(items) - 1) / (max_count - 1))
        for i in range(max_count)
    ]

    return [items[pos] for pos in positions]


def body_index(sample: dict) -> int:
    section = get_section(sample)

    if not section.startswith("body"):
        return 0

    try:
        return int(section.split("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def balance_dataset(rows: list[dict]) -> tuple[list[dict], dict]:
    by_paper = defaultdict(list)

    for row in rows:
        by_paper[get_paper_id(row)].append(row)

    balanced = []
    paper_stats = {}

    for paper_id, samples in by_paper.items():
        keep = []
        bodies = []

        for sample in samples:
            section = get_section(sample)

            if section.startswith("body"):
                bodies.append(sample)

            elif section in ALWAYS_KEEP_PREFIXES:
                keep.append(sample)

            else:
                # 알 수 없는 section은 버리지 않고 유지
                keep.append(sample)

        bodies.sort(key=body_index)

        selected_bodies = evenly_select(
            bodies,
            MAX_BODY_PER_PAPER,
        )

        combined = keep + selected_bodies

        # 보기 좋게 section 순서 정렬
        order = {
            "title": 0,
            "abstract": 1,
            "introduction": 2,
            "conclusion": 9999,
        }

        def sort_key(sample: dict):
            section = get_section(sample)

            if section.startswith("body"):
                return 100 + body_index(sample)

            return order.get(section, 5000)

        combined.sort(key=sort_key)
        balanced.extend(combined)

        paper_stats[paper_id] = {
            "before": len(samples),
            "body_before": len(bodies),
            "body_after": len(selected_bodies),
            "after": len(combined),
        }

    return balanced, paper_stats


def section_counts(rows: list[dict]) -> dict:
    counts = Counter()

    for row in rows:
        section = get_section(row)

        if section.startswith("body"):
            counts["body"] += 1
        else:
            counts[section or "unknown"] += 1

    return dict(counts)


def main():
    if not TRAIN_IN.exists():
        raise FileNotFoundError(f"파일 없음: {TRAIN_IN}")

    if not VAL_IN.exists():
        raise FileNotFoundError(f"파일 없음: {VAL_IN}")

    train = load_jsonl(TRAIN_IN)
    val = load_jsonl(VAL_IN)

    train_balanced, train_papers = balance_dataset(train)
    val_balanced, val_papers = balance_dataset(val)

    write_jsonl(TRAIN_OUT, train_balanced)
    write_jsonl(VAL_OUT, val_balanced)

    summary = {
        "max_body_per_paper": MAX_BODY_PER_PAPER,
        "train": {
            "before_samples": len(train),
            "after_samples": len(train_balanced),
            "paper_count": len(train_papers),
            "before_sections": section_counts(train),
            "after_sections": section_counts(train_balanced),
        },
        "validation": {
            "before_samples": len(val),
            "after_samples": len(val_balanced),
            "paper_count": len(val_papers),
            "before_sections": section_counts(val),
            "after_sections": section_counts(val_balanced),
        },
    }

    SUMMARY_OUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=" * 60)
    print("학습 데이터 균형 조정 완료")
    print("=" * 60)

    print("\n[TRAIN]")
    print("기존 sample:", len(train))
    print("균형 sample:", len(train_balanced))
    print("논문 수:", len(train_papers))
    print("기존 section:", section_counts(train))
    print("균형 section:", section_counts(train_balanced))

    print("\n[VALIDATION]")
    print("기존 sample:", len(val))
    print("균형 sample:", len(val_balanced))
    print("논문 수:", len(val_papers))
    print("기존 section:", section_counts(val))
    print("균형 section:", section_counts(val_balanced))

    print("\n생성 파일:")
    print(TRAIN_OUT)
    print(VAL_OUT)
    print(SUMMARY_OUT)


if __name__ == "__main__":
    main()
