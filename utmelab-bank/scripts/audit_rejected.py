#!/usr/bin/env python3
"""Export every rejected staging row with a categorised reason.

The question this report answers is "did the bank lose content, and if so,
whose fault is it?" That needs three things the old report did not do:

* It reads the production catalog, so a row that is already served (as a
  near-duplicate, or as a novel question) is not counted as a loss.
* It treats a gate *judgement* as a rule under review, not as a source
  defect. The figure and underline hints were refusing answerable rows.
* It names the exact gate code, so a fix can be aimed at one rule.

Run it where the bank and production credentials are available:

    .venv/bin/python scripts/audit_rejected.py --exam JAMB --summary
    .venv/bin/python scripts/audit_rejected.py --exam JAMB -o rejected.csv

"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utmelab_bank.adapters.database import bank_client, prod_client
from utmelab_bank.adapters.store.staging import StagingStore
from utmelab_bank.config import load_settings

#: Gate refusals are written as ``v6: code_one, code_two``.
_GATE_RE = re.compile(r"^(?P<version>v\d+):\s*(?P<codes>.+)$")

#: What each gate code means for the next step. ``fault`` is who can fix it.
GATE_CODES: dict[str, tuple[str, str]] = {
    # The source payload is malformed, or the source key is wrong.
    "answer_not_an_option": ("source", "answer key names no option"),
    "option_id_duplicate": ("source", "duplicate option ids"),
    "option_id_not_known": ("source", "option ids outside a-e"),
    "option_count": ("source", "fewer than 2 or more than 5 options"),
    "option_text_empty": ("source", "an option has no text"),
    "stem_empty": ("source", "the stem has no text"),
    "inline_out_of_bounds": ("source", "an inline mark runs past the text"),
    "inline_partial_overlap": ("source", "two inline marks partially overlap"),
    "image_url_missing": ("source", "image mark has no value"),
    "image_url_invalid": ("source", "image value is not a usable url"),
    "image_inline_not_anchor": ("source", "image mark has a non-zero length"),
    "year_out_of_range": ("source", "year outside 1900-2100"),
    "marks_out_of_range": ("source", "marks outside 0.5-10"),
    "exam_empty": ("source", "row names no exam"),
    "passage_missing": ("source", "passage the row names is absent"),
    "passage_scope_mismatch": ("source", "passage belongs to another subject"),
    "cloze_without_passage": ("source", "numbered gap with no passage"),
    # The bank's own rules or catalog are out of step with the content.
    "subtopic_not_in_catalog": ("pipeline", "stale catalog slug"),
    "subtopic_topic_missing": ("pipeline", "catalog topic missing"),
    "subtopic_topic_mismatch": ("pipeline", "subtopic under the wrong topic"),
    "placement_scope_mismatch": ("pipeline", "placement scope differs from row"),
    "catalog_scope_mismatch": ("pipeline", "catalog scope differs from row"),
    # Judgements. These were ported from a tool where a person clicked
    # "clear"; in the automated bank they become permanent refusals.
    "missing_figure": ("gate_rule", "stem points at a figure with no image"),
    "underline_missing": ("gate_rule", "stem mentions underlining with no mark"),
    "novel_leak": ("gate_rule", "novel content in a question-bank row"),
    "html_in_text": ("gate_rule", "HTML comment or markup in the stem"),
}

#: Error strings raised by the pipeline or provider, in priority order. The
#: first pattern that matches wins, so put the specific ones before the broad.
ERROR_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"^duplicate_", "duplicate", "duplicate"),
    (r"^review_fail", "source", "canonical answer judged wrong"),
    (r"^review_error", "provider", "review provider failed"),
    (r"^review_abstain", "source", "review abstained (missing media)"),
    (r"^review_", "pipeline", "review refused"),
    (r"ProviderExhausted", "provider", "all provider routes failed"),
    (r"UnknownSubtopic", "pipeline", "tag subtopic not in catalog"),
    (r"LowConfidenceTag", "provider", "tag confidence below threshold"),
    (r"tag evidence does not appear", "provider", "tag evidence not in source text"),
    (r"not a JSON object|invalid JSON|JSONDecode", "provider", "provider returned bad JSON"),
    (r"Kilo|kilo", "provider", "kilo provider failure"),
    (r"TimeoutError|timed out|timeout", "provider", "provider timeout"),
    (r"DatabaseError|query failed", "pipeline", "database failure"),
    (r"ValueError", "pipeline", "validation failure"),
    (r"^not ready", "pipeline", "ready condition not met"),
)


def classify(error: str | None) -> dict[str, str]:
    """Return stage, fault and a short label for one stored error."""
    text = (error or "").strip()
    if not text:
        return {"stage": "unknown", "fault": "unknown", "label": "no error recorded", "codes": ""}

    match = _GATE_RE.match(text)
    if match:
        codes = [code.strip() for code in match.group("codes").split(",") if code.strip()]
        found = [GATE_CODES.get(code, ("unknown", code.replace("_", " "))) for code in codes]
        labels = [f"{code} ({label})" for code, (_, label) in zip(codes, found, strict=False)]
        faults = [fault for fault, _ in found]
        # One pipeline problem in a row is enough to make the row ours to fix.
        fault = "pipeline" if "pipeline" in faults else (faults[0] if faults else "unknown")
        return {
            "stage": "gate",
            "fault": fault,
            "label": "; ".join(labels),
            "codes": ",".join(codes),
        }

    for pattern, fault, label in ERROR_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return {"stage": "review" if label.startswith(("canonical", "review")) else "pipeline",
                    "fault": fault, "label": label, "codes": ""}

    return {"stage": "other", "fault": "unknown", "label": text[:120], "codes": ""}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def production_text_index() -> dict[str, str]:
    """Every production stem, normalised, mapped to its id.

    A near-duplicate has a different hash, so the hash alone cannot tell the
    report that the content is already served. The stem can.
    """
    settings = load_settings()
    client = prod_client(settings)
    index: dict[str, str] = {}
    try:
        for table in ("questions", "novel_questions"):
            result = asyncio.run(client.execute(f"SELECT id, text FROM {table}"))
            for item_id, text in result.rows:
                index.setdefault(_norm(str(text)), str(item_id))
    finally:
        asyncio.run(client.close())
    return index


def collect(exam: str | None, subject: str | None, year: int | None) -> list[dict]:
    settings = load_settings()
    client = bank_client(settings)
    store = StagingStore(client)
    try:
        rows = asyncio.run(
            store.list_by_states(
                ("rejected",),
                limit=50_000,
                exam=exam,
                subject=subject,
                year=year,
            )
        )
    finally:
        asyncio.run(client.close())

    production = production_text_index()

    results: list[dict] = []
    for item in rows:
        scope = item.provenance.scope
        info = classify(item.error)
        production_id = production.get(_norm(item.content.stem.text), "")
        results.append(
            {
                "id": item.id,
                "exam": scope.exam,
                "subject": scope.subject,
                "year": scope.year,
                "section": scope.section or "",
                "source": item.provenance.source,
                "source_item_id": item.provenance.source_item_id,
                "stage": info["stage"],
                "fault": info["fault"],
                "category": info["label"],
                "codes": info["codes"],
                "in_production": bool(production_id),
                "production_id": production_id,
                "error": item.error or "",
                "attempts": item.attempts,
                "answer": item.content.answer,
                "stem": item.content.stem.text[:200],
                "explanation_present": bool(item.evidence.explanation),
                "updated_at": item.updated_at.isoformat(),
            }
        )
    return results


def write_csv(items: list[dict], path: Path) -> None:
    fields = list(items[0].keys()) if items else ["id"]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(items)


def print_summary(items: list[dict]) -> None:
    total = len(items)
    print("\n=== Rejected items ===")
    print(f"Total: {total}")
    if not total:
        return

    served = sum(1 for item in items if item["in_production"])
    duplicates = sum(1 for item in items if item["fault"] == "duplicate")
    lost = [
        item
        for item in items
        if not item["in_production"] and item["fault"] != "duplicate"
    ]
    print(f"Already in production: {served}")
    print(f"Duplicates inside the bank: {duplicates}")
    print(f"Not served anywhere:     {len(lost)}")

    print("\nBy fault (who can fix it):")
    for fault, count in Counter(item["fault"] for item in items).most_common():
        print(f"  {fault:<12} {count:>5}  {count / total:.0%}")

    print("\nLosses by category (not in production, not a duplicate):")
    for (fault, category), count in Counter(
        (item["fault"], item["category"]) for item in lost
    ).most_common():
        print(f"  [{fault}] {category}: {count}")

    print("\nBy subject and stage:")
    for (subject, stage), count in Counter(
        (item["subject"], item["stage"]) for item in items
    ).most_common():
        print(f"  {subject:<32} {stage:<8} {count}")

    print("\nTop recurring gate codes:")
    codes = Counter(
        code
        for item in items
        for code in (item["codes"].split(",") if item["codes"] else [])
        if code
    )
    for code, count in codes.most_common(15):
        print(f"  {code:<32} {count}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit rejected staging items")
    parser.add_argument("--exam", help="Exam filter, e.g. JAMB")
    parser.add_argument("--subject", help="Subject slug filter")
    parser.add_argument("--year", type=int, help="Year filter")
    parser.add_argument("-o", "--output", help="CSV or JSON output path")
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("--summary", action="store_true", help="Print the breakdown")
    args = parser.parse_args()

    items = collect(args.exam, args.subject, args.year)

    if args.summary or not args.output:
        print_summary(items)

    if args.output:
        path = Path(args.output)
        if args.format == "json":
            path.write_text(json.dumps(items, indent=2))
        else:
            write_csv(items, path)
        print(f"\nWritten {len(items)} rows to {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
