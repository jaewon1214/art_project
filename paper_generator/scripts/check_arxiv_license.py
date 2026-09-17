from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

INPUT_METADATA = RAW_DIR / "collected_metadata.jsonl"
OUTPUT_JSONL = RAW_DIR / "collected_metadata_with_license.jsonl"
OUTPUT_CSV = RAW_DIR / "license_check_report.csv"

USER_AGENT = "art-paper-project/0.1 (student research project)"
SLEEP_SECONDS = 3

LICENSE_MAP = {
    "creativecommons.org/licenses/by/4.0": "CC BY 4.0",
    "creativecommons.org/licenses/by-sa/4.0": "CC BY-SA 4.0",
    "creativecommons.org/licenses/by-nc/4.0": "CC BY-NC 4.0",
    "creativecommons.org/licenses/by-nd/4.0": "CC BY-ND 4.0",
    "creativecommons.org/licenses/by-nc-sa/4.0": "CC BY-NC-SA 4.0",
    "creativecommons.org/licenses/by-nc-nd/4.0": "CC BY-NC-ND 4.0",
    "arxiv.org/licenses/nonexclusive-distrib/1.0": "arXiv non-exclusive distribution license",
}

SAFE_FOR_PROJECT = {
    "CC BY 4.0",
    "CC BY-SA 4.0",
}

CONDITIONAL_NONCOMMERCIAL = {
    "CC BY-NC 4.0",
    "CC BY-NC-SA 4.0",
}

REVIEW_OR_EXCLUDE = {
    "CC BY-ND 4.0",
    "CC BY-NC-ND 4.0",
    "arXiv non-exclusive distribution license",
}


def load_metadata():
    rows = []
    with INPUT_METADATA.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def normalize_arxiv_id(arxiv_id: str) -> str:
    return arxiv_id.split("v")[0]


def classify_license(url: str | None):
    if not url:
        return "UNKNOWN", "REVIEW"

    normalized = url.lower().rstrip("/")

    for key, label in LICENSE_MAP.items():
        if key in normalized:
            if label in SAFE_FOR_PROJECT:
                return label, "KEEP"
            if label in CONDITIONAL_NONCOMMERCIAL:
                return label, "KEEP_NONCOMMERCIAL_ONLY"
            if label in REVIEW_OR_EXCLUDE:
                return label, "REVIEW"
            return label, "REVIEW"

    return url, "REVIEW"


def find_license_from_abs_page(arxiv_id: str):
    base_id = normalize_arxiv_id(arxiv_id)
    url = f"https://arxiv.org/abs/{base_id}"

    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # 1) Prefer explicit anchors to Creative Commons or arXiv license pages.
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        text = " ".join(a.stripped_strings).lower()

        if "creativecommons.org/licenses/" in low:
            candidates.append(href)
        elif "arxiv.org/licenses/" in low:
            candidates.append(href)
        elif "license" in text and ("creativecommons" in low or "arxiv.org/licenses/" in low):
            candidates.append(href)

    # 2) Fallback regex over raw HTML.
    if not candidates:
        html = response.text
        patterns = [
            r'https?://creativecommons\.org/licenses/[a-z\-]+/[0-9.]+/?',
            r'https?://arxiv\.org/licenses/nonexclusive-distrib/[0-9.]+/?',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                candidates.append(m.group(0))
                break

    if not candidates:
        return None, url

    # De-duplicate while preserving order.
    uniq = []
    seen = set()
    for x in candidates:
        if x not in seen:
            seen.add(x)
            uniq.append(x)

    return uniq[0], url


def main():
    if not INPUT_METADATA.exists():
        raise FileNotFoundError(f"Input not found: {INPUT_METADATA}")

    rows = load_metadata()
    out_rows = []
    report_rows = []

    print(f"Input papers: {len(rows)}")

    for i, item in enumerate(rows, start=1):
        arxiv_id = item.get("arxiv_id")
        if not arxiv_id:
            continue

        try:
            license_url, abs_url = find_license_from_abs_page(arxiv_id)
            license_name, decision = classify_license(license_url)

            item["license_url"] = license_url
            item["license_name"] = license_name
            item["license_decision"] = decision
            item["license_checked_from"] = abs_url

            report_rows.append(
                {
                    "arxiv_id": arxiv_id,
                    "title": item.get("title", ""),
                    "category": item.get("category", ""),
                    "license_name": license_name,
                    "license_url": license_url or "",
                    "license_decision": decision,
                    "abs_url": abs_url,
                }
            )

            print(
                f"[{i}/{len(rows)}] {arxiv_id} -> "
                f"{license_name} / {decision}"
            )

        except Exception as exc:
            item["license_name"] = "CHECK_ERROR"
            item["license_decision"] = "REVIEW"
            item["license_check_error"] = str(exc)

            report_rows.append(
                {
                    "arxiv_id": arxiv_id,
                    "title": item.get("title", ""),
                    "category": item.get("category", ""),
                    "license_name": "CHECK_ERROR",
                    "license_url": "",
                    "license_decision": "REVIEW",
                    "abs_url": f"https://arxiv.org/abs/{normalize_arxiv_id(arxiv_id)}",
                }
            )

            print(f"[{i}/{len(rows)}] {arxiv_id} -> ERROR: {exc}")

        out_rows.append(item)
        time.sleep(SLEEP_SECONDS)

    with OUTPUT_JSONL.open("w", encoding="utf-8") as f:
        for item in out_rows:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "arxiv_id",
                "title",
                "category",
                "license_name",
                "license_url",
                "license_decision",
                "abs_url",
            ],
        )
        writer.writeheader()
        writer.writerows(report_rows)

    counts = {}
    for row in report_rows:
        key = row["license_decision"]
        counts[key] = counts.get(key, 0) + 1

    print("\nDone.")
    print("Decision counts:", counts)
    print("Updated metadata:", OUTPUT_JSONL)
    print("Report:", OUTPUT_CSV)


if __name__ == "__main__":
    main()
