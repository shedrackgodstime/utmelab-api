---
name: Release blockers
description: Every blocker between the current bank and a defensible launch, with the one that decides the others
---

# Release blockers — written down 2026-10-14

The brief for this file: nothing stays in a chat. Every open item is here with
its number, its owner (human / syllabus / code), and the gate that closes it.

**Order matters.** Access is first because it is the only blocker that makes
the rest unobservable: until keys exist and requests are authenticated, nobody
can see what the bank actually serves, and "is it ready?" has no answer.

---

## 1. Access — the blocker that decides the others

**Today:** `GET /api/v1/questions`, `/keys/me`, `/novels/*` and `/reports/*`
take a `Caller` and are metered. **`/api/v1/papers/{exam}/{subject}`,
`.../score`, `/api/v1/blueprints/*`, `/api/v1/exams/*`, `/syllabus`,
`/coverage`, `/topics/*`, `/health`, `/openapi.json` take no key at all.**

| Surface | Key today | Answers on the wire? | Verdict |
|---|---|---|---|
| `/api/v1/questions` | yes | only with `include_explanation=true` | correct |
| `/api/v1/papers/{exam}/{subject}` | **no** | never | **a full-length paper, free** |
| `/api/v1/papers/.../score` | **no** | never | reveals correctness for guesses anyone can make unauthenticated |
| `/api/v1/blueprints/{exam}/{subject}` | **no** | never | the readiness account is a product asset |
| `/api/v1/exams/{exam}/papers` | **no** | never | scheme + readiness |
| `/health`, `/openapi.json` | **no** | never | fine, these are public by nature |

**Why this is a real blocker, not a nit.** Assembly is the product: a consumer
can call it 25 times and hold 25 complete JAMB papers with no key, no meter,
and no record of who asked. The bank was reviewed question by question at real
cost; that work is currently given away at the front door.

**Options, in the order I would take them:**
1. **Key the paper surface** — papers, score, blueprints. Same `Caller` seam as
   `/questions`; keep the meter on them. `/health` and `/openapi.json` stay
   public.
2. **Key the two that leak value** (papers, score) and leave the catalogue tier
   (syllabus, coverage, topics, blueprints) public as a marketing surface.
3. **Rate-limit by IP only, keys later** — weakest; it does not meter a paying
   consumer and it does not attribute usage.

**Gate:** an unkeyed `POST /api/v1/papers/...` returns 401, and a keyed one
spends a token and appears in the meter. A test pins it so it cannot regress.

**Also needed:** no accounts, no sessions, no web (D53) — so a key is the only
identity there is. Whoever holds a key is untraceable to a person. That is
acceptable for v1 and is stated plainly rather than hidden.

---

## 2. Content that cannot be answered as served — **mostly closed**

A question that points at a stimulus we do not hold is a coin flip, not a
question. These are not "thin" — they are **wrong**, and they were counted as
content until this audit.

**What the audit found (2026-10-14), from a new gate `tests/answerable.rs`:**

| Rows | Finding | Action taken |
|---|---|---|
| English `74769–74773` (5) | promised a bird passage; the source publishes it on the same page | **recovered** — one passage document, five rows linked, explanations written, all five now verified |
| Commerce `75442` (1) | "use the information below" with no information | **recovered** — the data block is on the page; written as a `Data` passage, stem corrected to the real question ("Calculate the working capital"), explanation shows the working, now verified |
| English `74779` (1) | "Fill in the gap labelled 11", marked **`verified: pass`** | **dropped** — its only stimulus on the source is the numbered gap list with every option printed in it. That is a key sheet, not a passage. Nothing we can honestly hold answers it, so the row goes and a verification claim that was never true goes with it |
| Arabic 10, French 6, Hausa 8, Igbo 6 (33) | announce "read the passage below" | **not broken** — on this source those languages render the stimulus inside the `<h1>`, so the harvester merged passage and question into one stem. The rows carry their own stimulus and are answerable. The gate now knows the difference (200 characters of substance after the announcement) |
| English `74804–74811` (8) | "choose the option that best completes the gap(s)" | **not broken** — each carries its own sentence inline |
| Music 4 rows | figures already attached | contested *keys*, not missing stimuli — see §4 |

