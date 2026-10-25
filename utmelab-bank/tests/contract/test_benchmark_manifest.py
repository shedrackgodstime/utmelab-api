import json
from pathlib import Path

MANIFEST = Path(__file__).parents[1] / "fixtures" / "benchmark" / "manifest.json"
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


def test_golden_manifest_has_unique_pending_cases() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = payload["entries"]

    assert payload["version"] == "1"
    assert len(entries) >= 10
    assert len({entry["id"] for entry in entries}) == len(entries)
    assert len({entry["asset_id"] for entry in entries}) == len(entries)
    assert {entry["kind"] for entry in entries} >= REQUIRED_KINDS
    assert all(entry["verified"] is False for entry in entries)
    assert all(entry["expected"] for entry in entries)
    assert all(entry["media_verified"] is True for entry in entries)
