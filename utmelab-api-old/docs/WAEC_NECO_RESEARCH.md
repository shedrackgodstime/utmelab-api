# WAEC / NECO — what the boards actually publish

**Status:** research note, 2026-10-13. **Landed since:** §4 fixed by small-D66
(counts nulled); §10 rows 1–2 implemented, row 3 superseded by set-membership
joins; pan-African direction noted in §9. **No D-row yet for WAEC content
itself, no WAEC/NECO data changed.**
This is the provenance record for the claims below; the decision log is the law.
Read before touching `subjects.json`, `topics.json` or `scheme.rs` for a
non-JAMB exam.

**Why this exists:** the WAEC/NECO subject rows already exist in
`data/subjects.json` (ruled board names, not guesses — **D65**), and the API
already answers for `WAEC` and `NECO` with an honest empty. This note asks the
question those rows were added without answering: *what does a WAEC or NECO
paper actually look like, and can our model hold it?*

Two answers: **no, not as it stands** — see §1 and §2 — and **yes, with work** —
see §5 and §6.

---

## 1. BLOCKING — a WAEC syllabus is country-partitioned, and `Topic` cannot say so

WAEC is run by five countries (Nigeria, Ghana, Sierra Leone, The Gambia,
Liberia) from one syllabus, and **the syllabi mark which content belongs to
whom.** Two conventions, both from WAEC's own PDFs:

**Section convention** — WAEC Biology syllabus, verbatim:

> "This examination syllabus is divided into three sections: Sections A, B and C.
> Section A is for all candidates, Section B is for candidates in Ghana only and
> Section C is for candidates in Nigeria, Sierra Leone The Gambia and Liberia."

**Asterisk convention** — WAEC Geography syllabus, verbatim:

> "Any topic in the syllabus that is marked with one asterisk (\*) will be for
> candidates in Ghana, Sierra Leone, Liberia and The Gambia. Topics that are
> marked with two asterisks (\*\*) will be for candidates in Nigeria only. The
> topics without asterisk are for all member countries."

**Our `Topic` has no field for this.** `slug, subject, exam, name, order,
weight, objectives` — there is nowhere to record that a topic is Nigeria-only,
or Ghana-only, or shared. So today a consumer asking for the WAEC Biology
syllabus gets one undifferentiated list, and **it would be wrong for four
countries out of five.** A Ghanaian candidate could be told to revise
Nigeria-only content; a Nigerian candidate could be pointed at content that
never appears on their paper.

This is the same class of failure D47 (fake `year`) and D50 (fake `weight`)
exist to prevent — a fact-shaped field that is not true — except worse, because
it is not a missing number, it is a missing *distinction*.

**NECO has no such split.** It is Nigeria-only. So the fix is WAEC-specific.

> Source: `https://waecsyllabus.com/download/ssce/BIOLOGY.pdf`,
> `https://waecsyllabus.com/download/ssce/GEOGRAPHY.pdf` (WAEC's own syllabus
> text, republished). **Confidence: high** — this is the board's own document.

## 2. A WAEC/NECO subject is 3 papers, not 1 — and only one of them is MCQ

Every subject on both boards is **Paper 1/II/III**: objective, essay/theory,
and practical. Our bank is 100% four-option MCQ, so we can only ever serve the
objective paper. That is fine and normal for a question bank — but it is a
decision nobody has written down, and it changes what `full_exam_questions`
means.

**NECO puts the objective paper LAST.** From NECO's official 2026 timetable
(`https://neco.gov.ng/2026%20SSCE%20EXTERNAL%20TIMETABLE.pdf`):

```
1013 Paper III: Objective - English Language    1 hr
1012 Paper II:   Essay     - English Language    1 hr 45 mins
1014 Paper IV:   Test of Orals - English Language 45 mins
1023 Paper III: Objective - General Mathematics  1 hr 45 mins
1003 Paper III: Objective - Civic Education      1 hr
```

Most subjects run as a combined *"Papers III & II: Objective & Essay"* sitting
of 2–3 hours, with Paper I as practical where one exists.

**WAEC keeps the objective first** — Biology Paper 1 is *"fifty multiple-choice
objective questions drawn from Section A … 50 marks and last for 50 minutes"*;
Paper 2 is essay; Paper 3 is practical, 80 marks.