**Why it went unnoticed for years:** the guard written to catch exactly this
(`to_question`'s `CLOZE_HINT` check) tested `parsed.get("passage")`, and
`parse_detail` never set `passage` — it was reading the stimulus into a `ref`
field nothing consumed. The guard was written and **inert**. Both are fixed: the
harvester now reads the stimulus off the page (`extract_passage`) and refuses any
row whose stem announces a stimulus it could not extract, and the bank-side gate
fails if one appears anyway.

**Remaining in this class:** none known. **Rule adopted:** a passage question
with no passage is *filled from the source or dropped* — never kept. The gate is
`tests/answerable.rs` (three tests), and the repair tool is
`tools/recover_passages.py`.

## 3. Syllabus gaps — **checked against the source; they are not ours**

The assumption behind this section was that our catalog was a partial mirror of
JAMB's syllabus. Checked on 2026-10-14 against the syllabus source we import
from (which states it is verified against JAMB's IBASS e-syllabus), it is not:

| Subject | JAMB's topic count | Ours | Verdict |
|---|---|---|---|
| History | 43 | 43 | **complete** — and none of the 43 is world history |
| English Language | 3 (Comprehension/Summary, Lexis and Structure, Oral Forms) | 3 | **complete at topic level** |
| Agricultural Science | 48 | 48 | **complete** |
| Physics | 39 | 39 | complete |

**So the real finding is the opposite of the assumption: the 2025 History paper
asks about things JAMB's own syllabus does not list.** The French Revolution,
Treaty of Versailles, Bretton Woods, NATO, the Cold War, the Battle of Hastings
and the Cuban Missile Crisis are all in our 2025 paper and in none of JAMB's 43
topics. That is 24 of 79 rows (30%) of the paper.

**What this means for us, and the decision it forces:**

- Our catalog is faithful to the syllabus. Nothing to "fix" in the import.
- Those 24 rows cannot be filed under a syllabus topic without lying about where
  they come from, and leaving them untagged makes them undrillable.
- **Options:** (a) leave them untagged and reported (current state — honest,
  undrillable); (b) add an explicitly labelled `out-of-syllabus` bucket per
  subject, with our own period subdivisions, so drills work and nothing claims
  it is JAMB's; (c) map each to the nearest syllabus topic, which pollutes the
  drill a candidate actually sits for.
  My recommendation is **(b)**, clearly named so a consumer can exclude it — the
  rows are real 2025 questions and candidates were asked them.

**Two smaller, genuinely fixable gaps:**
- **English has no `comprehension` subtopic**, although JAMB's topic is literally
  "Comprehension/Summary". Ours splits it into `fiction` and `cloze` only, so five
  passage questions had no honest home. Adding `comprehension` under the topic is
  faithful to JAMB's own wording. *Gate:* the six English rows are taggable.
- **One agricultural-science row** ("which is NOT a function of livestock") has no
  exact home; JAMB lists no such topic. One row, recorded rather than forced.
- **Animal husbandry and civic education are not JAMB subjects** (WAEC/NECO). We
  hold one row each and no catalog, which is correct by construction — not a gap.

## 4. Fragility: two subjects with no margin

| Subject | Paper size | Verified | Headroom |
|---|---|---|---|
| **yoruba** | 40 | 40 | **0** |
| music | 40 | 42 | 2 |

Both serve today. **Any** park, quarantine, duplicate removal or key fix in
either one closes its paper gate, and the 409 will say exactly what is short.
Yoruba at zero is a standing single point of failure for a launch subject.

**Gate:** either build real margin (author or harvest into both), or write the
zero down as an accepted risk with a named owner.

---

## 5. Content still open, counted

- **52 unverified rows** (french 5, music 5, geography 4, computer-studies 4,
  hausa 4, and a tail). Six English rows left this list on 2026-10-14 when the
  passage recovery made them answerable. **Commerce 79 → 79 verified** (working
  capital row recovered and verified).
- **13 rows in quarantine** — neither content nor a decision. Fix or drop.
- **3 rows untagged** — all with recorded reasons:
  - `animal-husbandry`: no catalog topics exist (WAEC subject we serve one row of)
  - `agricultural-science`: 1 row ("functions of livestock") has no exact subtopic match
  - `civic-education`: no catalog topics exist (WAEC subject we serve one row of)
  **History 24 → 0**: world-history bucket created, all tagged `out-of-syllabus`.
  **English 6 → 0**: `comprehension` subtopic added, 5 birds passage rows + 1 headmaster row tagged.

---

## 6. Ops

- **Turso has no backup job.** Content tables re-seed from `data/`; the
  **verification log is in git; the key store has neither**. A lost database
  means rotating every key ever issued.
- **The host is stale on the docs path.** Its deploy script and Caddyfile still
  point at `web/` after the 2026-10-12 rename to `site/`. Worked around inside
  the release tarball (a `web → site` symlink) so nothing on the host had to be
  mutated; the real fix is re-running `docs/deployment/vps-onetime-setup.sh`.
- **No uptime check** on `/health`, which is the one endpoint worth watching
  (bank version, subjects, questions, withheld count).
- **Repo access is partial from this machine:** no admin rights, so a failed
  workflow cannot be re-run (a re-run needed a tag delete/re-push), and deploy
  secrets cannot be read or written.

---

## What is *not* a blocker

- **One cohort (2025 only).** Every paper is `mode: "count"`; blueprint mode is
  dormant by design and activates itself when a second year lands (D71).
- **Harvest for 2025 is exhausted.** More content means older cohorts or
  authoring — both fine, neither is a defect.
- **The D-rows.** Ratified (D53, D67–D72). The arithmetic in
  `docs/QUESTION_BANK_DECISIONS.md` is the law for whatever follows.