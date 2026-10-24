"""The checked-in WAEC syllabus inputs stay aligned with the source map."""

from __future__ import annotations

import json
from pathlib import Path

from utmelab_bank.adapters.sources.myschool.subjects import load_map

REPO_ROOT = Path(__file__).resolve().parents[3]
WAEC_DIR = REPO_ROOT / "data" / "waec"


def test_every_waec_syllabus_input_is_mapped_and_structurally_complete() -> None:
    entries = load_map().exam("WAEC").subjects
    catalog_slugs = {entry.slug for entry in entries}
    files = sorted(WAEC_DIR.glob("*.json"))

    assert files
    assert {path.stem for path in files} <= catalog_slugs

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        subjects = payload["subjects"]
        topics = payload["topics"]
        subtopics = payload["subtopics"]

        assert len(subjects) == 1
        assert subjects[0]["exam"] == "WAEC"
        assert subjects[0]["slug"] == path.stem
        assert topics
        assert subtopics

        topic_slugs = {topic["slug"] for topic in topics}
        assert len(topic_slugs) == len(topics)
        assert all(subtopic["topic"] in topic_slugs for subtopic in subtopics)
        assert all(
            set(topic.get("countries", [])) <= {"NG", "GH", "SL", "GM", "LR"}
            for topic in topics
        )
