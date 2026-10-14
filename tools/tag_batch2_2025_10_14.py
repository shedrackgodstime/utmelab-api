#!/usr/bin/env python3
"""Tagging batch 2, 2026-10-14: english, art, french, geography, computer-studies.

Same discipline as the physics batch (see tools/physics_tag_2025_10_14.py):
every slug is checked against `data/subtopics.json` and against the subject's
own topic list, an already-tagged row is left alone, and a row with no honest
home stays null with the reason printed.

English note: the catalog has three topics and eleven subtopics, and **no
"comprehension" subtopic** — `fiction` and `cloze` are the only two under the
comprehension topic. So passage questions with no passage of their own (the
bird rows, which reference a stimulus the row does not carry) have no slug to
go to and stay null rather than being filed under "fiction", which is a lie
about what they are. Cloze rows, which do carry their passage, are filed.

Run: `python3 tools/tag_batch2_2025_10_14.py [--dry-run]`
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

BANK = Path("data/questions.json")
SUBS = Path("data/subtopics.json")
TOPICS = Path("data/topics.json")

# full id -> subtopic slug
ID_TAGS = {
    # ── use of english ─────────────────────────────────────────────────────
    "q_authored_eng_cloze_001": "cloze",
    "q_authored_eng_cloze_002": "cloze",
    "q_authored_eng_cloze_003": "cloze",
    "q_authored_eng_cloze_004": "cloze",
    "q_claim_2025_english-language_74804": "cloze",
    "q_claim_2025_english-language_74805": "cloze",
    "q_claim_2025_english-language_74806": "cloze",
    "q_claim_2025_english-language_74807": "cloze",
    "q_claim_2025_english-language_74808": "cloze",
    "q_claim_2025_english-language_74809": "cloze",
    "q_claim_2025_english-language_74810": "cloze",
    "q_claim_2025_english-language_74811": "cloze",
    # ── art ────────────────────────────────────────────────────────────────
    "q_authored_fine_arts_colour_001": (
        "elements-of-design-line-colour-shape-form-texture-tone-value"
    ),
    "q_claim_2025_fine-arts_75228": "nok-igbo-ukwu-ife-benin-esie-igala-jukun-akwashi-mbari",
    "q_claim_2025_fine-arts_75242": "nok-igbo-ukwu-ife-benin-esie-igala-jukun-akwashi-mbari",
    "q_claim_2025_fine-arts_75247": "nok-igbo-ukwu-ife-benin-esie-igala-jukun-akwashi-mbari",
    # ── french ─────────────────────────────────────────────────────────────
    "q_claim_2025_french_75225": "liaison-e-g-trois-animaux-des-enfants",
    "q_claim_2025_french_75237": (
        "identification-and-application-of-basic-processes-conjugatio"
    ),
    "q_claim_2025_french_75420": (
        "reading-and-interpreting-texts-on-topics-of-general-and-emer"
    ),
    "q_claim_2025_french_75873": "identification-of-basic-form-classes-pr-positions-simple-e-g",
    "q_claim_2025_french_75874": "assessment-of-vocabulary-span-words-in-contemporary-contexts",
    # ── geography ──────────────────────────────────────────────────────────
    "q_claim_2025_geography_75447": (
        "natural-resources-types-minerals-soils-water-vegetation-etc-geography"
    ),
    "q_claim_2025_geography_75485": "erosion-geography",
    "q_claim_2025_geography_75534": (
        "recognition-and-description-of-physical-and-human-features-a-geography"
    ),
    "q_claim_2025_geography_75535": (
        "distances-areas-reduction-and-enlargement-geography"
    ),
    # ── computer studies ───────────────────────────────────────────────────
    "q_claim_2025_computer-studies_64124": "definitions-of-algorithm-and-flowchart",
    "q_claim_2025_computer-studies_64334": "software-types-examples-and-uses",
    "q_claim_2025_computer-studies_64424": "definition-and-classification-of-programming-languages",
    "q_claim_2025_computer-studies_64429": "software-types-examples-and-uses",
}

# Rows deliberately left null, with the reason printed on every run so the gap
# stays visible instead of quietly persisting.
LEFT_NULL = {
    "q_authored_eng_reading_001": "the headmaster passage is a novel document, not a bank row",
    "q_claim_2025_english-language_74769": "passage question with no passage in the row; the catalog has no comprehension subtopic",
    "q_claim_2025_english-language_74770": "same",
    "q_claim_2025_english-language_74771": "same",
    "q_claim_2025_english-language_74772": "same",
    "q_claim_2025_english-language_74773": "same",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = json.loads(BANK.read_text())
    subtopics = {s["slug"]: s for s in json.loads(SUBS.read_text())}
    topics = {t["slug"]: t for t in json.loads(TOPICS.read_text())}
    problems = []
    for qid, slug in ID_TAGS.items():
        if slug not in subtopics:
            problems.append(f"{qid} -> {slug}: not in data/subtopics.json")
            continue
        owner = topics[subtopics[slug]["topic"]]["subject"]
        row = next((r for r in rows if r["id"] == qid), None)
        if row is not None and owner != row["subject"]:
            problems.append(f"{qid} -> {slug}: that subtopic belongs to {owner}")
    if problems:
        print("ABORT: bad assignments")
        for p in problems:
            print(f"  {p}")
        return 1

    tagged = 0
    for row in rows:
        slug = ID_TAGS.get(row["id"])
        if slug and not row.get("subtopic_id"):
            if args.dry_run:
                print(f"  {row['id']} -> {slug}")
            row["subtopic_id"] = slug
            tagged += 1

    print(f"tagged {tagged}")
    by_slug = Counter(ID_TAGS.values())
    for slug, n in by_slug.most_common():
        print(f"  {n:2}  {subtopics[slug]['name'][:66]}")

    print(f"\nleft null on purpose: {len(LEFT_NULL)} rows this batch")
    for qid, why in LEFT_NULL.items():
        print(f"  {qid}: {why}")

    if not args.dry_run:
        BANK.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
        print("data/questions.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())