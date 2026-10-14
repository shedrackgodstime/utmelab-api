#!/usr/bin/env python3
"""Tagging batch 3, 2026-10-14: the last taggable untagged rows.

Thirty rows across fourteen subjects, each assigned the syllabus subtopic its
question actually tests, with the same discipline as the physics batch: slug
checked against `data/subtopics.json` *and* against its owning topic's subject,
already-tagged rows untouched, and a row with no honest home left null with the
reason printed.

Two rows cannot be tagged at all and are recorded rather than forced:

  q_waec_2025_animal_husbandry_001 — the catalog has zero topics for
    animal-husbandry (our only WAEC row). The agricultural-science subtopics
    cover the same ground, but filing a WAEC row under a JAMB topic would make
    the topic tree claim a subject it does not own.
  q_unassigned_civic_001 — carries no exam at all, so it is already withheld
    from serving; civic-education likewise has no topics.

Run: `python3 tools/tag_batch3_2025_10_14.py [--dry-run]`
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

BANK = Path("data/questions.json")
SUBS = Path("data/subtopics.json")
TOPICS = Path("data/topics.json")

ID_TAGS = {
    # ── agricultural science ───────────────────────────────────────────────
    "q_claim_2025_agricultural-science_76147": (
        "macro-and-micro-nutrients-and-their-roles-in-plant-nutrition-agricultural-science"
    ),
    "q_claim_2025_agricultural-science_76176": (
        "factors-affecting-rock-weathering-and-soil-formation-agricultural-science"
    ),
    # ── christian religious studies ───────────────────────────────────────
    "q_claim_2025_christian-religious-knowledge-crk_74744": (
        "the-calls-of-isaiah-ezekiel-and-jeremiah-isaiah-6-1-13-ezek"
    ),
    "q_claim_2025_christian-religious-knowledge-crk_74746": (
        "obedience-and-rewards-abraham-gen-22-1-19-hebrew-midwives-ex"
    ),
    "q_claim_2025_christian-religious-knowledge-crk_74753": (
        "the-call-of-the-first-disciples-mt-4-18-22-9-9-13-mk-1-16-20"
    ),
    # ── commerce / economics / government ──────────────────────────────────
    "q_claim_2025_economics_76928": "determination-of-wages-interest-and-profit",
    "q_claim_2025_government_74624": (
        "the-1963-1979-1989-and-1999-constitutions-characteristics-an"
    ),
    # ── literature ─────────────────────────────────────────────────────────
    "q_claim_2025_literature-in-english_74715": "interpretation-of-the-prescribed-texts-theme-plot-socio-poli",
    "q_claim_2025_literature-in-english_75031": "poetic-devices-structure-imagery-sound-rhyme-rhythm-repetiti",
    # ── principles of accounts ─────────────────────────────────────────────
    "q_claim_2025_accounts-principles-of-accounts_75030": "columnar-cashbooks",
    "q_claim_2025_accounts-principles-of-accounts_75171": "principles-concepts-and-conventions-of-accounting",
    # ── biology ────────────────────────────────────────────────────────────
    "q_claim_2025_biology_74417": "probability-in-genetics-and-sex-determination-biology",
    "q_claim_2025_biology_74505": "animal-nutrition-food-classes-food-tests-mammalian-teeth-ali-biology",
    "q_claim_2025_biology_74512": "application-of-the-principles-of-heredity-in-agriculture-and-biology",
    # ── chemistry ──────────────────────────────────────────────────────────
    "q_claim_2025_chemistry_74216": "dynamic-equilibrium",
    # ── mathematics ────────────────────────────────────────────────────────
    "q_claim_2025_mathematics_74094": "properties-of-closure-commutativity-associativity-and-distri",
    "q_claim_2025_mathematics_74200": "properties-of-closure-commutativity-associativity-and-distri",
    # ── arabic / islamic religious studies ─────────────────────────────────
    "q_claim_2025_arabic_75333": "plurals-sound-masculine-plural-sound-feminine-plural-and-bro",
    "q_claim_2025_islamic-religious-knowledge-irk_75550": "jahiliyyah-practices-idol-worship-infanticide-polyandry-gamb",
    "q_claim_2025_islamic-religious-knowledge-irk_75568": "belief-in-his-prophets-ulul-azmi-q-4-163-164",
    # ── hausa ──────────────────────────────────────────────────────────────
    "q_claim_2025_hausa_75956": "contextual-questions-from-unseen-passages-approximately-200",
    "q_claim_2025_hausa_76187": "contextual-questions-from-unseen-passages-approximately-200",
    "q_claim_2025_hausa_76195": "contextual-questions-from-unseen-passages-approximately-200",
    "q_claim_2025_hausa_76208": "contextual-questions-from-unseen-passages-approximately-200",
    # ── igbo ───────────────────────────────────────────────────────────────
    "q_claim_2025_igbo_75085": "igbo-orthography-mkp-r-edemede-igbo",
    "q_claim_2025_igbo_75088": "proverbs-ilu",
    "q_claim_2025_igbo_75707": "analysis-of-characters-themes-story-lines-language-and-moral",
    "q_claim_2025_igbo_75701": "analysis-of-characters-themes-story-lines-language-and-moral",
    # ── home economics / physical education ────────────────────────────────
    "q_claim_2025_home-economics_74957": (
        "textile-terms-fibres-fabrics-yarn-staple-filament-blends"
    ),
    "q_claim_2025_physical-education_76419": "skills-of-table-tennis-and-badminton",
}

LEFT_NULL = {
    "q_waec_2025_animal_husbandry_001": "no catalog topics for animal-husbandry",
    "q_unassigned_civic_001": "no exam on the row (withheld from serving); civic-education has no topics",
    "q_claim_2025_agricultural-science_76234": (
        "'functions of livestock' has no subtopic; livestock-management carries only the "
        "ruminant-care line"
    ),
    "q_claim_2025_commerce_75442": (
        "the row says 'use the information below' and carries none — the data is missing, "
        "so it is unanswerable as served and has no home to be filed under"
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = json.loads(BANK.read_text())
    by_id = {r["id"]: r for r in rows}
    subtopics = {s["slug"]: s for s in json.loads(SUBS.read_text())}
    topics = {t["slug"]: t for t in json.loads(TOPICS.read_text())}

    problems = []
    for qid, slug in ID_TAGS.items():
        row = by_id.get(qid)
        if row is None:
            problems.append(f"{qid}: not in the bank")
            continue
        if slug not in subtopics:
            problems.append(f"{qid} -> {slug}: not a catalog subtopic")
            continue
        owner = topics[subtopics[slug]["topic"]]["subject"]
        if owner != row["subject"]:
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

    print(f"\ntagged {tagged}")
    for slug, n in Counter(ID_TAGS.values()).most_common():
        print(f"  {n:2}  {subtopics[slug]['name'][:64]}")
    print(f"\nleft null on purpose: {len(LEFT_NULL)}")
    for qid, why in LEFT_NULL.items():
        print(f"  {qid}: {why}")

    if not args.dry_run:
        BANK.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
        print("data/questions.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())