So `full_exam_questions` means **the objective paper's count**, for both boards,
or it means nothing.

**The "answer N of M" problem is worse than one subject.** `scheme.rs` records
it for Elective Mathematics Paper 2 and calls it *"the known, recorded, unsolved
problem."* It is in fact board-wide:

- WAEC Geography Paper 2 — *"nine essay-type questions out of which candidates
  will be required to answer four in 2 hours for 80 marks"*
- WAEC Hausa Paper 2 — *"answer six questions: three from Section A, two from
  Section B and one from Section C"*
- WAEC Biology Paper 2 — *"answer two questions from Section A and all the
  short-structured questions from either Section B or C"*

Objective papers are all-answered, so this does not block serving MCQs. It does
mean any WAEC/NECO "paper" is a mock until someone decides how N-of-M scores.

## 3. A WAEC/NECO paper is 8–9 subjects, not 4

JAMB is Use of English + three electives — four subjects, 120 minutes, all
attempted. Our whole scheme model is built on that, and `is_complete()` counts
compulsory subjects plus electives toward a four-subject paper.

- **WAEC (Nigeria):** candidates pick **9 subjects** including Mathematics,
  English, Civic Education and a trading subject.
- **NECO:** **4 compulsory + 3–4 from a specialisation + 1 elective outside the
  field = minimum 8, maximum 9.**

> Sources: `https://syllabus.ng/waec` (**medium** — independent aggregator, no
> primary citation); NECO subject/specialisation structure from
> `https://neco2025.org/` (**low** — aggregator; the 76-subject figure and the
> 8–9 combination rule both need confirming against a NECO primary document
> before either is stored).

**Consequence:** "a full paper for at least 4 subjects" is *partial* for both
boards. For WAEC it is roughly the compulsory core; for NECO it is below the
minimum. That is a legitimate milestone — it is just worth naming for what it
is rather than calling it a paper.

## 4. Our non-JAMB `full_exam_questions` are unverified, and two look wrong

| row | stored | what sources say |
|---|---|---|
| WAEC `english-language` | 80 | plausible (D21 cites WAEC Paper 1 = 80); **unverified by a primary source here** |
| WAEC `general-mathematics` | 75 | **unverified** |
| WAEC `civic-education` | 40 | **unverified**; WAEC English's own Civic Education syllabus carries no count in the text we read |
| WAEC `animal-husbandry` / `financial-accounting` / `visual-arts` | 40 each | **unverified** |
| NECO `english-language` | 40 | **contradicted** — NECO English Language objective is *"60 Questions"* in 1 hour |
| NECO `civic-education` | 40 | **unverified** (timetable gives duration, not count) |
| NECO `animal-husbandry` | 40 | **unverified** |

WAEC's own objective counts are demonstrably **per subject and not uniform** —
Biology 50, Hausa 60, English 80. So a flat 40 for the three elective WAEC
rows has no support in anything read today.

**This is D50's exact failure mode.** `full_exam_questions` is a bare integer a
consumer will read as "this is how many questions the paper has." At least one
is wrong. Under D50 the honest value is either a verified number or *absent* —
and these are not absent today, they are plausible-looking.

