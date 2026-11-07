"""The checked-in WAEC input is the pinned source manifest, nothing else.

The per-subject catalog is a local build artifact. Production holds the only
persistent catalog, so a checked-in subject JSON would be a second, drifting
copy.
"""

from __future__ import annotations

import json
from pathlib import Path

from utmelab_bank.adapters.sources.myschool.subjects import load_map

REPO_ROOT = Path(__file__).resolve().parents[3]
WAEC_DIR = REPO_ROOT / "data" / "waec"
MANIFEST = WAEC_DIR / "sources.json"

#: Inputs beside the subject syllabuses that are not catalog rows.
NON_CATALOG_FILES = frozenset({"sources", "verifications"})


def test_data_waec_holds_no_per_subject_catalog() -> None:
    files = sorted(path.stem for path in WAEC_DIR.glob("*.json"))
    assert MANIFEST.is_file()
    assert set(files) - NON_CATALOG_FILES == set()


def test_every_manifest_subject_is_an_official_waec_subject() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    subjects = payload["subjects"]
    official = {entry.slug for entry in load_map().exam("WAEC").subjects}

    assert subjects
    assert set(subjects) <= official


def test_every_manifest_entry_pins_the_pdf_it_builds_from() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    for slug, item in payload["subjects"].items():
        assert item["pdf"].startswith("https://"), slug
        assert len(item["sha256"]) == 64, slug
        assert int(item["bytes"]) > 0, slug
        assert int(item["pages"]) > 0, slug
