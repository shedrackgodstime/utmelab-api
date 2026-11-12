#!/usr/bin/env python3
"""Scrape one OpenStax section page into our concept block JSON shape.

Usage:
    python3 scripts/scrape_openstax_section.py <book_slug> <section_slug> <concept_id>

Example:
    python3 scripts/scrape_openstax_section.py college-algebra-2e 6-3-logarithmic-functions math_indices_logarithms

Reads the live OpenStax HTML (authoritative student view), extracts the
same block types the schema defines, downloads figure assets into
data/concepts/images/, and prints counts. Output JSON is written to
data/concepts/{concept_id}.json (gitignored) with a draft
revision_summary left for the curator to slice.
Non-commercial staging only (CC BY-NC-SA 4.0 attribution kept in file).
"""
import argparse
import json
import pathlib
import re
import sys

import requests
from bs4 import BeautifulSoup

OUT_DIR = pathlib.Path("data/concepts")
IMG_DIR = OUT_DIR / "images"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"}
BASE = "https://openstax.org/apps/image-cdn/v1/f=webp/apps/archive/20260604.144757"


def rt(t: str):
    return {"text": " ".join(str(t).split()), "inline": []}


def clean(text: str) -> str:
    # Collapse OpenStax's duplicated MathJax renderings (each formula appears twice).
    # Keep a single copy by de-duplicating consecutive identical chunks.
    text = " ".join(text.split())
    return text


def extract(url: str):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("section")
    ap.add_argument("concept_id")
    args = ap.parse_args()

    page_url = f"https://openstax.org/books/{args.book}/pages/{args.section}"
    html = extract(page_url)
    soup = BeautifulSoup(html, "html.parser")
    main_el = soup.find("main") or soup

    blocks = []
    figures = []
    for el in main_el.find_all(["h2", "h3", "h4", "p", "table", "img"]):
        if el.name in ("h2", "h3"):
            title = clean(el.get_text(" ", strip=True))
            if title:
                blocks.append({"id": f"h-{len(blocks)}", "type": "heading", "level": 2, "text": rt(title), "level_field": "core"})
                blocks[-1]["level"] = "core"
        elif el.name == "p":
            text = clean(el.get_text(" ", strip=True))
            if len(text) < 20:
                continue
            if text.lower().startswith(("example", "try it", "who knew")):
                blocks.append({"id": f"ex-{len(blocks)}", "type": "example", "kind": "worked" if text.lower().startswith("example") else "try_it", "title": rt(text), "problem": rt(text), "level": "core"})
            elif text.startswith("Figure") or text.startswith("Table"):
                continue  # caption handled with its figure/table
            elif len(text) > 40:
                blocks.append({"id": f"p-{len(blocks)}", "type": "paragraph", "content": rt(text), "level": "core"})
        elif el.name == "img":
            src = el.get("src") or ""
            alt = el.get("alt") or "Figure"
            m = re.search(r"/resources/([a-f0-9]{40,})", src)
            if not m:
                continue
            hash_ = m.group(1)
            fname = f"{args.concept_id}_{hash_[:8]}.webp"
            fpath = IMG_DIR / fname
            if not fpath.exists():
                try:
                    ir = requests.get(f"{BASE}/resources/{hash_}", headers=HEADERS, timeout=30)
                    ir.raise_for_status()
                    fpath.write_bytes(ir.content)
                except Exception as e:
                    print(f"image download failed {hash_}: {e}", file=sys.stderr)
                    continue
            fig = {"id": f"fig-{len(figures)}", "type": "figure", "asset_url": f"images/{fname}", "caption": rt(alt), "alt": alt, "licence": "CC BY-NC-SA 4.0", "credit": "OpenStax", "level": "core"}
            figures.append(fig)
            blocks.append(fig)
        elif el.name == "table":
            rows = []
            for tr in el.find_all("tr"):
                cells = [clean(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
            if rows:
                blocks.append({"id": f"tbl-{len(blocks)}", "type": "table", "title": rt("Table"), "rows": rows, "alt": f"Table with {len(rows)} rows", "level": "core"})

    doc = {
        "concept_id": args.concept_id,
        "schema_version": 4,
        "updated_at": "2026-11-09",
        "title": args.concept_id.replace("_", " ").title(),
        "subject_area": "mathematics",
        "source_attribution": {"publisher": "OpenStax", "book": args.book, "section": args.section, "url": page_url, "licence": "CC BY-NC-SA 4.0 (non-commercial staging; attribution required)", "locator": "scraped live section page"},
        "revision_summary": {
            "read_time_minutes": 4,
            "key_takeaway": rt("See deep_context.blocks for the full sourced section."),
            "sections": [],
            "worked_examples": [],
            "formulas": [],
            "active_recall_checks": [],
            "examiner_traps": [],
            "sources": [{"title": f"{args.book} {args.section}", "url": page_url, "locator": "scraped live section page"}],
        },
        "deep_context": {"blocks": blocks},
        "placements": [],
    }
    out = OUT_DIR / f"{args.concept_id}.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} with {len(blocks)} blocks ({len(figures)} figures downloaded)")
    print(f"page: {page_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
