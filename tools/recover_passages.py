#!/usr/bin/env python3
"""Recover the missing passages, 2026-10-14.

An invariant added to the suite (`tests/answerable.rs`) found **33 rows that
promise a passage the bank does not carry** — Arabic 10, French 6, Hausa 8,
Igbo 6 — plus the six already handled. The source published every one of those
stimuli on the question's own page; `tools/harvest.py` read the stimulus into a
`ref` field nothing consumed, so the rows arrived as pointers with no text.

This walks the source for each affected row, extracts the passage with the
harvester's own reader, groups rows that share a stimulus into one passage
document, and writes:
  * `data/passages.json` — one document per distinct stimulus
  * `data/questions.json` — `passage_id` set on every row that now has one

Polite by construction: one request per row, `--delay` seconds apart, one
worker. Idempotent: a row that already carries a passage is skipped, and a row
whose stimulus cannot be recovered is reported and left alone (it becomes a
decision, not a silent gap).

Run: `python3 tools/recover_passages.py [--dry-run] [--delay 2.5]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import harvest  # noqa: E402

BANK = Path("data/questions.json")
PASSAGES = Path("data/passages.json")

# Stems that announce a stimulus the row must then carry. Mirrors
# `tests/answerable.rs` — the test is the gate, this is the repair.
PROMISES = (
    "passage below",
    "passage above",
    "following passage",
    "read the passage",
    "according to the passage",
    "the text below",
    "according to the text",
    "use the information below",
    "use the information",
    "the table below",
)

# The source spells subjects its own way (the harvester's slug map).
SOURCE_SLUG = {
    "arabic": "arabic",
    "french": "french",
    "hausa": "hausa",
    "igbo": "igbo",
    "english-language": "english-language",
    "commerce": "commerce",
    "music": "music",
}


def rt(text: str) -> dict:
    return {"text": text, "inline": []}


def promises(row: dict) -> bool:
    text = row["text"]["text"] if isinstance(row["text"], dict) else str(row["text"])
    low = text.lower()
    # A figure is the stimulus for a drawn one, and rides the row as an image
    # mark — those rows are answerable and are not this script's business.
    if row["text"].get("inline"):
        return False
    return any(needle in low for needle in PROMISES)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=2.5)
    args = parser.parse_args()

    rows = json.loads(BANK.read_text())
    known = {p["id"] for p in json.loads(PASSAGES.read_text())}
    targets = [
        r
        for r in rows
        if r.get("passage_id") is None and promises(r) and not r["text"].get("inline")
    ]
    print(f"rows promising a passage they do not carry: {len(targets)}")
    if not targets:
        return 0

    recovered: dict[str, list[str]] = defaultdict(list)  # passage text -> row ids
    failed: list[tuple[str, str]] = []
    for i, row in enumerate(targets, 1):
        slug = SOURCE_SLUG.get(row["subject"], row["subject"])
        qid = row["id"].rsplit("_", 1)[-1]
        url = f"https://myschool.ng/classroom/{slug}/{qid}?exam_type=jamb&exam_year={row['year']}"
        try:
            html = harvest.fetch(url)
            passage = harvest.extract_passage(html)
        except Exception as error:  # noqa: BLE001 — one bad page must not stop the run
            failed.append((row["id"], f"fetch failed: {error}"))
            print(f"  [{i}/{len(targets)}] {row['id']}: fetch failed")
            continue
        if not passage:
            failed.append((row["id"], "no stimulus found on the page"))
            print(f"  [{i}/{len(targets)}] {row['id']}: NO STIMULUS")
        else:
            recovered[passage].append(row["id"])
            print(f"  [{i}/{len(targets)}] {row['id']}: {len(passage)} chars")
        time.sleep(args.delay)

    print(f"\n{sum(len(v) for v in recovered.values())} rows recovered into "
          f"{len(recovered)} distinct passages; {len(failed)} failed")
    for qid, why in failed:
        print(f"  failed {qid}: {why}")
    if args.dry_run:
        return 0

    passages = json.loads(PASSAGES.read_text())
    by_text = {p["text"]["text"]: p["id"] for p in passages}
    created = 0
    for text, row_ids in recovered.items():
        if text in by_text:
            pid = by_text[text]
        else:
            subject = next(r["subject"] for r in rows if r["id"] == row_ids[0])
            kind = "Data" if "information below" in text.lower() else "Comprehension"
            digest = hashlib.sha256(text.encode()).hexdigest()[:8]
            pid = f"psg_jamb_2025_{subject.replace('-', '_')}_{kind.lower()}_{digest}"
            assert pid not in known, pid
            known.add(pid)
            passages.append(
                {
                    "id": pid,
                    "exam": "JAMB",
                    "subject": subject,
                    "year": 2025,
                    "kind": kind,
                    "title": f"Recovered stimulus {digest}",
                    "author": None,
                    "text": rt(text),
                }
            )
            by_text[text] = pid
            created += 1
        for qid in row_ids:
            next(r for r in rows if r["id"] == qid)["passage_id"] = pid

    PASSAGES.write_text(json.dumps(passages, indent=2, ensure_ascii=False) + "\n")
    BANK.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {created} new passage documents, linked "
          f"{sum(len(v) for v in recovered.values())} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())