"""Validate the local golden benchmark manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MANIFEST = Path(__file__).parents[1] / "tests" / "fixtures" / "benchmark" / "manifest.json"
REQUIRED_KINDS = {
    "labelled_diagram",
    "graph",
    "equation_or_formula",
    "electrical_diagram",
    "diagram_only",
    "low_resolution",
    "malformed_media",
    "calculation_diagram",
}


def load_manifest() -> dict:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = payload.get("entries", [])
    if payload.get("version") != "1":
        raise ValueError("unsupported benchmark manifest version")
    if len(entries) < 10:
        raise ValueError("benchmark manifest must contain at least 10 entries")
    if len({entry["id"] for entry in entries}) != len(entries):
        raise ValueError("benchmark entry IDs must be unique")
    if len({entry["asset_id"] for entry in entries}) != len(entries):
        raise ValueError("benchmark asset IDs must be unique")
    if not {entry["kind"] for entry in entries} >= REQUIRED_KINDS:
        raise ValueError("benchmark manifest is missing a required media kind")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the golden benchmark manifest")
    parser.add_argument(
        "--require-verified",
        action="store_true",
        help="fail until every entry has a manually checked expected observation",
    )
    args = parser.parse_args()

    payload = load_manifest()
    entries = payload["entries"]
    verified = sum(bool(entry.get("verified")) for entry in entries)
    pending = len(entries) - verified
    print(f"cases={len(entries)} verified={verified} pending={pending}")
    if args.require_verified and pending:
        print("benchmark manifest still needs manual labels")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
