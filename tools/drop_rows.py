#!/usr/bin/env python3
"""Drop the four duplicate/contested rows found by tools/dup_audit.py (D72).

Every row below is named with the row it duplicates and the reason. The bank
keeps one copy of a question; the docs keep the record, because the bank is a
question bank and an evidence store is a different thing (and a duplicate is
still a duplicate after you annotate it).

Two of the four are exact or semantic duplicates; two carry a key that cannot
be stood behind, and their good twin already holds the question:

  q_claim_2025_computer-studies_64092            twin 64345  (same question;
      "Fire fox" is a typo of "Firefox" — the twin spells it correctly)
  q_claim_2025_accounts-principles-of-accounts_75201  twin 75116 (same
      question, options reordered; both key "provisional general warrant")
  q_claim_2025_accounts-principles-of-accounts_75166  twin 75175 (same stem,
      different options; its key "Bank note" is not an accounting source
      document — the twin's "Journal proper" is the standard answer)
  q_claim_2025_hausa_76200                      twin 75986  (same proverb, but
      its options hold no reading of "one hand cannot lift a corpse"; option a
      "A taimaka wa juna" is the meaning of a different proverb)

Run from the repo root. Writes data/questions.json and data/verifications.json
(file first, Turso second — the deletions in Turso are the follow-up step, and
tests/turso_parity.rs is what proves they landed).
"""

from __future__ import annotations

import json
from pathlib import Path

QUESTIONS = Path("data/questions.json")
VERIFICATIONS = Path("data/verifications.json")

# id -> (twin kept, why)
DROPS = {
    "q_claim_2025_computer-studies_64092": (
        "q_claim_2025_computer-studies_64345",
        'same question; "Fire fox" is a typo of "Firefox"',
    ),
    "q_claim_2025_accounts-principles-of-accounts_75201": (
        "q_claim_2025_accounts-principles-of-accounts_75116",
        "same question, options reordered; both key the provisional warrant",
    ),
    "q_claim_2025_accounts-principles-of-accounts_75166": (
        "q_claim_2025_accounts-principles-of-accounts_75175",
        'same stem, different options; "Bank note" is not a source document',
    ),
    "q_claim_2025_hausa_76200": (
        "q_claim_2025_hausa_75986",
        "same proverb; its options hold no reading of it",
    ),
}


def main() -> int:
    questions = json.loads(QUESTIONS.read_text())
    ids = {q["id"] for q in questions}
    for drop, (twin, _) in DROPS.items():
        if drop not in ids:
            print(f"ABORT: {drop} is not in the bank")
            return 1
        if twin not in ids:
            print(f"ABORT: twin {twin} is missing — dropping {drop} would lose the question")
            return 1

    kept = [q for q in questions if q["id"] not in DROPS]
    QUESTIONS.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + "\n")

    verifications = json.loads(VERIFICATIONS.read_text())
    kept_v = [v for v in verifications if v["question_id"] not in DROPS]
    VERIFICATIONS.write_text(json.dumps(kept_v, indent=2, ensure_ascii=False) + "\n")

    for drop, (twin, why) in DROPS.items():
        print(f"dropped {drop} — kept {twin} ({why})")
    print(f"questions {len(questions)} -> {len(kept)}")
    print(f"verifications {len(verifications)} -> {len(kept_v)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())