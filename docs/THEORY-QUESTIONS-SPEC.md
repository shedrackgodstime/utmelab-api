# WAEC & NECO Paper 2 Theory Questions & Marking Scheme Specification

This document defines the locked product design, data contract, examiner scoring rules, and API endpoints for WAEC and NECO Paper 2 Theory Questions, Step-by-Step Marking Schemes, and the Self-Evaluation Engine.

---

## 1. Context and Problem Statement

West African examinations (WAEC WASSCE and NECO SSCE) evaluate candidates through three distinct papers:
- **Paper 1**: Objective multiple-choice testing (30% to 40% of composite mark).
- **Paper 2**: Theory, essays, mathematical derivations, and structural problem solving (50% to 60% of composite mark).
- **Paper 3**: Practical laboratory experiments or alternatives to practical (where applicable).

Existing edtech platforms focus almost exclusively on Paper 1 multiple-choice questions. Candidates who practice only multiple-choice questions regularly fail Paper 2 because they do not understand how examiners award marks across intermediate lines of working.

This subsystem provides authentic Paper 2 questions with official step-by-step marking schemes, alternative solution paths, word-to-symbol formulation guides, and an interactive self-scoring evaluation engine.

---

## 2. Official Examiner Marking Mechanics

WAEC and NECO marking schemes do not score open-ended solutions as simple pass or fail. Examiners allocate points using four standardized mark designations:

### A. Method Marks (M)
- Awarded for applying a recognized mathematical formula, scientific law, or valid algebraic process.
- **The Prerequisite Rule**: A method mark is prerequisite to subsequent accuracy marks. If a candidate makes a conceptual error resulting in zero method marks ($M0$), all dependent accuracy marks for that working line are automatically forfeited ($A0$).

### B. Accuracy Marks (A)
- Awarded for correct numerical computation, valid algebraic simplification, or exact values following a valid method mark.
- Accuracy marks cannot be scored if the preceding method mark was not awarded.

### C. Independent Marks (B)
- Awarded for standalone definitions, correct statements of physical laws, labeled elements on diagrams, or correct units.
- Independent marks do not depend on preceding method steps.

### D. Official Deductions and Penalties
- **Unit Penalty**: Deduction of 1 mark for omitting or misstating the SI unit in the final answer.
- **Premature Rounding Penalty**: Deduction of 1 mark for rounding intermediate decimal figures rather than keeping exact values until the final evaluation.
- **Mechanical Accuracy Deductions**: Deduction of 0.5 marks per spelling or punctuation error in English essay writing (up to the section ceiling).

---

## 3. Core Subsystem Capabilities

### Capability 1: Dual-Mode Question Access
The API serves questions in two distinct operational modes:
1. **Student Practice View**: Returns the question stem, stimulus, diagrams, sub-parts, and allocated marks while withholding the solution rubric.
2. **Teacher / Rubric Review View**: Exposes the complete line-by-line marking rubric with mark codes ($M1, A1, B1$), scoring conditions, and Chief Examiner commentary.

### Capability 2: Alternative Solution Paths (Aliter)
In WAEC marking schemes, over 40% of mathematics and physics questions accept two or more valid solution paths (e.g. Factorization vs Quadratic Formula vs Completing the Square; Kinematics vs Work-Energy). The marking rubric stores distinct method trees so candidates can verify whichever valid approach they choose.

### Capability 3: Word-to-Symbol Formulation Bridge
Chief Examiners identify the translation of word problems into equations as the primary cause of candidate failure in mathematics and physics. For word problems, the question payload includes a `formulation_bridge` that maps each sentence in the problem directly to its variable definition, algebraic constraint, and formulated equation before calculations begin.

### Capability 4: Scientific Diagram & Drawing Rubrics
For questions requiring diagrams (Biology anatomy, Physics ray optics, Geometry bearings), the rubric details explicit point allocations:
- Diagram Title ($B1$)
- Proportional Magnification ($B1$)
- Line Quality: continuous, un-feathered lines ($B1$)
- Label Lines: horizontal, ruled, non-intersecting, touching exact structures without arrowheads ($B2$)

### Capability 5: Interactive Rule-Governed Self-Evaluation
An evaluation endpoint (`POST /api/v1/theory/{exam}/{subject}/{id}/evaluate`) allows mobile and web clients to submit a checklist of steps a candidate satisfied during paper practice. The engine:
- Verifies step dependencies: zeroes out accuracy marks if method marks are absent ($M0 \implies A0$).
- Applies unit and rounding deductions.
- Returns a realistic predicted raw score with actionable diagnostic feedback.

---

## 4. Database Schema

### Table: `theory_questions`

