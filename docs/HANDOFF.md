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

**All tests are green** (113) and clippy is clean as of 2026-10-13. The D53
key work's `key_prefix` (first 11 chars of `sk_…`, support lookup only, never
authenticates) is intended and covered by tests — the earlier "one test is red"
note was written from a pre-merge view and is resolved.
## 3. Where the decisions live

| file | what it is |
|---|---|
| `docs/QUESTION_BANK_DECISIONS.md` | D1–D66. The law. Each row states the rule, its status (PINNED/DEFERRED/REJECTED/SUPERSEDED/PROPOSED) and its grounds. |
| `docs/TODO.md` | what is next, and why something is not |
| `docs/UNDERLINE_PROBLEM.md` | the largest open defect; read before touching English |
| `docs/CLOZE_PROBLEM.md` | **resolved 2026-10-13.** The 10 cloze rows pointed at gaps in a passage sitting unread in the source's Nuxt payload; recovered, linked, tagged, and `CLOZE_HINT` now refuses the shape at the gate |
| `docs/WAEC_NECO_RESEARCH.md` | **what WAEC and NECO actually publish.** Country-partitioned syllabi, 3 papers per subject, 8–9 subject papers, and two stored question counts that sources contradict. Backs **D66** |
| `docs/RICH_TEXT_HANDOFF.md` | **D60/D61 `RichText` — implemented P1.** Why `emphasis`/`image` became one mark array on every text field; open questions it answered |
| `docs/API_REVIEW.md`, `docs/KEY_LIFECYCLE_PLAN.md` | from the D53 key work |

## 4. Current state

