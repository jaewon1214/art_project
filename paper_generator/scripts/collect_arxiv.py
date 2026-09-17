from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

import requests

API_URL = "https://export.arxiv.org/api/query"
USER_AGENT = "art-paper-project/0.1 (student research project)"

QUERIES = {
    "copyright": [
        '"AI music" copyright',
        '"generative AI music" copyright',
        '"music generation" copyright',
        '"AI-generated music" copyright',
    ],
    "authorship": [
        '"AI music" authorship',
        '"generative music" authorship',
        '"AI-generated music" creator',
        '"AI music" creative agency',
    ],
    "voice_cloning": [
        '"voice cloning" music',
        '"synthetic voice" copyright',
        '"singing voice synthesis" AI',
        '"AI-generated vocals"',
    ],
    "music_generation": [
        '"AI music generation"',
        '"generative music" transformer',
        '"AI composition" music',
        '"text-to-music" generation',
    ],
}

MAX_RESULTS_PER_QUERY = 25
SLEEP_SECONDS = 3

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PDF_DIR = RAW_DIR / "pdfs"
META_PATH = RAW_DIR / "collected_metadata.jsonl"

ATOM = {"a": "http://www.w3.org/2005/Atom"}
ARXIV = {"arxiv": "http://arxiv.org/schemas/atom"}


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def arxiv_id_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def existing_ids() -> set[str]:
    ids: set[str] = set()
    if not META_PATH.exists():
        return ids
    for line in META_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            ids.add(json.loads(line)["arxiv_id"])
        except Exception:
            pass
    return ids


def search_arxiv(query: str, max_results: int):
    params = (
        f"?search_query=all:{quote(query)}"
        f"&start=0&max_results={max_results}"
        f"&sortBy=submittedDate&sortOrder=descending"
    )
    response = requests.get(
        API_URL + params,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()

    root = ET.fromstring(response.text)
    results = []

    for entry in root.findall("a:entry", ATOM):
        abs_url = clean(entry.findtext("a:id", namespaces=ATOM))
        arxiv_id = arxiv_id_from_url(abs_url)

        authors = [
            clean(author.findtext("a:name", namespaces=ATOM))
            for author in entry.findall("a:author", ATOM)
        ]

        pdf_url = None
        for link in entry.findall("a:link", ATOM):
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href")
                break
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"

        # arXiv feeds may expose a license element. If absent, keep null:
        # do NOT infer that arXiv hosting means an open training license.
        license_el = entry.find("arxiv:license", ARXIV)
        license_url = None
        if license_el is not None:
            license_url = (
                license_el.attrib.get("href")
                or clean(license_el.text)
                or None
            )

        results.append(
            {
                "arxiv_id": arxiv_id,
                "title": clean(entry.findtext("a:title", namespaces=ATOM)),
                "abstract": clean(entry.findtext("a:summary", namespaces=ATOM)),
                "authors": authors,
                "published_at": clean(entry.findtext("a:published", namespaces=ATOM)),
                "updated_at": clean(entry.findtext("a:updated", namespaces=ATOM)),
                "source_url": abs_url,
                "pdf_url": pdf_url,
                "license_url": license_url,
            }
        )

    return results


def download_pdf(item: dict) -> str | None:
    path = PDF_DIR / f"{item['arxiv_id'].replace('/', '_')}.pdf"
    if path.exists():
        return str(path.relative_to(ROOT))

    try:
        response = requests.get(
            item["pdf_url"],
            headers={"User-Agent": USER_AGENT},
            timeout=60,
        )
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            print(f"[SKIP PDF] {item['arxiv_id']}: PDF response not detected")
            return None
        path.write_bytes(response.content)
        return str(path.relative_to(ROOT))
    except Exception as exc:
        print(f"[PDF ERROR] {item['arxiv_id']}: {exc}")
        return None


def main():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    seen = existing_ids()

    total_new = 0

    with META_PATH.open("a", encoding="utf-8") as meta_file:
        for category, queries in QUERIES.items():
            for query in queries:
                print(f"\n[{category}] {query}")

                try:
                    results = search_arxiv(query, MAX_RESULTS_PER_QUERY)
                except Exception as exc:
                    print(f"[SEARCH ERROR] {exc}")
                    time.sleep(SLEEP_SECONDS)
                    continue

                for item in results:
                    if item["arxiv_id"] in seen:
                        continue

                    item["category"] = category
                    item["language"] = "en"
                    item["source"] = "arxiv"
                    item["license_status"] = (
                        "CHECKED_FROM_FEED" if item["license_url"] else "REVIEW_REQUIRED"
                    )
                    item["local_pdf"] = download_pdf(item)

                    meta_file.write(json.dumps(item, ensure_ascii=False) + "\n")
                    meta_file.flush()

                    seen.add(item["arxiv_id"])
                    total_new += 1
                    print(
                        f"[NEW] {item['arxiv_id']} | "
                        f"license={item['license_url'] or 'REVIEW_REQUIRED'}"
                    )

                # Be polite to the public API.
                time.sleep(SLEEP_SECONDS)

    print(f"\nDone. New papers: {total_new}")
    print(f"Metadata: {META_PATH}")
    print(f"PDFs: {PDF_DIR}")


if __name__ == "__main__":
    main()
