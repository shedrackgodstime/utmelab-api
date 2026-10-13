# HANDOFF — utmelab-api

**Read this first if you are a fresh session.** It is the map; the decision log
is the law; this is what you need to not repeat our mistakes.

Repo: `/data/data/com.termux/files/home/projects/UTME-Lab/utmelab-api`
Remote: `github-shedrackgodstime:utmelab-api` · branch `main`
Parent repo `UTME-Lab` **ignores this directory** — it is a separate product.

> **Renamed `web/` → `site/` (2026-10-12).** The docs/dashboard project was
> `web/`; it is now `site/`, and it is an **npm** project (`npm ci`), not bun.
> It ships in the release as `release/site/` and Caddy serves it from
> `/opt/apps/utmelab-api/current/site`. The deploy gate and Caddyfile on the VPS
> are *installed copies* that still hold the old name — re-run
> `bash docs/deployment/vps-onetime-setup.sh` there before the next deploy, or
> the gate rejects the release. Full note in
> [`deployment/README.md`](deployment/README.md). Dated records
> (`API_REVIEW.md`, `QUESTION_BANK_DECISIONS.md` D32, `KEY_LIFECYCLE_PLAN.md`)
> still say `web/` on purpose — they describe the tree as it was at the time.

---

## 1. What this is

A commercial question-bank API for JAMB/WAEC/NECO. Five surfaces: the bank
(questions), the catalog (subjects/topics/subtopics/syllabus), keys and rate
limiting, the report intake, and a static docs tier. It is also the eventual
backend for the user's own UTME-Lab app.

## 2. Build and test

```bash
cargo build
cargo test                 # must be green before any push
cargo clippy --all-targets # must be clean
cargo fmt
cargo run -- openapi --out site/openapi.json  # regenerate the spec after route changes
```

**All tests are green** (105) and clippy is clean as of 2026-10-13. The D53
key work's `key_prefix` (first 11 chars of `sk_…`, support lookup only, never
authenticates) is intended and covered by tests — the earlier "one test is red"
note was written from a pre-merge view and is resolved.
## 3. Where the decisions live

| file | what it is |
|---|---|
| `docs/QUESTION_BANK_DECISIONS.md` | D1–D63. The law. Each row states the rule, its status (PINNED/DEFERRED/REJECTED/SUPERSEDED) and its grounds. |
| `docs/TODO.md` | what is next, and why something is not |
| `docs/UNDERLINE_PROBLEM.md` | the largest open defect; read before touching English |
| `docs/RICH_TEXT_HANDOFF.md` | **D60/D61 `RichText` — implemented P1.** Why `emphasis`/`image` became one mark array on every text field; open questions it answered |
| `docs/API_REVIEW.md`, `docs/KEY_LIFECYCLE_PLAN.md` | from the D53 key work |

## 4. Current state

```
2,288 questions (2,287 servable + 1 withheld fixture) · 25/25 JAMB subjects clear 40 · all year 2025
277 verified (12%, derived from data/verifications.json, D62) · 282 explained
withheld: 6 (5 stub novels + the deliberate unassigned-exam fixture, D58)
catalog: 566 topics, 2,092 subtopics + data/blueprints.json (D63, provisional)
novel:   the featured set text has 54 verified questions (+125 honest unverified)
bank_version in /health changes only when content changes
```

2026-10-13 (P1): RichText landed (D60/D61) — every text field is
`{text, inline}`, `emphasis`/`image` fields deleted, loader enforces
bounds/overlap/https, `tools/` map markup to marks, `verified` derives from
the log (D62, 188 legacy seeds). Quarantine 102 (the `debatable` false
positive fixed; figure findings never void verification).

2026-10-13 (P0): inbox import admitted 128 — all 128 were Lekki Headmaster
novel dupes already held (zero key conflicts), dropped from the bank; 1
pre-existing bank row (Mr. Nku) moved verbatim into the novel doc
(`verified:false`); 25 inbox files archived to `data/inbox/archive/`, the
staged `lekki-headmaster-candidates.json` stays. Bank 2,289 → 2,288; novel
doc 178 → 179. Quarantine steady at 103 (78/11/10/4).