```sql
CREATE TABLE IF NOT EXISTS theory_questions (
    id TEXT PRIMARY KEY,
    exam TEXT NOT NULL,
    subject TEXT NOT NULL,
    year INTEGER NOT NULL,
    paper INTEGER NOT NULL DEFAULT 2,
    section TEXT NOT NULL,
    question_number TEXT NOT NULL,
    topic_slug TEXT NOT NULL,
    subtopic_slug TEXT,
    total_marks INTEGER NOT NULL,
    stem TEXT NOT NULL,
    diagram_url TEXT,
    sub_parts TEXT NOT NULL,
    formulation_bridge TEXT,
    marking_methods TEXT NOT NULL,
    diagram_rubric TEXT,
    penalties TEXT NOT NULL,
    examiner_report TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_theory_questions_unique
ON theory_questions (exam, subject, year, question_number);

CREATE INDEX IF NOT EXISTS idx_theory_questions_topic
ON theory_questions (exam, subject, topic_slug);

CREATE INDEX IF NOT EXISTS idx_theory_questions_subtopic
ON theory_questions (exam, subject, subtopic_slug);
```

---

## 5. Data Contract & JSON Schema

Every question payload is bounded strictly under 16 KiB.

### Complete `TheoryQuestion` Structure

```json
{
  "id": "wq_waec_2023_math_p2_q4",
  "exam": "WAEC",
  "subject": "general-mathematics",
  "year": 2023,
  "paper": 2,
  "section": "Section A",
  "question_number": "4",
  "topic_slug": "algebraic-processes",
  "subtopic_slug": "quadratic-equations",
  "total_marks": 8,
  "stem": {
    "text": "A rectangular garden has a perimeter of 48 metres and an area of 135 square metres. (a) Form a quadratic equation in one variable representing the dimensions of the garden. (b) Solve the equation to determine the length and breadth of the garden.",
    "inline": []
  },
  "diagram_url": null,
  "sub_parts": [
    {
      "part_label": "(a)",
      "prompt": "Form a quadratic equation in one variable representing the dimensions of the garden.",
      "allocated_marks": 3
    },
    {
      "part_label": "(b)",
      "prompt": "Solve the equation to determine the length and breadth of the garden.",
      "allocated_marks": 5
    }
  ],
  "formulation_bridge": [
    {
      "clause": "A rectangular garden has a perimeter of 48 metres",
      "variable_mapping": "Let length be L and breadth be B. Perimeter formula is 2(L + B) = 48",
      "derived_equation": "L + B = 24 \\implies B = 24 - L"
    },
    {
      "clause": "and an area of 135 square metres",
      "variable_mapping": "Area formula is L \\times B = 135. Substitute B = 24 - L",
      "derived_equation": "L(24 - L) = 135 \\implies L^2 - 24L + 135 = 0"
    }
  ],
  "marking_methods": [
    {
      "method_id": "method_1",
      "method_name": "Method 1: Factorization",
      "is_primary": true,
      "steps": [
        {
          "step_id": "step_1",
          "part_label": "(a)",
          "description": "Expressing perimeter relationship and isolating one variable",
          "expression": "2(L + B) = 48 \\implies B = 24 - L",
          "mark_type": "M",
          "mark_value": 1,
          "notes": "Award M1 for correct semi-perimeter substitution"
        },
        {
          "step_id": "step_2",
          "part_label": "(a)",
          "description": "Substituting into area equation to form quadratic equation",
          "expression": "L(24 - L) = 135 \\implies L^2 - 24L + 135 = 0",
          "mark_type": "M",
          "mark_value": 1,
          "notes": "Award M1 for setting equation equal to zero"
        },
        {
          "step_id": "step_3",
          "part_label": "(a)",
          "description": "Accurate quadratic equation in standard form",
          "expression": "L^2 - 24L + 135 = 0",
          "mark_type": "A",
          "mark_value": 1,
          "notes": "Accept any equivalent variable name"
        },
        {
          "step_id": "step_4",
          "part_label": "(b)",
          "description": "Finding factors with product 135 and sum -24",
          "expression": "(L - 15)(L - 9) = 0",
          "mark_type": "M",
          "mark_value": 2,
          "notes": "Award M1 for correct factor pair (-15, -9), M1 for factorized expression"
        },
        {
          "step_id": "step_5",
          "part_label": "(b)",
          "description": "Solving for both roots",
          "expression": "L = 15 \\text{ or } L = 9",
          "mark_type": "A",
          "mark_value": 1,
          "notes": "Award A1 for both roots correctly calculated"
        },
        {
          "step_id": "step_6",
          "part_label": "(b)",
          "description": "Stating final dimensions with correct SI units",
          "expression": "\\text{Length} = 15 \\text{ m}, \\text{Breadth} = 9 \\text{ m}",
          "mark_type": "A",
          "mark_value": 2,
          "notes": "Award A1 for dimensions identification, A1 for units. Deduct 1 mark if units are omitted"
        }
      ]
    },
    {
      "method_id": "method_2",
      "method_name": "Method 2: Quadratic Formula",
      "is_primary": false,
      "steps": [
        {
          "step_id": "step_m2_1",
          "part_label": "(b)",
          "description": "Correct quotation and substitution into quadratic formula",
          "expression": "L = \\frac{-(-24) \\pm \\sqrt{(-24)^2 - 4(1)(135)}}{2(1)}",
          "mark_type": "M",
          "mark_value": 2,
          "notes": "Award M1 for correct formula structure, M1 for exact substitution"
        },
        {
          "step_id": "step_m2_2",
          "part_label": "(b)",
          "description": "Simplifying discriminant and evaluating roots",
          "expression": "L = \\frac{24 \\pm \\sqrt{576 - 540}}{2} = \\frac{24 \\pm 6}{2} = 15 \\text{ or } 9",
          "mark_type": "A",
          "mark_value": 1,
          "notes": "Award A1 for exact roots"
        },
        {
          "step_id": "step_m2_3",
          "part_label": "(b)",
          "description": "Stating final dimensions with correct SI units",
          "expression": "\\text{Length} = 15 \\text{ m}, \\text{Breadth} = 9 \\text{ m}",
          "mark_type": "A",
          "mark_value": 2,
          "notes": "Award A1 for dimensions, A1 for metres"
        }
      ]
    }
  ],
  "diagram_rubric": null,
  "penalties": [
    {
      "penalty_type": "unit_omission",
      "deduction": 1,
      "description": "Deduct 1 mark if metres (m) is omitted from the final length and breadth answer."
    },
    {
      "penalty_type": "premature_rounding",
      "deduction": 1,
      "description": "Deduct 1 mark for rounding values during intermediate steps."
    }
  ],
  "examiner_report": {
    "general_performance": "Candidate performance on this question was fair. Many candidates successfully established the perimeter equation but failed to substitute correctly into the area formula.",
    "common_errors": [
      "Confusing perimeter 2(L + B) with L + B = 48, leading to an incorrect quadratic equation L^2 - 48L + 135 = 0.",
      "Finding roots 15 and 9 but failing to explicitly state which value is length and which is breadth.",
      "Omitting the unit of measurement (metres) in the final answer statement."
    ],
    "remedies": "Instructors should train candidates to verify boundary dimensions against both perimeter and area before finalizing answers."
  }
}
```

