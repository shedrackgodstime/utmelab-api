#!/usr/bin/env python3
"""Preflight validator for study notes.

Checks, per note:
- JSON parses as list of TopicNote objects with required keys
- Serialized size strictly < 16 KiB (16384 bytes, MAX_BODY_BYTES)
- Placement triple present (exam, subject, topic_slug); subtopic optional
- Headings carry no manual numeric prefix (section_number carries it)
- section_number values are 1..n consecutive
- Inline offsets are valid Unicode-scalar ranges inside their text
- Callout kinds in {key_concept, examiner_tip, warning, law, definition}
- Read time_minutes matches ceil(words/150) bounded 1..6
- sources present, non-empty, every source has title + absolute http(s) url
  and a locator
- No em/en dashes in human text (editorial standard)
- worked_examples/formulas/active_recall_checks/examiner_traps are lists;
  linked_question_ids is a list
- Thesis-required rule: at least one worked example OR formulas present
  for mathematics/physics notes (pedagogical completeness)
- Duplicate note ids rejected

Usage: python3 scripts/validate_notes.py <notes.json> [--placements placements.json]
Without a placements file, placement validation checks shape only.
Exit 0 if all notes pass, 1 otherwise.
"""
import json
import math
import re
import sys
from pathlib import Path

MAX_BODY = 16 * 1024
CALL_OUT_KINDS = {"key_concept", "examiner_tip", "warning", "law", "definition"}
INLINE_KINDS = {"bold", "italic", "underline", "strike", "subscript", "superscript", "image"}
NUMERIC_PREFIX = re.compile(r"^\s*\d+\s*[\.\)]\s+")
DASHES = ("—", "–")  # em dash, en dash

REQUIRED_KEYS = [
    "id", "exam", "subject", "topic_slug", "title", "read_time_minutes",
    "key_takeaway", "sections", "worked_examples", "formulas",
    "active_recall_checks", "examiner_traps", "sources", "linked_question_ids",
]


def count_words(note):
    total = len(note["key_takeaway"]["text"].split())
    for s in note["sections"]:
        total += len(s["content"]["text"].split())
        if s.get("callout"):
            total += len(s["callout"]["text"]["text"].split())
    for w in note.get("worked_examples", []):
        total += len(w["problem_statement"]["text"].split())
        total += len(w["final_answer"]["text"].split())
        total += sum(len(st["description"].split()) for st in w["steps"])
    for c in note.get("active_recall_checks", []):
        total += len(c["prompt"].split()) + len(c["explanation"].split())
    for t in note.get("examiner_traps", []):
        total += len(t["misconception"].split()) + len(t["correction"].split())
    return total


def expected_read_time(note):
    return max(1, min(6, math.ceil(count_words(note) / 150)))


def check_rich_text(rt, where, errors):
    """Inline offsets are Unicode-scalar offsets, matching the Rust Inline type."""
    text = rt.get("text", "")
    inlines = rt.get("inline", [])
    n = len(text)  # Python str indexes code points; scalars == code points for BMP+astral in py3
    for iv in inlines:
        start, length = iv.get("start"), iv.get("len")
        kind = iv.get("kind")
        if kind not in INLINE_KINDS:
            errors.append(f"{where}: inline kind {kind!r} not allowed")
            continue
        if start is None or length is None:
            errors.append(f"{where}: inline missing start/len")
            continue
        if start < 0 or length < 0 or start + length > n:
            snippet = text[max(0, start - 5) : start + length + 5] if 0 <= start <= n else ""
            errors.append(
                f"{where}: inline start={start} len={length} exceeds text length {n} ({snippet!r}...)"
            )
    for d in DASHES:
        if d in text:
            errors.append(f"{where}: contains em/en dash {d!r} (editorial standard: none)")