2026-10-11 evening: 83 more Lekki/Bepo/Stardom rows found in the English bank
(the D35 guard only scanned character names — multi-word titles and setting
names slipped through) and moved verbatim into the novel doc (original ids,
`verified:false`). Bank 2,371 → 2,288; novel doc 95 → 178. `image` is now
`{url, position}` (D55); `emphasis` is live (D54).

Per-subject question counts and the catalogue are in `data/subjects.json`,
`data/topics.json`, `data/subtopics.json`, `data/questions.json`.

## 5. The rules that are easiest to break

These are the ones that have actually been broken this week. They are not
obvious from the code.

1. **D35 — a novel is its own domain.** Novel questions live in
   `data/novels/<slug>.json`, never in `data/questions.json`. 77 leaked into the
   English bank before we caught it. `tests/store.rs::no_question_in_the_bank_depends_on_a_novel_we_hold`
   now guards it. **The lesson: read the decision log before touching content.**
2. **D45 — `verified` means *reviewed*, not *sourced*.** Never set it in an
   import or a harvest. 97 rows once carried it purely because they came from
   the old bank; a hand-check found two with wrong answers and explanations
   written to justify them.
3. **D47–D49, D52 — provenance.** `source` is `past_paper`, `claimed_paper`,
   `authored` or `imported`. `year` means **the cohort the question is prepared
   for**, not the paper it was lifted from, and is required on every row.
4. **D51 — three gates.** Admissible (mechanical, the only gate that blocks
   entry), explainable (not a gate), sellable (`verified`). A question with no
   explanation is honest; a question with a *fabricated* explanation is poison.
5. **D15/D46 — `Option { id, text }`, answer by id, label never stored; JAMB is
   four options.** Never store a label or an index.
6. **D50 — objectives live on the topic, not the subtopic**, because that is the
   level JAMB states them. `weight: 0` means *not published*, never *worth
   nothing*.
7. **D23 — routes never touch storage.** `JsonStore` is a dev store; Turso
   arrives behind the same trait.

## 6. Tooling

```bash
# harvest (on GitHub Actions — the phone is slow and hot)
gh workflow run harvest -f subjects=<slug|all> -f year=2025 -f delay=2
gh run list --workflow=harvest --limit 5
gh run view <id> --log | tail -40

# merge harvested rows into the bank (never sets verified)
cargo run -- import --dry-run     # report first, always
cargo run -- import

# syllabus trees — one command per subject
python3 tools/import_syllabus.py --subject <site-slug> --display "<JAMB name>" \
        [--catalog-slug <our-slug>]
```

The crawl runs in CI because it is a multi-hour job on a bad phone network:
**CI does ~19 questions/min, the phone managed 2–6.** Politeness (single
worker, 2s spacing, identified user agent) lives in `tools/harvest_all.py` and
holds wherever it runs.

**One subject map**: `config/harvest.json`, read by both the Python crawler and
the Rust importer, with a test that fails if it and `data/subjects.json`
disagree. Two lists is how subjects drift.

## 7. Open work, in the order it should be done

1. **The 78 underline questions** (`docs/UNDERLINE_PROBLEM.md`) — **backfilled
   2026-10-13**, all carrying `Underline` marks (quarantine clean on the
   kind). Answerable as served; `verified` needs a human pass each — review
   work, in batches of ~50 via `review.py`, checking the answer by computing
   it. Known suspect: `t76545`'s key (`bought`→*son*).