> Confidence: WAEC Biology 50 / Hausa 60 — **high** (board's own syllabus PDFs).
> NECO English 60 — **medium** (exam-guide pages, not the paper itself).
> All others — **unverified**, recorded so nobody re-assumes them.

## 5. Syllabus sources exist, and they are better than expected

`jambsyllabus.com` had no WAEC/NECO equivalent, and this is the answer:

| source | what | confidence |
|---|---|---|
| `https://waecsyllabus.com/` | **64 subjects**, web + PDF each, direct per-subject PDF URLs (`/download/ssce/BIOLOGY.pdf`). States it is *independent, not affiliated with WAEC* — same standing as `jambsyllabus.com` | medium-high |
| `https://syllabus.ng/waec/<subject>` | per-subject page carrying the **marking guide** (paper-by-paper structure) | medium |
| `https://wassequestions.com/wp-content/uploads/...` | also hosts WAEC syllabus PDFs by year | low-medium |
| NECO | no clean single site found; `neco.gov.ng` publishes timetables (authoritative, counts absent) and subject syllabus lists are scattered across aggregators | low — **needs work** |

Note the shape of the good ones: **the marking guide is printed in the syllabus
itself.** Biology's Paper 1/2/3 breakdown, Geography's asterisk rule, Hausa's
weighting table — that is the paper structure, from the board, per subject. If
we build WAEC catalogs, that text is the primary source for `full_exam_questions`
and the country markers, and it is sitting in the PDFs already.

## 6. Question sources exist for both boards

| source | what | confidence |
|---|---|---|
| `https://myschool.ng/classroom/<subject>?exam_type=neco` | NECO past questions **per subject and per year** (`neco 2001`, …), with answer statistics and explanations | medium |
| `https://kuulchat.com/wassce/questions/june-2025-english` | WASSCE papers by year, section-preserving, questions + answers | low-medium |
| competitor: `https://sdashapi.com` | commercial API already selling JAMB/WAEC/NECO/Post-UTME with per-row solutions — confirms the market exists and someone is already in it | — |

`config/harvest.json` skips 12 NECO subjects with the reason *"the source carries
no JAMB paper."* That reason is about **our** JAMB source, not about the boards.
A second source is required and at least two candidates are visible.

## 7. What this costs, honestly

Serving a WAEC paper needs, in order:

1. **Country scope on topics** — a schema change. Nothing WAEC is servable
   correctly without it, and it is the only blocking item.
2. **Verified `full_exam_questions`** from the marking guides in the PDFs, and
   `absent` where unverified — a data correction, not just an addition.
3. **Decide what a paper is** — 8–9 subjects, objective only, and how N-of-M
   scores. A product decision, not a research one.
4. **Topic trees** from `waecsyllabus.com` — mechanical once (1) is settled,
   the way Commerce was.
5. **Questions** from a second harvest source.
6. **Verification**, as always — and nothing harvested is checkable against our
   own summaries the way the physics batches were.

Steps 4–6 are the expensive part. Steps 1–3 are cheap and none of them are
worth doing unless 4–6 will follow.

## 8. Do not

- **Do not store a country marker as topic text or in `name`.** §1 needs a real
  field or a real scope; smuggling it into a string recreates the problem it
  solves.
- **Do not infer WAEC question counts from JAMB's.** They differ per subject
  (50 / 60 / 80 observed), and the subject sets barely overlap.
- **Do not assume NECO mirrors WAEC.** Different country scope, objective paper
  numbered III, different subject count (76 vs 64).
- **Do not call a 4-subject set "a paper."** It is the compulsory core at best.
- **Do not touch `subjects.json` on the strength of this note.** D7 first.

## 9. Open, needs a primary source

- Pan-African scope (noted 2026-10-13, explicitly later): beyond Nigeria, the
  neighbouring countries — and eventually non-WAEC boards (KCSE, UNEB, NSC).
  No action now; recorded so the door stays visibly open. The set-based scope
  model (§10 design direction) already covers WAEC's four neighbours with no
  extra machinery — each new country/board is content work (topics, questions,
  verification), not engineering work. JAMB pays first (D1); this follows.
- NECO's exact subject count and the compulsory list (76? which four?)
- NECO objective-paper question count per subject — 60 uniform or not?
- WAEC `civic-education` and the three electives: real objective counts
- Whether "WAEC" in our catalog means Nigeria by default, or must be
  country-qualified everywhere (a product decision with a schema cost)

## 10. Proposed shape — `data/exams.json` (D66, PROPOSED)

Written after the research above showed that a subject cannot honestly carry
the facts the current model asks of it. **Scoped pin (D66, 2026-10-13):**
exam record + nullable count implemented; scope as join tables
(`topic_countries`, `exam_requirements`) with `?country=` filters
implemented — the nullable-`Topic.country` sketch here is superseded by sets,
which alone can hold a four-country section. The `is_compulsory` rewrite
stays deferred.

```json
[
  {
    "code": "JAMB",
    "name": "Joint Admissions and Matriculation Board — UTME",
    "countries": ["NG"],
    "status": "live",
    "has_full_paper": true,
    "subjects_required": 4,
    "duration_minutes": 120,
    "rules": ["Use of English plus three electives; all four subjects attempted."]
  },
  {
    "code": "WAEC",
    "name": "West African Examinations Council — WASSCE",
    "countries": ["NG", "GH", "SL", "GM", "LR"],
    "status": "live",
    "has_full_paper": false,
    "subjects_required": null,
    "duration_minutes": null,
    "rules": [
      "WAEC syllabi are country-partitioned; a topic may be Nigeria-only, Ghana-only, or shared. Pass a country to filter.",
      "Each subject is up to three papers (objective, essay, practical). We serve the objective paper only.",
      "Some papers are 'answer N of M'. Objective papers are all-answered, so this does not affect objective mocks."
    ]
  },
  {
    "code": "NECO",
    "name": "National Examinations Council — SSCE",
    "countries": ["NG"],
    "status": "live",
    "has_full_paper": false,
    "subjects_required": null,
    "duration_minutes": null,
    "rules": ["Objective paper is numbered III, not I."]
  },
  {
    "code": "POST-UTME",
    "name": "JAMB Post-UTME Screening",
    "countries": ["NG"],
    "status": "planned",
    "has_full_paper": null,
    "subjects_required": null,
    "duration_minutes": null,
    "rules": []
  }
]
```

### The four changes, in dependency order

| # | change | what it fixes |
|---|---|---|
| 1 | `Subject.full_exam_questions: u32` → `objective_paper_questions: Option<u32>` | §4. `None` covers both "unverified" and "this subject is three papers" — same value honestly, because in both cases we cannot state a single count. |
| 2 | `data/exams.json`, `Exam` as a real record | The hardcode `(exam == "JAMB").then_some(120)` at `scheme.rs:136`, and `is_complete(min_electives)` taking the paper shape from a **query parameter** — the exam's fact, sitting in the caller's hands. |
| 3 | ~~`Topic.country: Option<String>`, null = all member countries~~ → `topic_countries` join (set membership; absence = universal) | §1. Single scalar cannot hold Section C's four countries — sets shipped instead. |
| 4 | `Subject.is_compulsory: bool` → an exam-level requirement rule | Already wrong: NECO has 2 subjects flagged compulsory while its rule is 4, one of which is *one of* a group. A boolean cannot say that. **Deferred** — record why, build later. |

### What this buys

- Full-paper features become **data** (`has_full_paper`), not an exam-name comparison. POST-UTME arrives as a row.
- `/exams` can finally say "WAEC requires a country", which is the precondition for §1 being fixable.
- `duration_minutes` gains a home and a path to per-country values.
- `rules[]` un-hardcodes the WAEC N-of-M warning currently a Rust literal in `rules_for()`.
- `exams` is already phase 5 of D64's clearing order — this is the same row as a table later, which is D64's "same structs" rule satisfied by construction.
- `subjects_required` moves the paper shape out of a query string.

### The product split this makes explicit

| product | where it works | gate |
|---|---|---|
| **objective mock** | **every exam, every subject, today** | objective count known + enough verified rows |
| **full paper** | JAMB now, POST-UTME later | `has_full_paper: true` |

The WAEC ask is an **objective mock** question and becomes answerable with a topic
tree, some rows and no exam modelling at all.

### Explicitly NOT proposed

- **No `Paper` table.** Not caution — a proof. `Option { id, text }` + `answer`
  can only express single-choice with one right answer. Objective papers *are*
  MCQ; essay and practical are not. The model can only ever represent the
  objective paper, so one nullable column named for it is the complete story. A
  `Paper` entity would model a shape the model cannot hold.
- **No N-of-M scoring.** Objective papers are all-answered; the recorded WAEC
  problem never reaches this bank.
- **No country-qualified exam codes** (`WAEC-NG`). The 5× cost is only paid when
  Ghana is built, but the exam namespace should not fork to solve what one
  nullable field solves.
- **`is_compulsory` → rule is not proposed for now.** Recorded as known-wrong.

### The honest caveat

If the product is Nigeria-only forever, changes 3 and 4 are speculative
generality and should be dropped, and this collapses to something much smaller.
Smaller is right. Decide that before opening the schema window — the whole
proposal is one breaking window, not four.