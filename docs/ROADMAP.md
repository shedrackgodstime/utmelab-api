# ROADMAP — utmelab-api implementation plan

**The single plan.** Phases P0→P4. Status 2026-10-13: **P0 done** (`43f1115`),
**P1 done** (`bf4295f`), **D61 proven** (`97f18bd`), **78-backfill done**
(`e76d61a`). Next: English review batches, then P4.

Each phase below carries goal / decisions / touches / acceptance / DO NOT.
`TODO.md` holds work items moved out of here; the decision log
(`QUESTION_BANK_DECISIONS.md`, now D1–D64) is the law. No code without a
D-row (D7).

> External review (`site/temp-chatgpt-review.md`) was read, its takes folded
> into this plan below (see §6), and the file deleted. Nothing lives in chat.

---

## Anti-drift rules (apply to every phase)

1. **D7 gate.** New need → new decision row first (what, status, why), then code.
2. **Phase gates.** A phase exits only when these pass together:
   `cargo test` green + `cargo clippy --all-targets` clean + `cargo fmt --check`
   + `cargo run -- quarantine` count not up + `cargo run -- openapi --out
   site/openapi.json` regen'd.
3. **Tests are the leash.** Boot-fails-on-bad-data, openapi drift test (calls
   every route), withheld round-trip (D58), quarantine read-only,
   `bank_version` stability. A guard that fires wrongly is a bug in the guard —
   fix it same commit.
4. **Small, dry-run-first commits.** `import --dry-run` before `import`,
   `propose` before `apply`. One phase per commit, message names the D.
5. **DO NOT (global).** No deprecation aliases; no block/document model; no
   `emphasis` resurrection; no WAEC-theory smuggling into RichText; no
   `verified:true` on quarantined rows; no hotlink without the https gate.

---

## P0 — Baseline ✅ done (`43f1115`)

* Goal: clean slate, inbox resolved, docs synced.
* `cargo run -- import` (admits ~128, refuses counted), archive `data/inbox/`.
* Record quarantine baseline (~103). Sync `README.md` (`site/`, D1–D63).
* Acceptance: gates green, inbox empty-or-archived.

## P1 — The one schema break ✅ done (`bf4295f`; D61 proven `97f18bd`)

* Goal: land RichText everywhere + verification log in one breaking window.
* Answer `RICH_TEXT_HANDOFF.md` §6 first: `<p>`→`\n\n` / `<br>`→`\n`; keep
  `position` on `Image` (`Image{url,position,alt?}`, zero-length anchor);
  offsets = Unicode scalars; LaTeX `\(…\)` stays plain, never inside a mark.
* Then §7 order: Rust types + bounds/overlap tests first → 2,289-row migration
  (`{text}` → `{text,inline}`) → `json.rs:369` substring→bounds check →
  `import.rs`, `quarantine.rs`, harvester `clean_inline/clean_blocks`,
  `propose_emphasis.py` retired-or-retargeted, `review.py` →
  `openapi.rs` + regen → docs sync.
* D62 in the same window (same files): `Verification` log, hash-void rule,
  `review.py verify` appends a row instead of flipping a bool, legacy
  `verified:true` rows seed `Human/Pass {legacy-import}`.
* DO NOT: backfill the 78 on the old shape — that writes every row twice.
* Acceptance: gates green + harvest of one subject end-to-end proves D61.

## P2 — Pipeline honest (D49/D51/D56/D57 carry over)

* Harvester maps markup→marks 1:1, `html.unescape`, keeps 5th options,
  never writes explanations; `FIGURE_HINT` still refuses diagram-less rows
  (bank stays filtered output — D61).
* Import 3 gates unchanged, every refusal counted; withheld round-trip guarded.
* Quarantine on new predicates (missing `Underline` mark, bad `Image` mark,
  dupes on plain `text`, cloze gaps, counts, novel leaks).

## P3 — Content moat (in progress; 78-backfill done `e76d61a`, review batches next)

* 78 underlines → `Underline` marks (syn/antonym semi-auto, stress/sound by
  hand). Image-mirror decision (hotlink dies = broken stems). Passage bench.
* Verify in ~50-row batches via `review.py` (compute answers, don't trust keys;
  word-stress double-checked — 2/11 wrong before). English first (60/180),
  then Maths/Phys/Chem/Bio, then Computer + PHE (competitor gap).
* Blueprints (D63, done — `data/blueprints.json`, 80 rows, all 566 topics):
  wire opt-in only (`?include=blueprint` / `/blueprints/{exam}/{subject}`),
  never default. S5 replaces S1/S2 as tagging lands.
* Paper assembly stays scheme+readiness (D41) until 180 verified (~103 today).
* Acceptance: English fully verified, quarantine English count → 0.

## P4 — Expose (naming + vertical slice)

* Count naming (review point 2): `full_exam_questions` (scheme requirement) vs
  `summary.questions` (held) vs `questions_available` (fillable) — rename in
  docs/spec, no new fields. Readiness = blueprint × coverage (verified,
  deduped), never raw totals.
* Readiness per topic once blueprints + tagging meet; until then
  `complete:false` is the honest answer.
* Milestone (review point 3): **one complete subject** (Mathematics — measured
  blueprint + 58/60 verified) flowing source → model → API → real paper. Tests
  architecture against content before scaling.
* O2/O3/O5 (exposure shape, 68k port, tiers) stay open until content is
  sellable. Study notes (D18) stay deferred.

---

## §6 — External review takes (folded, file deleted)

* **Adopted now:** verification policy → D62 (bool on wire, log in store);
  count-name disambiguation → P4; vertical-slice milestone → P4; "freeze
  semantics, not implementation" → this roadmap's phase gates.
* **Already in place (verified against code):** max `per_page` 200
  (`json.rs:699`), id-stable ordering (`:718`), same `render()` rule on list +
  detail, RFC 9457 errors, utoipa-derived spec, report queue (D38).
* **Deferred honestly:** commercial access rules / billing (no users);
  `quota_monthly:null` = "not configured".
