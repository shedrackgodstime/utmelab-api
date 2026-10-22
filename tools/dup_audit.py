#!/usr/bin/env python3
"""Duplicate audit for data/questions.json.

Run it before and after any bulk content change:

    python3 tools/dup_audit.py            # report
    python3 tools/dup_audit.py --strict   # exit 1 on any exact duplicate

What counts as a duplicate, and what does not
--------------------------------------------
* **exact** — same stem *and* same options, whatever the ids. Two ids can
  hold one question (a re-harvest, a copy/paste, a retry). Never allowed.
* **shared stem** — same stem, different options. Not automatically a bug:
  two years' papers ask "which of these is not a source document?" with
  different option sets and different correct answers, and both are real
  questions. Reported so a human decides, never auto-dropped.
* **same stem, same key** — the dangerous middle: the options differ, the
  answer letter agrees, so one copy is usually wrong or the pair is one
  question asked twice. Flagged for review.

The normaliser keeps every unicode letter and digit. An earlier version used
`[^a-z0-9]`, which deleted Arabic and Hausa text entirely and made 66
perfectly good rows look like one duplicate — a false alarm that a real
duplication check must never raise. Kept as a unit test so it cannot come back.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BANK = Path("data/questions.json")
VERBOS = Path("data/verifications.json")


def plain(value) -> str:
    """RichText or string → text."""
    if isinstance(value, dict):
        return value.get("text", "")
    return str(value)


def norm(text: str) -> str:
    """Every unicode letter/digit, lowercased — nothing else survives."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def option_key(q: dict) -> str:
    return "|".join(f"{o['id']}:{norm(plain(o['text']))}" for o in q["options"])


def fingerprint(q: dict) -> str:
    payload = norm(plain(q["text"])) + option_key(q)
    return hashlib.sha256(payload.encode()).hexdigest()


def load() -> list[dict]:
    return json.loads(BANK.read_text())


def group(rows: list[dict], key) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        out[key(row)].append(row)
    return out


def label(q: dict, verdicts: dict[str, str]) -> str:
    return f"{q['id']} [{q['subject']}] key={q['answer']} {verdicts.get(q['id'], 'unverified')}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when an exact duplicate exists (for CI)",
    )
    args = parser.parse_args()

    rows = load()
    verdicts = {}
    if VERBOS.exists():
        verdicts = {
            v["question_id"]: v.get("verdict", "?")
            for v in json.loads(VERBOS.read_text())
        }

    ids = [q["id"] for q in rows]
    dup_ids = sorted({i for i in ids if ids.count(i) > 1})

    exact = {h: g for h, g in group(rows, fingerprint).items() if len(g) > 1}
    shared = {
        h: g
        for h, g in group(rows, lambda q: norm(plain(q["text"]))).items()
        if len(g) > 1
    }
    same_key = {
        h: g
        for h, g in shared.items()
        if len({norm(plain(q["text"])) for q in g}) == 1
        and len({q["answer"] for q in g}) == 1
        and len({option_key(q) for q in g}) > 1
    }

    print(f"rows: {len(rows)}")
    print(f"duplicate ids: {len(dup_ids)} {dup_ids}")
    print()
    print(f"EXACT duplicates (stem + options): {len(exact)}")
    for g in exact.values():
        print(f"  {len(g)} copies:")
        for q in g:
            print(f"    {label(q, verdicts)}")
    print()
    print(f"SHARED STEM, different options: {len(shared)}")
    for g in shared.values():
        flag = "  <-- same key, different options" if any(
            norm(plain(q["text"])) in same_key for q in g
        ) else ""
        print(f"  {len(g)} copies{flag}: {plain(g[0]['text'])[:70]!r}")
        for q in g:
            print(f"    {label(q, verdicts)}")
    return 1 if args.strict and (exact or dup_ids) else 0


if __name__ == "__main__":
    sys.exit(main())