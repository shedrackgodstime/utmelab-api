# Pilot 001 — Newton’s Second Law

Status: pilot/draft. Not production data. Purpose: test the OpenLearn tree and conventions on one real capture end-to-end.

Source: `utmelab-bank/data/concepts/phy_m42073.json` (“Newton’s Second Law of Motion: Concept of a System”).

Extraction notes: `openlearn/work/extract-newtons-second-law.md`.

## What this pilot tests

- Concept vs Statement vs Relation separation.
- One underlying empirical Statement with verbal + mathematical formulations.
- Named law as a Concept anchor (not a sixth primitive).
- Study container vs Knowledge; worked examples as Study.
- External layer with zero placements.
- Source attribution/license and fidelity notes.
- Flat JSON references (no DB/tooling yet).

## Files

- `source-attribution.json` — source/license record.
- `source-fidelity.json` — fidelity/flag notes tied to source refs.
- `concept-newtons-second-law.json` — Concept anchor for the named law.
- `statement-newtons-second-law.json` — the empirical law Statement (verbal + mathematical formulations).
- `statement-related-to-first-law.json` — Statement asserting the relation to the First Law.
- `relation-related-to-first-law.json` — reified Relation (pilot only).
- `study-topic-section.json` — Study container/topic + block-role notes.
- `external-placement.json` — external placement record (empty in this capture).

## Review questions

1. Do the IDs/refs work without a DB?
2. Is `concept:newtons-second-law` the right anchor, or should the law be purely a bundle record?
3. Does the Relation need reification, or is `statement:...related-to-first-law` enough?
4. Are Study block roles sufficient, or do we need per-block pointers?
5. Is `CC BY-NC-SA 4.0` acceptable for the intended use? (This capture says non-commercial staging.)

## Not done

- No migration, no schema commitment.
- Full block coverage still pending (blocks 64, 67, 68–124 not individually classified).
- No app code, validation tooling, or storage decisions.
