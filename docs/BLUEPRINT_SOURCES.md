# Blueprint sources — per-topic question counts

**Status:** research note behind **D63**. The decision log is the law; this file is
the provenance record. Every row in `data/blueprints.json` points here.

**Rule (D63):** JAMB publishes no per-topic counts, so nothing here is official.
Each row carries `source` + `sample` + `method` + `confidence`. A consumer can
tell TestDriller-17yr from JAMB-official because they are never in the same field.

---

## S1 — TestDriller 17-year analysis (Mathematics, topic-level)

* URL: `https://www.testdriller.com/151445261/concise-jamb-mathematics-syllabus-with-number-of-question-analysis`
* What: per-topic % of questions across **17 years** of JAMB Mathematics papers.
* Granularity: 31 named rows, sums to **100.00%** — a complete partition, the
  strongest third-party source found.
* Use: folded onto our 23 catalog topics (31 → 23, folding noted per row, e.g.
  `INDICES 2.23` + `LOGARITHMS AND SURDS 4.02` → `indices-logarithms-and-surds 6.25`).
* Confidence: **high** (large sample, complete partition, topic-level).

## S2 — Examkits 2026 syllabus guide (8 subjects, section-level)

* URL: `https://examkits.com/blog/2026-jamb-syllabus-guide-complete-subject-topics-tips-strategies-for-utme-success/` (2025-11-28)
* What: section-level % bands for English, Mathematics, Physics, Chemistry,
  Biology, Economics, Government, Literature.
* Granularity: **sections, not topics** (e.g. Physics: Mechanics 25%,
  Electricity 25%, Waves 20%, Heat 15%, Modern 15%). No sample size stated.
* Use: stored as `level: section` rows with member topic slugs listed. **Never
  even-split to topics** — that would be fabrication with a source attached.
* Confidence: **medium** for section shares, bands not points (stored as low/high).

## S3 — StudyRoadmap weightage cues (planning only)

* URL: `https://studyroadmap.in/exams/jamb/syllabus/`
* What: 1–5 weightage cues per topic across 4 subjects. Explicitly *"a planning
  tool, not a guarantee of question counts."*
* Use: **not ingested** — recorded so nobody re-discovers it. Right attitude,
  wrong precision for a blueprint.

## S4 — Psychometric content-validity paper (coverage evidence)

* What: peer paper comparing WAEC/NECO/NABTEB/JAMB items against syllabi;
  all four boards cover **>80%** of syllabus, spread "fairly adequate".
* Use: evidence that **no fixed official blueprint exists** — rotation is real,
  so blueprint rows are expectations with variance, never promises.

## S5 — Our own Turso table (future primary source)

* What: ~65k real JAMB rows (1978–2025) already held. Once questions carry
  `subtopic_id`, our own per-topic distribution (sample of thousands, our
  syllabus mapping, recomputable) replaces S1/S2 topic by topic.
* Use: the end state. S1/S2 seed the blueprint today; S5 absorbs them.

---

## Coverage matrix (JAMB subjects in catalog)

| Subject | Topics | Blueprint level | Source |
|---|---|---|---|
| mathematics | 23 | topic (all 23) | S1 |
| use-of-english | 3 | topic ranges (all 3) | S2 |
| literature-in-english | 5 | topic (85% mapped, 15% overlap residual noted) | S2 |
| physics | 39 | section (5 rows) | S2 |
| chemistry | 18 | section (5 rows) + 5 unmapped | S2 |
| biology | 23 | section (5 rows) + 3 unmapped (evolution) | S2 |
| economics | 23 | section (6 rows) + 11 unmapped | S2 |
| government | 32 | section (4 rows, all 32 covered) | S2 |
| geography | 24 | section (5 rows) + 1 unmapped (ecowas) | S2 |
| agricultural-science (48), arabic (5), art (13), christian-religious-studies (52), computer-studies (32), french (4), hausa (23), history (43), home-economics (25), igbo (13), islamic-religious-studies (17), music (28), physical-education (35), principles-of-accounts (18), yoruba (20) | 375 | unmapped (subject rows, members listed) | — |

Every catalog topic appears in `blueprints.json`: as its own row, as a section
member, or in an unmapped subject's member list. Mapped topic rows: 31.
Section rows: 30. Unmapped subject rows: 15 (+2 unmapped-member rows for
chemistry/biology/geography remainders).