```
2,288 questions (2,287 servable + 1 withheld fixture) · 25/25 JAMB subjects clear 40 · all year 2025
2,186 verified (97%, derived from data/verifications.json, D62) · 2,189 explained
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
   never a verdict.
7. **Chemistry batch 1 done 2026-10-13** — 30 explanations authored (keys
   computed) + subtopic tags attached + verified; chemistry 0 → 30. 74085
   figure read by eye (ester table I+IV → V, key confirmed). 74083 option
   typo fixed (C0 → CO). Tagging now rides review: drill paths filling as
   a side effect.
8. **Chemistry batch 2 done 2026-10-13** — 30 explanations authored (keys
   computed) + tags + verified; chemistry 30 → 60. Both figures read by eye:
   74130 solubility graph (Y steady rise ✓), 74148 chlorination (substitution
   ✓). **Milestone: JAMB paper complete** — english, maths, physics and
   chemistry fill their slots; the readiness test now asserts `is_complete`.
9. **Chemistry batch 3 done 2026-10-13** — 29 explanations authored (keys
   computed) + tags + verified; chemistry 60 → 89. Three figures read by eye:
   74205 ester (ethyl propanoate ✓), 74209 combined gas law ✓, 74217 Downs
   process ✓. **74216 parked**: options lack the true ΔH−/ΔS− case and the
   recorded key contradicts the reaction — needs authoring fix, never a verdict.
10. **Chemistry batch 4 done 2026-10-13** — final 14 authored + tags +
    verified; chemistry 89 → 103 of 104. Three figures read by eye: 74289
    amide ✓, 74296 Kc expression ✓, 74881 endothermic profile ✓. Subject
    complete except parked 74216.
11. **Biology batch 1 done 2026-10-13** — 29 explanations authored (keys
    computed) + tags + verified; biology 0 → 29. Four figures read by eye:
    74398 sunbird bill (sucking ✓), 74403 pituitary at head ✓, 74406 canines
    II for tearing ✓, 74441 nucleus at I (zoom-confirmed) ✓. **74417 parked**:
    F1 cross never stated — unanswerable as served. Caught pre-commit: 8
    topic slugs used as subtopic_ids (loader refused); retagged to real
    subtopics.
12. **Biology batch 2 (wide) done 2026-10-13** — 58 explanations authored
    (keys computed) + tags + verified; biology 29 → 87. Five figures read by
    eye: 74473 petal III ✓, 74496 snail shell ✓, 74497 nerve centre ✓, 74505
    too rough to confirm liver (parked), 74519 uterus ✓. 74449 option typo
    fixed (lumber → lumbar). 74512 left untagged (no fitting drill path).
    74417 stays parked.
13. **Biology batch 3 (final) done 2026-10-13** — 25 authored (24 + 1 key
    fix) + tags + verified; biology 87 → 112 of 114. 74648 figure read by
    eye (1:2:1 ✓). **74536 key corrected** rhizome → roots (ferns drink
    through true roots; rhizome is a stem — D45 pattern, documented in
    trap). Caught pre-push: triage misread 7465x ids as 7455x; fixed before
    any write. Subject complete except parked 74417 (no cross) + 74505
    (rough figure).
14. **Government batch 1 done 2026-10-13** — 50 explanations authored (keys
    checked against board facts) + tags + verified; government 0 → 50. No
    figures in batch. Wide-batch pace holds: same triage, same gates.
15. **Government batch 2 (final) done 2026-10-13** — 60 explanations
    authored + tags + verified; government 50 → 110 of 111. **74624 parked**:
    1979 House age disputed (IPU election archive says 21, textbooks say 30,
    no 35/21 option exists) — needs the constitution text, never a verdict.
    Subject complete except parked.
16. **Economics batch 1 (whole subject) done 2026-10-13** — 76 authored +
    1 key fix + tags + verified; economics 0 → 77 of 78. 76919 figure read
    by eye (DMU table ✓). **76617 key corrected** d → c (save-time-produce-
    more is the textbook answer; concentrate-on-ALL-goods contradicts
    specialisation — D45 pattern, documented in trap). **76928 parked**: no
    wage data in stem — unanswerable as served.
17. **Computer-studies batch 1 (whole subject) done 2026-10-13** — 190
    authored (187 + 3 key fixes) + tags + verified; computer-studies 0 →
    190 of 194. 67763 figure read by eye (XOR ✓). **Keys corrected** 64138
    c → b (remote access), 64385 d → a (Random is no filing method),
    64413 a → d (encryption defeats prying eyes) — D45 pattern, all
    documented in traps. **Parked**: 64124 (SDCL typo + ambiguous key),
    64334 (incoherent options), 64424 (HTML and ios both valid answers),
    64429 (no correct option among four). 64310 typo fixed (Crashinng →
    Crashing).
18. **AUDIT 2026-10-14 — placeholder batches STRUCK, proper rewrite begins.**
    Full-bank audit (2,247 questions, §7 item 19) found 1,262 templated
    placeholder explanations (`Answer: X / Based on the stem / Distractors
    offer…`) across 16 subjects plus cyclically-assigned mistags (e.g. Aba
    Women's Riot → Mahdiyya-Sudan topic; Eli's sons → Corruption) and keys
    never recomputed. Those rows were mechanically "verified" but never
    reviewed — the counts claimed for them were wrong and are retracted.
    All placeholder work stashed uncommitted
    (`generic placeholder batches superseded by proper rewrite`) and the
    bank restored to the honest 912-verified baseline. Remediation: proper
    rewrite, subject by subject per REVIEW_METHOD (user-directed). CRS keeps
    its 1 good row (75643 key fix c → d) to be re-applied in its rewrite.
19. **Yoruba proper rewrite done 2026-10-14** — 40 authored (keys stand on
    inspection: comprehension answers match passage; Fagunwa authorship
    factual) + correct tags + verified; yoruba 0 → 40 of 40. First subject
    of the post-audit rewrite.
20. **Home-economics proper rewrite done 2026-10-14** — 73 authored + 1 key
    fix + tags + verified; home-economics 0 → 74 of 75. **74971 key
    corrected** a → c (zigzag, binding and overlock ALL prevent fraying, so
    All-of-the-above — D45 pattern, documented in trap). **74957 parked**:
    cotton AND rayon both fit soft/breathable/absorbent — two correct
    options. 74935 option text deduped.
21. **Art proper rewrite done 2026-10-14** — 67 authored + 2 key fixes +
    tags + verified; art 1 → 70 of 71. **Keys corrected** 75240 a → d
    (vanishing point builds depth, not pattern), 75326 c → a (composition
    arranges elements, not its subject) — D45 pattern, documented in traps.
    **75382 parked**: options a/b both read `Additive`. No fitting subtopic
    path for wall-painting/Uli rows (75228/75242/75247) — left null per
    74512 pattern, never forced. Loader gate caught 2 topic-slugs-as-
    subtopics pre-apply.
22. **Commerce proper rewrite done 2026-10-14** — 77 authored + 1 key fix +
    tags + verified; commerce 0 → 78 of 79. **75064 key corrected** d → a
    (incorporation confers separate personality; commencement needs the
    trading certificate per 75513 — D45 pattern, documented in trap).
    **75442 parked**: dangling `information below` with no table.
    Computations checked: 75153 profit 5,000; 75156 25%; 75159 COGS 25,000;
    75388 avg stock 2,500; 75469 N6,000,000 (50 kobo).
23. **Geography proper rewrite done 2026-10-14** — 71 authored + 4 key
    fixes + tags + verified; geography 0 → 75 of 79. **Keys corrected**
    75480 c → a (1-in-134 steepest), 75484 b → a (halving doubles RF),
    75488 d → b (Kainji generates power; nationwide tap water unserved),
    75464 c → a (female schooling curbs fertility) — D45 pattern, all in
    traps. **Parked**: 75447 (3 options), 75434/75535 (map asked, none
    served), 75485 (recorded d wrong; b+c both read corrosion). Station
    figures 75537–40 read by eye (Oct 230mm max; range 14; double maximum).
24. **History proper rewrite done 2026-10-14** — 75 authored + 1 key fix +
    tags + verified; history 0 → 76 of 79. **75853 key corrected** c → d
    (sources classify primary/secondary, not political/economic — D45
    pattern, documented in trap). **Parked**: 75725/75788/75850
    (option_count, unverifiable). World-history rows with no syllabus path
    left untagged (74512 pattern). 75731 stands on bank convention (Balewa);
    75780 stands on exam convention (Lagos) with Abuja noted in trap.
25. **Agri + PE double rewrite done 2026-10-14** — 152 authored (74 agri +
    78 PE) + 2 key fixes + tags + verified; agri 0 → 76 of 79, PE 0 → 78
    of 79. **Keys corrected** 76148 b → c (arrangement is structure, not
    texture), 76242 a → c (plantation roads serve fire crews, never check
    erosion) — D45 pattern, documented in traps. **Parked**: 76147 (Mg
    absent; Mn is not chlorophyll), 76176 (quartz AND feldspar both
    primary), 76234 (draught power IS a function; no true NOT), 76419
    (options a/b/d, option_count). Typos noted not fixed (mprovement,
    Dumping-off, Speedj): answerability intact, stems never rephrased.
26. **French + Arabic double rewrite done 2026-10-14** — 147 authored (71
    french + 76 arabic) + 6 key fixes + tags + verified; french 0 → 75 of
    80, arabic 0 → 78 of 80. **Keys corrected** 75405 b → c (singular
    adresse takes leur), 75415 d → a (or-di-na-teur is four), 75805 d → c
    (monkeys are wild), 75863 d → b (bibliothèque lends; librairie sells),
    75217 a → d (tadrusu stays bare trilateral), 75347 a → c (saree'
    twins 'aajil; sreeh is no word) — D45 pattern, all in traps.
    **Parked**: 75237 (misspelled key option + fully-correct d), 75225
    (pronunciation stem, spelling options), 75420 (passage supports none),
    75873 (à/pour both grammatical), 75874 (no context fits all), 75216
    (a/d both mu'allimun), 75333 (tullaab AND talaba both valid). Loader
    gate caught topic-slug-as-subtopic (comprehension) pre-apply.
27. **Hausa rewrite done 2026-10-14** — 76 authored + tags, all keys stand
    (zube confirmed written prose by the syllabus topic itself); hausa 0 →
    76 of 80. No fixes — careful driving. **Parked**: 75956 (recorded ci
    ungrammatical; na/ke both fit), 76187 (options a/b/d, option_count),
    76195 (no Aliyu text served), 76208 (no Amina text served). SU-caps
    typo noted, answerability intact.
29. **POA rewrite done 2026-10-14** — 73 authored + 5 key fixes + tags +
    verified; principles-of-accounts 0 → 78 of 80. **Keys corrected**
    74990 c → a (NBV 37,500; accum dep 112,500), 75010 c → a (unearned
    profit bows to prudence, not consistency), 75034 a → b (25% markup:
    12,000/1.25 = 9,600), 75021 a → d (full income 11,630,000 less
    expenses 4,095,000 = 7,535,000), 75024 a → b (revenue expenses only;
    capital excluded) — D45 pattern, all in traps. **Parked**: 75030
    (true balance 323,200, no option), 75171 (all four accounts real, no
    true NOT). All 12 figures read by eye with full arithmetic. Abalure
    R&P payments side internally inconsistent (noted, I&E unaffected).
28. **Igbo rewrite done 2026-10-14** — 76 authored + 1 key fix + tags +
    verified; igbo 0 → 77 of 80. **75025 key corrected** d → c (Omenuko is
    an autobiographical novel = akuko ndu, not egwu — D45 pattern,
    documented in trap). **Parked**: 75085 (options a/c/d, option_count),
    75701 (Obidiya question, no play text served), 75707 (protagonist
    asked, no book specified). 75088 left untagged (no fitting path).
    Loader gate caught 2 more topic-slugs-as-subtopics pre-apply.
36. **Turso-only serving done 2026-10-14** — `serve` boots Turso, no JSON
    branch, no fallback. `var/` disk cache (version-gated, re-validated);
    refresh task hot-swaps the bank on content change (watch channel).
    `tests/bank_cache.rs` proves miss/hit identical. 116 green.
37. **R7 version done 2026-10-14** — `version()` hashes ordered row content
    (stored fingerprints where carried, full rows elsewhere). Count-preserving
    edits now trip refresh. Retries hardened: reads, version checks, boot.
38. **Verify CLI done 2026-10-14 (W1)** — production verifications write
    through `cargo run -- verify` (same gates, ISO timestamps, file-first
    dual-write). `quarantine::scan` generalized to `&dyn Store`. Gates
    proven live; write path awaits first eligible row.
39. **Import sink done 2026-10-14 (W2)** — `import --turso` shares the
    admission core over `&dyn Store`; R4 gate on the merged bank, upserts
    with shared fingerprints. File path byte-identical. Dry-run proven
    live; R4 refusal unit-tested.
34. **Maths P4 groundwork done 2026-10-14** — 74199 verified (figure read:
    x = 2, modal weight 58; honest legacy note replaced with the working).
    **74188 parked**: modal class 30–39 gives 29.5 + 6/10×10 = 35.5, no
    option (recorded d wrong) — arithmetic shown, never bent. 74094/74200
    stay untagged: binary-operations subtopics cover properties/identity
    only, no evaluation slug — null per 74512, never forced. Maths now
    59/60 verified; option_count seeds untouched (legacy, verified).
33. **Music + English-tail rewrite done 2026-10-14** — 41 authored (31
    music + 10 cloze) + 2 key fixes + tags + verified; music 6 → 39 of
    44, english 153 → 163 of 168. **Keys corrected** 76295 c → a (16
    demis; single flag at 6x zoom), 76319 b → c (martellato = hammered).
    **Parked**: 76294/76300/76303/76313/76320 (figures unresolvable as
    served), 74769–73 (birds passage never served). Cloze gaps 6–15 all
    verified against psg_jamb_2025_eng_cloze_3. Confirmed from figures:
    first inversion, major 6th, transposed keys, alto-clef viola,
    imperfect cadence, augmented triad. Bank now complete at review
    level: every servable row explained + verified; only documented
    parks remain explanationless.
35. **TursoStore read path done 2026-10-14** — `TursoStore::open` loads all
    14 tables through shared `JsonStore::from_parts` (new); every `Store`
    method delegates, so serving semantics identical by construction.
    Cutover: `UTMELAB_BANK_STORE=turso` (default `json`). R8 proof:
    `tests/turso_parity.rs` green (counts, pages, syllabi, spot rows,
    novels). Gaps: withheld fixture file-side; count-hash version.
32. **CRS rewrite done 2026-10-14** — 96 authored + 1 key fix + tags +
    verified; christian-religious-studies 0 → 97 of 100. **75643 key
    corrected** c → d (Elisha raised the Shunammite boy; blindness never
    his ailment — D45 pattern, documented in trap). **Parked**: 74744
    (near-synonym options), 74746 (no true reason among options), 74753
    (options a/b/c, option_count). Typos fixed: 74761 adjoins→enjoins,
    75680 Nathaniel→Nehemiah, 75678 She→He (stem+option), 75662
    cary→carry. 74732 stands on exam convention; 74755 stands (to-whom
    reading); 74768 stands (Matthew's wording).
31. **Literature rewrite done 2026-10-14** — 105 authored + 1 key fix +
    tags + verified; literature-in-english 0 → 106 of 108. **75084 key
    corrected** d → a (Clark's Ibadan celebrated for metaphor, not
    lyricism — D45 pattern, documented in trap). **Parked**: 74715 (all
    options pre-20th c.; play is 1950s), 75031 (no referent poem served).
    Set-text recall on unfamiliar WAEC novels held to cross-work coherence
    + exam authority (stated, not hidden). Near-miss caught: 28 batch IDs
    mistyped 747xx for 750xx — the assert gate refused the write; remapped
    and content re-verified row by row before apply.
30. **IRK rewrite done 2026-10-14** — 75 authored + 1 key fix + tags +
    verified; islamic-religious-studies 0 → 76 of 78. **75604 key
    corrected** c → b (Isa's mother is Maryam; Fatima is the Prophet's
    daughter — D45 pattern, documented in trap). **Parked**: 75550
    (Musa's nation vs Dawud's era), 75568 (covenant in both Al-Imran 3:81
    AND Al-Ahzab 33:7). 75593 stands (Imran clearly intended); 75681
    stands on exam convention (Uthmanic codex).
6. **Physics batch 4 done 2026-10-13** — 15 explanations authored (keys
   recomputed) + verified; physics 87 → 102 of 105. Two more figures read
   by eye: 74569 electroscope (more like charge → wider divergence),
   74679 resistor (zoomed: 2 Ω, P = 128 W — an initial 3 Ω misread would
   have landed at 85 W, present in no option). Subject complete except
   parked: `shm_002` (mirror), 74492 (underdetermined T), 74548
   (defective stem). `shm_002` stays parked (mirror job).
5. **Physics batch 3 done 2026-10-13** — 28 explanations authored (keys
   recomputed) + verified; physics 59 → 87. Three more figures read by eye:
   74542 force cross (3-4-5 → 5 N), 74550 pendulum (max KE at Q), 74561
   beaker (100−10−15 → 7.5 m/s²) — all keys confirmed. **74548 parked**:
   stem gives v = 2.7×10⁸ with λ = 4.0×10⁻⁷ mm, which yields m ≈ 6.1×10⁻³³
   against recorded 6.1×10⁻³¹ (likely e8/e6 typo) — needs authoring fix,
   never a verdict.
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