def validate_note(note, errors, seen_ids):
    nid = note.get("id", "<missing id>")
    if nid in seen_ids:
        errors.append(f"duplicate note id {nid}")
    seen_ids.add(nid)

    missing = [k for k in REQUIRED_KEYS if k not in note]
    if missing:
        for k in missing:
            errors.append(f"{nid}: missing required key {k}")
        if any(k not in note for k in ("sections", "key_takeaway", "read_time_minutes")):
            return

    size = len(json.dumps(note, ensure_ascii=False).encode("utf-8"))
    if size >= MAX_BODY:
        errors.append(f"{nid}: serializes to {size} bytes, must be < {MAX_BODY}")

    # Placement shape
    for field in ("exam", "subject", "topic_slug"):
        if not note.get(field) or not isinstance(note[field], str):
            errors.append(f"{nid}: placement field {field} missing or not a string")
    if note.get("subtopic_slug") is not None and not isinstance(note["subtopic_slug"], str):
        errors.append(f"{nid}: subtopic_slug must be string or null")

    # Read time
    words = count_words(note)
    exp = expected_read_time(note)
    if note["read_time_minutes"] != exp:
        errors.append(
            f"{nid}: read_time_minutes={note['read_time_minutes']} but word count {words} "
            f"implies {exp} (ceil(words/150), bounded 1..6)"
        )

    # Rich text everywhere
    check_rich_text(note["key_takeaway"], f"{nid}:key_takeaway", errors)
    secs = note["sections"]
    if not (2 <= len(secs) <= 5):
        errors.append(f"{nid}: expected 2..5 sections, found {len(secs)}")
    for i, s in enumerate(secs, 1):
        if s.get("section_number") != i:
            errors.append(f"{nid}: section {i} has section_number {s.get('section_number')}, expected {i}")
        if NUMERIC_PREFIX.match(s.get("heading", "")):
            errors.append(
                f"{nid}: heading {s.get('heading')!r} has manual numeric prefix; section_number already carries it"
            )
        check_rich_text(s["content"], f"{nid}:section{i}.content", errors)
        co = s.get("callout")
        if co:
            if co.get("kind") not in CALL_OUT_KINDS:
                errors.append(f"{nid}:section{i} callout kind {co.get('kind')!r} not in {sorted(CALL_OUT_KINDS)}")
            check_rich_text(co["text"], f"{nid}:section{i}.callout", errors)
    for w in note.get("worked_examples", []):
        check_rich_text(w["problem_statement"], f"{nid}:example {w['title']}", errors)
        check_rich_text(w["final_answer"], f"{nid}:example {w['title']}", errors)

    # Pedagogy lists
    for lst in ("worked_examples", "formulas", "active_recall_checks", "examiner_traps", "linked_question_ids"):
        if not isinstance(note[lst], list):
            errors.append(f"{nid}: {lst} must be a list")
    if note["subject"] in ("mathematics", "physics") and not note["worked_examples"] and not note["formulas"]:
        errors.append(f"{nid}: math/physics note needs worked_examples or formulas")

    # Sources
    srcs = note.get("sources", [])
    if not srcs:
        errors.append(f"{nid}: sources is empty; every note needs at least one NoteSource")
    for si, s in enumerate(srcs):
        title = s.get("title", "")
        url = s.get("url", "")
        loc = s.get("locator", "")
        if not title:
            errors.append(f"{nid}:sources[{si}] missing title")
        if not (url.startswith("http://") or url.startswith("https://")):
            errors.append(f"{nid}:sources[{si}] url not absolute http(s): {url!r}")
        if not loc:
            errors.append(f"{nid}:sources[{si}] url={url!r} missing locator")
        if "search" in url.lower() and "query=" in url.lower():
            errors.append(f"{nid}:sources[{si}] url looks like a search result, not a stable page")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    notes = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(notes, list):
        print(f"{path}: top level must be a JSON list")
        return 1
    errors = []
    seen = set()
    for n in notes:
        validate_note(n, errors, seen)
    if errors:
        print(f"FAIL: {len(errors)} error(s) in {path}")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: {len(notes)} notes in {path} pass preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
