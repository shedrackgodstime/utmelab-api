#!/usr/bin/env python3
"""Convert one openly licensed PDF chapter or lecture range into a concept file.

Usage:
    python3 scripts/scrape_open_pdf.py --pdf /tmp/book.pdf \
        --concept-id eng_phonetics_vowels --title "English Vowels" \
        --subject-area english_language --publisher "Mountain Top University" \
        --book "ENG 204 Introduction to General Phonetics and Phonology II" \
        --licence "CC BY 4.0" --source-url "https://oer.mtu.edu.ng/..." \
        --start "LECTURE THREE" --end "LECTURE FOUR"

The PDF is read locally. Text is split on explicit lecture/chapter markers when
given, otherwise the whole document is used. Headings are inferred from numbered
section patterns, all-caps lines, and standard course headings. Figures are not
extracted from PDFs (vector art and scans cannot be reproduced reliably); the
source locator records the page range so a future figure pass can add them.
"""
import argparse
import datetime
import json
import pathlib
import re
import sys

from pdfminer.high_level import extract_text

OUT_DIR = pathlib.Path("data/concepts")

HEADING_RE = re.compile(
    r"^(?:"
    r"LECTURE\s+(?:\d+|[A-Z]+)\b.*|"
    r"CHAPTER\s+(?:\d+|[A-Z]+)\b.*|"
    r"\d+(?:\.\d+)*\s+[A-Z].*|"
    r"(?:Learning\s+)?Objectives|Pre-?Test|CONTENT|Introduction|Conclusion|"
    r"Summary|Bibliography|References|Revision(?:\s+Questions?)?|Key\s+Terms|"
    r"Glossary|Exercises?|Self-?Test(?:\s+Questions?)?|Course\s+Contents?"
    r")\s*$",
    re.IGNORECASE,
)

LIST_RE = re.compile(r"^(?:\(?[ivxlcdm]+\)?[.)]|\(?[a-z]\)|[0-9]+[.)]|[-•*])\s+", re.IGNORECASE)


def rt(text: str):
    return {"text": " ".join(str(text).split()), "inline": []}


def clean_lines(text: str):
    text = text.replace("\x0c", "\n")
    text = text.replace("\u00ad", "")
    text = text.replace("\uf0b7", "•")
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        # Drop running licence lines and bare page numbers.
        if re.search(r"is licensed under|Creative Commons Attribution", line, re.I):
            continue
        if re.fullmatch(r"\d{1,3}", line):
            continue
        line = re.sub(r"[ \t]+", " ", line)
        lines.append(line)
    return lines


def slice_lines(lines, start, end):
    if not start:
        return lines
    joined = "\n".join(lines)
    start_re = re.compile(re.escape(start))
    m = start_re.search(joined)
    if not m:
        raise SystemExit(f"start marker not found: {start!r}")
    begin = m.start()
    if end:
        m2 = re.compile(re.escape(end)).search(joined, begin + len(start))
        if not m2:
            raise SystemExit(f"end marker not found after start: {end!r}")
        joined = joined[begin:m2.start()]
    else:
        joined = joined[begin:]
    return joined.splitlines()


def is_heading(line: str):
    if len(line) > 140:
        return False
    if HEADING_RE.match(line):
        return True
    # All-caps short lines are usually section banners.
    letters = [c for c in line if c.isalpha()]
    if len(letters) >= 4 and line.upper() == line and len(line) <= 90:
        return True
    return False


def build_blocks(lines):
    blocks = []
    buf = []

    def flush():
        nonlocal buf
        if not buf:
            return
        text = " ".join(buf)
        text = re.sub(r"\s+", " ", text).strip()
        buf = []
        if len(text) < 2:
            return
        blocks.append({
            "id": f"p-{len(blocks)}",
            "type": "paragraph",
            "content": rt(text),
            "level": "core",
        })

    for line in lines:
        if not line:
            flush()
            continue
        if is_heading(line):
            flush()
            blocks.append({
                "id": f"sec-{len(blocks)}",
                "type": "heading",
                "text": rt(line),
                "level": "core",
            })
            continue
        buf.append(line)
    flush()
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--concept-id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--subject-area", required=True)
    ap.add_argument("--publisher", required=True)
    ap.add_argument("--book", required=True)
    ap.add_argument("--licence", required=True)
    ap.add_argument("--source-url", required=True)
    ap.add_argument("--locator", default="")
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    path = pathlib.Path(args.pdf)
    if not path.exists():
        raise SystemExit(f"PDF not found: {path}")

    raw = extract_text(str(path))
    lines = clean_lines(raw)
    lines = slice_lines(lines, args.start, args.end) if args.start else lines
    blocks = build_blocks(lines)

    words = sum(len(b.get("content", b.get("text", {})).get("text", "").split()) for b in blocks)
    read_minutes = max(1, round(words / 200))

    locator = args.locator or f"PDF text extraction, {len(blocks)} blocks"
    doc = {
        "concept_id": args.concept_id,
        "schema_version": 4,
        "updated_at": datetime.date.today().isoformat(),
        "title": args.title,
        "subject_area": args.subject_area,
        "source_attribution": {
            "publisher": args.publisher,
            "book": args.book,
            "section": args.title,
            "url": args.source_url,
            "licence": args.licence,
            "locator": locator,
        },
        "revision_summary": {
            "read_time_minutes": read_minutes,
            "key_takeaway": rt("See deep_context.blocks for the full sourced chapter."),
            "sections": [],
            "worked_examples": [],
            "formulas": [],
            "active_recall_checks": [],
            "examiner_traps": [],
            "sources": [{
                "title": f"{args.book} ({args.publisher})",
                "url": args.source_url,
                "locator": locator,
            }],
        },
        "deep_context": {"blocks": blocks},
        "placements": [],
    }
    if args.notes:
        doc["source_attribution"]["notes"] = args.notes

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{args.concept_id}.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    kinds = {}
    for b in blocks:
        kinds[b["type"]] = kinds.get(b["type"], 0) + 1
    print(f"wrote {out} with {len(blocks)} blocks, {words} words, ~{read_minutes} min")
    print(kinds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