---

## 6. Self-Evaluation Data Contract

### Evaluation Request (`POST /api/v1/theory/{exam}/{subject}/{id}/evaluate`)
```json
{
  "selected_method_id": "method_1",
  "achieved_step_ids": ["step_1", "step_2", "step_3", "step_4", "step_5", "step_6"],
  "unit_included": true,
  "intermediate_rounding_avoided": true
}
```

### Evaluation Response
```json
{
  "question_id": "wq_waec_2023_math_p2_q4",
  "total_marks": 8,
  "awarded_marks": 8,
  "percentage": 100.0,
  "mark_breakdown": {
    "method_marks_awarded": 4,
    "method_marks_possible": 4,
    "accuracy_marks_awarded": 4,
    "accuracy_marks_possible": 4,
    "independent_marks_awarded": 0,
    "independent_marks_possible": 0
  },
  "penalties_applied": [],
  "diagnostic_feedback": [
    "Full credit awarded. Both method formulation and final accuracy criteria were satisfied."
  ]
}
```

---

## 7. Proposed API Endpoints

### 1. Paged Theory Questions
`GET /api/v1/theory/{exam}/{subject}`
- **Parameters**: `year`, `topic`, `section`, `page`, `per_page`
- **Behavior**: Returns paged question summaries without full rubrics.

### 2. Practice Question View
`GET /api/v1/theory/{exam}/{subject}/{id}`
- **Parameters**: `include_rubric=false` (default)
- **Behavior**: Returns question stem, formulation bridge, sub-parts, and allocated marks. Withholds marking steps.

### 3. Complete Marking Rubric View
`GET /api/v1/theory/{exam}/{subject}/{id}/rubric`
- **Behavior**: Returns the full marking scheme including all alternative methods, mark allocations ($M, A, B$), diagram rubrics, and Chief Examiner reports.

### 4. Interactive Self-Evaluation
`POST /api/v1/theory/{exam}/{subject}/{id}/evaluate`
- **Behavior**: Evaluates candidate checklist selections against examiner prerequisite rules, applies penalty deductions, and returns the computed score and diagnostic feedback.

---

## 8. Source Attribution & Quality Standard

Every theory question and marking scheme in UTMELAB must be:
1. **Directly Attributed**: Sourced from official past examination papers and validated against WAEC/NECO Chief Examiners' Reports.
2. **Pedagogically Complete**: Featuring explicit mark designations ($M, A, B$), alternative solution paths, and common error commentary.
3. **Clean Writing Compliant**: Zero em dashes, zero en dashes, zero hyphens as dashes, active voice, and clear Saxon phrasing.
4. **Offline Parity**: Stored locally in libSQL replicas with read latency under 15 milliseconds.
