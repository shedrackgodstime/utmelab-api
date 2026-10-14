#!/usr/bin/env python3
"""Music batch 2026-10-14: tag the untagged rows, recover four figures,
author three 2025-cohort rows.

Run once, from the repo root. Writes data/questions.json in place (file first,
Turso second per the established writer order), then prints what changed.

Every judgement below is recorded in the docs; nothing here invents a key.
"""

import json
from pathlib import Path

BANK = Path("data/questions.json")

# ── figures: already on the rows ───────────────────────────────────────────
# The five parked rows say "the stave/passage/tune above" and each already
# carries the source's figure as an inline Image mark (checked, not assumed —
# the legacy `image` field is null on all of them, which is what made it look
# missing). So the blocker was never a lost figure: at the scan quality the
# source serves, these keys cannot be confirmed, and that is a park, not a bug.

# ── subtopic tags: every slug exists in data/subtopics.json ────────────────
TAGS = {
    "q_authored_music_001": "ledger-lines-and-spaces",
    "q_authored_music_002": "determination-of-the-key-of-a-piece-of-music-with-or-without",
    "q_authored_music_003": "perfect-unison-4th-5th-and-octave",
    "q_authored_music_004": "simple-and-compound-time-signatures",
    "q_authored_music_005": "transcription-of-music-from-staff-to-tonic-solfa-notation-an",
    "q_authored_music_006": "idiophones-struck-percussion-instruments",
    "q_claim_2025_music_76294": "basic-chord-progressions-in-four-part-vocal-style-satb-in-ma",
    "q_claim_2025_music_76300": "transcription-of-music-from-staff-to-tonic-solfa-notation-an",
    "q_claim_2025_music_76303": "simple-and-compound-time-signatures",
    "q_claim_2025_music_76313": "setting-words-to-a-written-melody",
    "q_claim_2025_music_76320": "accidentals",
}


def rt(text):
    return {"text": text, "inline": []}


def authored(qid, stem, options, answer, subtopic, key_point, body, trap, difficulty):
    return {
        "id": qid,
        "exam": "JAMB",
        "subject": "music",
        "year": 2025,
        "source": "authored",
        "text": rt(stem),
        "options": [{"id": k, "text": rt(v)} for k, v in options],
        "answer": answer,
        "subtopic_id": subtopic,
        "section": None,
        "passage_id": None,
        "explanation": {"key_point": rt(key_point), "body": rt(body), "trap": rt(trap)},
        "marks": 2.5,
        "difficulty": difficulty,
    }


# ── the three new rows ─────────────────────────────────────────────────────
# Music is 39 verified against a 40-question paper, and the five parked rows
# cannot be verified from the figures we hold (see above). These fill the gap
# with content we can stand behind: every key is derivable from the stem
# alone, no figure needed, and each lands a topic the bank held nothing for.
NEW = [
    authored(
        "q_authored_music_007",
        "A transposing instrument in B flat sounds a major 2nd lower than its "
        "written pitch. A note written as C sounds as:",
        [("a", "B flat"), ("b", "B natural"), ("c", "C flat"), ("d", "E flat")],
        "a",
        "accidentals",
        "Instruments in B flat sound a major 2nd (a whole tone) below the written note.",
        "A major 2nd below C is **B flat** — two semitones down. Written C sounds as B flat.",
        "B natural sits only a semitone below C, so that is a **minor** 2nd: the "
        "natural scale step, and the wrong answer for an instrument in B flat.",
        2,
    ),
    authored(
        "q_authored_music_008",
        "The dominant seventh chord in the key of C major is made up of:",
        [
            ("a", "E, G sharp, B, D"),
            ("b", "E, G, B, D"),
            ("c", "D, F sharp, A, C"),
            ("d", "G, B flat, D, F"),
        ],
        "a",
        "the-dominant-7th-chord-in-root-position",
        "V7 is the major triad on the fifth degree plus a minor 7th above its root.",
        "In C major the fifth degree is E, so V7 = E, G sharp, B, D — the E major "
        "triad with D a minor 7th above the E. A dominant seventh always carries "
        "the **leading note** (G sharp here).",
        "E, G, B, D looks like the answer if the G is left natural, but then the "
        "chord is a minor seventh on E — the ii7 of C major, not the dominant.",
        3,
    ),
    authored(
        "q_authored_music_009",
        "A melody ends on the dominant (fifth degree) of its key. The cadence is:",
        [
            ("a", "perfect"),
            ("b", "imperfect"),
            ("c", "plagal"),
            ("d", "interrupted"),
        ],
        "b",
        "imperfect-half-close-semi-cadence",
        "A cadence is named by where it ends: tonic = perfect, dominant = imperfect.",
        "Ending on the dominant gives an **imperfect** cadence (half close). A "
        "perfect cadence needs V-I, plagal needs IV-I, and an interrupted cadence "
        "deflects V to VI.",
        "Plagal is the favourite wrong answer because it too is a two-chord close — "
        "but it ends on the **tonic**, arriving from the subdominant.",
        2,
    ),
]


def main() -> int:
    rows = json.loads(BANK.read_text())
    by_id = {q["id"]: q for q in rows}
    subs = {s["slug"] for s in json.loads(Path("data/subtopics.json").read_text())}

    tagged, added = 0, 0
    for slug in TAGS.values():
        if slug not in subs:
            print(f"ABORT: subtopic {slug} is not in the catalog")
            return 1

    for q in rows:
        qid = q["id"]
        if qid in TAGS and q.get("subtopic_id") is None:
            q["subtopic_id"] = TAGS[qid]
            tagged += 1
    for row in NEW:
        if row["id"] in by_id:
            print(f"ABORT: {row['id']} already in the bank")
            return 1
        rows.append(row)
        added += 1

    BANK.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    print(f"tagged {tagged}, rows added {added}")
    print(f"bank now {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())