2. **Verification and explanations** — English batches 1–3 done 2026-10-13
   (85 rows verified + 19 italic-marked rows re-verified; English 67 → 152).
   Figure-hint scan refined per-hint (figure/table exact-only — `figures` as
   numbers no longer fires), which unblocked `sentinterp_001`. Caught and
   fixed in review: `t76545` wrong key (son→port, explanation rewritten),
   `t76459` confused body sentence (removed), `t76569` loose clause
   (alveolar /n/ vs velar /ŋ/, corrected). Review in batches of ~50 via
   `review.py`, checking the answer by computing it, not by trusting the
   key. Parked: `t74853` (`wound` noun/verb ambiguous with no context —
   needs an authoring fix, not a verdict).
3. **Physics batch 1 done 2026-10-13** — 29 explanations authored (every key
   recomputed from first principles) + verified; physics 1 → 30. The D56
   plainness gate caught my own `<` in authored prose before it shipped.
   `shm_002` stays parked (flagged, figure stripped — mirror job). The
   74358 diagram fetched and read by eye: concentric circles = straight
   conductor, key confirmed.
4. **Physics batch 2 done 2026-10-13** — 29 explanations authored (keys
   recomputed) + verified; physics 30 → 59. Three figures fetched and read
   by eye: 74489 circuit (Z ≈ 163.5 Ω, key confirmed), 74493 refraction
   (sin r = 0.5/1.5 ≈ 0.3, key confirmed). **74492 parked**: figure states
   no weight, yet statics from the readable figure gives T = 20 N against
   recorded 19.24 — underdetermined, needs authoring fix or better scan,
   never a verdict. `shm_002` stays parked (mirror job).
3. **Subtopic tagging** — 2,175 questions belong to no drill path despite 2,092
   subtopics existing.
4. ~~**6 novel questions still in the English bank**~~ — **resolved 2026-10-11**: the subject-scoped D35 guard caught **45** misfiled Lekki Headmaster questions (the "This question is based on…" rows plus the Bepo/Stardom/relocation set that named characters). 41 moved into the novel document verbatim (their rescue convention: original ids, `verified:false`), 4 exact duplicates of rows already in the novel doc dropped from the bank. Bank 2,416 → 2,371; novel doc 54 → 95 questions. All `verified:false`, `explanation:null` — honest.
5. **71 images** still on the source's CDN (absolute URLs, all `above`); the user deferred the mirror to a
   future CI job plus an asset repo.

## 8. Traps we have already hit — do not walk into them again

- **`git diff` ignores untracked files.** The harvest workflow used
  `git diff --quiet -- data/inbox`, so the *first* harvest of every new subject
  was discarded. Use `git status --porcelain`.
- **`which gh && gh auth status || echo "missing"`** prints "missing" whenever
  *auth* fails, not only when gh is absent. Check the tool and the auth
  separately.
- **HTML entities.** The harvester must call `html.unescape`, not a
  hand-written table; 139 questions shipped with `&rsquo;` and `&eacute;` in
  their stems. Hand-enumerating just moves the failure.
- **Deduping is by content fingerprint, not id.** Two ids can hold the same
  question, and a re-harvested row can have a *new* fingerprint and an *old* id
  once the bank has been cleaned. The importer guards both.
- **Tests must assert invariants, not snapshots.** Three tests broke on content
  growth because they quoted a number ("five maths questions"). If a test names a
  count from the bank, it is wrong.
- **Scan every page in a test.** A guard that read only page 1 (200 rows) missed
  six novel questions hiding at rows 201–282.
- **A check that fires wrongly is a bug in the check**, not in the data — three
  times this week (a subtopic deletion, a "subject missing" report, and a novel
  match on the name "Sola").

## 9. How we got here, in one paragraph

The bank started at 155 questions with `verified` meaning "came from a scrape".
An audit of 133 rows by hand found six wrong or broken questions and two where
no correct answer was offered; provenance was rebuilt (`source`, `year`,
`claimed_paper`); a harvester and an importer were written; the catalogue went
from 6 subjects to all 25 with 566 topics; and Mathematics was reviewed and
explained end to end. The remaining gap is not volume — it is review.