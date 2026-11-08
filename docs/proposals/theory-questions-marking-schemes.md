# Product Proposal: WAEC & NECO Paper 2 Theory Questions and Marking Schemes

## 1. Executive Summary

West African secondary examinations (WAEC WASSCE and NECO SSCE) divide testing into distinct papers. While Paper 1 consists of multiple-choice objective questions, Paper 2 (Theory, Essays, and Mathematical Problem Solving) accounts for 50% to 60% of a candidate's final composite grade.

Current edtech platforms focus almost exclusively on Paper 1 multiple-choice testing. Candidates who rely solely on multiple-choice practice regularly fail Paper 2 because they do not understand how examiners distribute marks across intermediate lines of working.

This proposal specifies a new product subsystem for UTMELAB: **Authentic Paper 2 Theory Questions with Step-by-Step Marking Schemes**, attributed directly to official past examination papers and Chief Examiners' Reports.

---

## 2. Core Examiner Grading Mechanics

WAEC and NECO examiners follow strict, standardized marking conventions. Unlike objective questions with single correct options, theory marking schemes award credit through four specific mark designations:

### A. Method Marks (M)
- Awarded for applying a recognized mathematical formula, correct scientific principle, or valid algebraic process.
- Examples include quoting the correct kinematic formula, setting up a balance sheet, or substituting values into a quadratic equation.
- **Governing Rule**: Method marks are prerequisite to accuracy marks. If a candidate makes a conceptual error resulting in zero method marks ($M0$), all dependent accuracy marks for that step are automatically forfeited ($A0$).

### B. Accuracy Marks (A)
- Awarded for correct numerical calculations, simplified algebraic expressions, or exact values following a valid method.
- An accuracy mark cannot be awarded if the corresponding method mark was not scored.

### C. Independent Marks (B)
- Awarded for standalone definitions, correct statements of laws, labeled elements in diagrams, or correct SI units.
- Independent marks do not depend on preceding method marks.

### D. Examiner Deductions and Penalties
- **Unit Penalty**: Deduction of 1 mark for omitting or misstating the SI unit in a final numerical answer.
- **Premature Rounding**: Deduction of 1 mark for rounding intermediate decimal values before the final computation line.
- **Grammar and Spelling Penalties**: Specific mark deductions in essay writing for spelling and mechanical errors.

---

## 3. Supported Modes of Use

The API supports two distinct operational modes:

### Mode 1: Candidate Practice View
Candidates receive the question stem, diagrams, sub-parts, and allocated point values. The marking rubric is withheld so students can attempt the solution independently without seeing the answer.

### Mode 2: Examiner / Teacher Rubric View
Reveals the full line-by-line marking rubric. Each line of working shows its exact mark allocation ($M1, A1, B1$), scoring conditions, and documented common errors from Chief Examiners' Reports.

---

## 4. Proposed Data Schema

### Table: `theory_questions`

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `TEXT PRIMARY KEY` | Deterministic slug (e.g. `wq_2023_math_p2_q4`) |
| `exam` | `TEXT NOT NULL` | Examination body (`WAEC` or `NECO`) |
| `subject` | `TEXT NOT NULL` | Subject slug (e.g. `general-mathematics`, `physics`) |
| `year` | `INTEGER NOT NULL` | Examination year (e.g. `2023`) |
| `paper` | `INTEGER NOT NULL` | Paper number (`2`) |
| `section` | `TEXT NOT NULL` | Paper section (`Section A` or `Section B`) |
| `question_number` | `TEXT NOT NULL` | Stated question number (e.g. `"4"`, `"11"`) |
| `topic_slug` | `TEXT NOT NULL` | Primary syllabus topic slug |
| `subtopic_slug` | `TEXT` | Optional subtopic slug |
| `total_marks` | `INTEGER NOT NULL` | Total points allocated to the question |
| `stem` | `TEXT NOT NULL` | JSON serialized rich text prompt and context |
| `diagram_url` | `TEXT` | Optional diagram or stimulus image path |
| `sub_parts` | `TEXT NOT NULL` | JSON array of question parts `(a)`, `(b)`, `(c)` |
| `marking_rubric` | `TEXT NOT NULL` | JSON array of sequential marking steps with mark types |
| `examiner_report` | `TEXT NOT NULL` | JSON object containing candidate errors and remedies |
| `content_hash` | `TEXT NOT NULL` | SHA-256 hash for cache invalidation |

### Structured Sub-Models

#### 1. `SubPart`
```json
{
  "part_label": "(a)",
  "prompt": "Find the value of x in the equation 2^(2x + 1) - 9(2^x) + 4 = 0.",
  "allocated_marks": 5
}
```

#### 2. `MarkingStep`
```json
{
  "step_number": 1,
  "part_label": "(a)",
  "description": "Expressing equation in quadratic form using index laws",
  "expression": "2 \\times (2^x)^2 - 9(2^x) + 4 = 0",
  "mark_type": "M",
  "mark_value": 1,
  "examiner_notes": "Award M1 for recognizing substitution y = 2^x leading to 2y^2 - 9y + 4 = 0."
}
```

#### 3. `ExaminerReport`
```json
{
  "general_performance": "Candidate performance was moderate. Many candidates successfully formed the quadratic equation but failed to convert back to the variable x.",
  "common_errors": [
    "Stopping at y = 4 or y = 1/2 without solving for x.",
    "Incorrectly expanding 2^(2x + 1) as 2^(2x) + 2."
  ],
  "remedies": "Instructors must emphasize checking whether the final answer answers the original question variable."
}
```

---

## 5. Proposed API Endpoints

### 1. Browse Theory Questions
`GET /api/v1/theory/{exam}/{subject}`
- **Query Parameters**:
  - `year`: Filter by examination year (e.g. `?year=2023`).
  - `topic`: Filter by syllabus topic (e.g. `?topic=indices-and-logarithms`).
  - `section`: Filter by paper section (e.g. `?section=A`).
  - `page`: Page index (default: `1`).
  - `per_page`: Clamped between 1 and 50 (default: `20`).
- **Response**: Paged envelope of theory question summaries.

### 2. Get Theory Question (Practice View)
`GET /api/v1/theory/{exam}/{subject}/{id}`
- **Query Parameter**:
  - `include_rubric=true` (optional): Includes full marking rubric in the response. Default is `false`.
- **Response**: Question stem, sub-parts, allocated marks, and optional diagram URLs.

### 3. Get Complete Marking Rubric (Teacher / Review View)
`GET /api/v1/theory/{exam}/{subject}/{id}/rubric`
- **Response**: Complete step-by-step marking steps, mark types ($M, A, B$), deduction rules, and Chief Examiner report commentary.

---

## 6. Implementation Roadmap

1. **Step 1: Schema Migration & Storage Engine**
   - Add table `theory_questions` to libSQL startup schema and replica migrations.
   - Establish unique indexes on `(exam, subject, year, question_number)`.

2. **Step 2: Core Domain & Wire Models**
   - Implement Rust structs for `TheoryQuestion`, `MarkingStep`, `ExaminerReport`, and wire serialization.

3. **Step 3: Reference Content Authoring**
   - Hand-author authentic reference theory questions directly from WAEC past papers and Chief Examiners' Reports for:
     - General Mathematics (Paper 2 Algebra and Geometry)
     - Physics (Paper 2 Mechanics and Waves)
     - English Language (Paper 2 Summary and Essay rubrics)

4. **Step 4: API Router & MCP Tools**
   - Register endpoints in `src/routes/` and expose matching MCP resource templates.
   - Add unit tests verifying bounds, schema integrity, and mark balance consistency.
