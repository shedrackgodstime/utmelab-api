#!/usr/bin/env python3
"""Explanations for the six rows the passage recovery made answerable.

A question whose stimulus we did not hold could not be explained honestly, so
these were left unverified for years. With the passages recovered (see
`tools/recover_passages.py`), each row can be read and worked:

* five English comprehension questions on the bird-calls passage, recovered
  from the source page the harvester had been discarding;
* one commerce question whose data block had been dropped the same way, with
  the working capital shown.

Written to `data/questions.json` first; verification goes through
`cargo run -- verify`, which refuses a row whose explanation is missing — which
is why these six sat unverified for as long as they did.

Run: `python3 tools/write_recovered_explanations.py`
"""

from __future__ import annotations

import json
from pathlib import Path

BANK = Path("data/questions.json")


def rt(text: str) -> dict:
    return {"text": text, "inline": []}


EXPLANATIONS = {
    # ── English comprehension: the bird-calls passage ──────────────────────
    "q_claim_2025_english-language_74769": {
        "key_point": "The passage opens on how noisy birds are — their calls are what a child notices first.",
        "body": "The very first thing the passage says a child notices about birds is how **noisy** they are: the guinea fowl is \"renowned for this\", and with practice a listener can name the species in a wood from the calls alone. So the answer is **noise**, not nests, feeding or colour.",
        "trap": "\"Feeding trait\" is the tempting one because the passage does mention birds feeding — but it says they call *even while* they are feeding, which makes feeding what happens around the noise, not the noise itself.",
    },
    "q_claim_2025_english-language_74770": {
        "key_point": "It is the calls, and it takes practice to read them.",
        "body": "The passage says birds \"make characteristic calls, and with practice you can tell which species are in a wood just from these calls without seeing the birds at all\". Beak shape, feeding and feather colour are never offered as identification aids here.",
        "trap": "\"Their mode of feeding\" sounds plausible because the passage mentions seeds and insects — but it uses that detail for a different point (keeping flocks together), not for identifying a bird.",
    },
    "q_claim_2025_english-language_74771": {
        "key_point": "They hunt on branches, where a flock can easily scatter.",
        "body": "The passage: \"When flocks of finches are looking for insects or seeds on the branches of trees, they could easily become separated\" — so the answer is the moment they are **hunting for insects or seeds**.",
        "trap": "Predators are the memorable detail in this passage, and they appear one sentence later — as the trigger for the alarm call, not for the separation. The separation sentence names insects and seeds, and the birds are *up on branches*.",
    },
    "q_claim_2025_english-language_74772": {
        "key_point": "Each species' calls are characteristic of that species, hence \"a particular type\".",
        "body": "The passage distinguishes two things: calls in general are characteristic of a **species** (\"which species are in a wood\"), and a bird of prey gets a specific alarm call. So the small birds each have their own **particular type of call**.",
        "trap": "\"Different alarm calls\" and \"a similar alarm call\" both overreach: the passage says calls are characteristic (i.e. species-specific, not interchangeable), and it never says alarm calls are the same across birds or different from each other.",
    },
    "q_claim_2025_english-language_74773": {
        "key_point": "A bird of prey triggers the flying-predator call, which warns the birds nearby.",
        "body": "\"At the sight of a bird of prey, a small bird will give its flying predator call as an alarm to other birds in the neighbourhood.\" The call goes to *other birds* — which is what **calling its mates** describes.",
        "trap": "\"Flies away\" reads naturally but is the opposite of what the passage says: the bird stays and *calls*, precisely so the flock stays together.",
    },
    # ── Commerce: working capital from a data block ─────────────────────────
    "q_claim_2025_commerce_75442": {
        "key_point": "Working capital = current assets − current liabilities, and only current items count.",
        "body": "Current assets: debtors 10,000 + cash in hand 5,000 + closing stock 10,000 = **25,000**. Current liabilities: creditors 8,000 + overdraft 12,000 = **20,000**. Working capital = 25,000 − 20,000 = **5,000**.",
        "trap": "Sales 50,000 and purchases 16,000 are the biggest numbers in the data and belong to **neither side**: they are revenue and cost, not stock, cash or a payable. Adding them is the classic wrong turn.",
    },
}


def main() -> int:
    rows = json.loads(BANK.read_text())
    by_id = {q["id"]: q for q in rows}
    missing = [qid for qid in EXPLANATIONS if qid not in by_id]
    if missing:
        print(f"ABORT: not in the bank: {missing}")
        return 1
    for qid, parts in EXPLANATIONS.items():
        row = by_id[qid]
        if row.get("passage_id") is None:
            print(f"ABORT: {qid} has no passage — an explanation would be uncheckable")
            return 1
        row["explanation"] = {part: rt(text) for part, text in parts.items()}
    BANK.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(EXPLANATIONS)} explanations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())