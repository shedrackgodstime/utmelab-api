# Proof of Concept: Syllabus Topic Study Notes (Revision 2)

This specification incorporates market research from top edtech revision platforms:
* **Save My Exams**: Syllabus-aligned modular design, examiner tips, and worked examples with model answers.
* **Seneca Learning**: Cognitive microlearning, 5-to-8 minute sessions, and active recall checks between sections.
* **uLesson**: West African curriculum alignment, visual aids, and step-by-step calculation methods.

---

## 1. Why Traditional Notes Fail & What Modern Edtech Does

Traditional study notes fail because they dump textbook chapters as unbroken walls of text. Students read passively, lose concentration, and forget the material within hours.

Modern revision platforms succeed because they follow three proven pedagogical rules:
1. **Rule of One Idea**: Break topics into micro-sections that answer one syllabus objective in under 2 minutes.
2. **Worked Examples**: Show the exact step-by-step mathematical or conceptual execution before asking the student to practice.
3. **Learn-Then-Check Loop (Active Retrieval)**: Place quick-check questions directly after a section so the student actively retrieves memory before scrolling further.

---

## 2. Updated Domain Data Contract

```rust
pub struct TopicNote {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub topic_slug: String,
    pub subtopic_slug: Option<String>,
    pub title: String,
    pub read_time_minutes: u8,
    pub key_takeaway: RichText,
    pub sections: Vec<NoteSection>,
    pub worked_examples: Vec<WorkedExample>,
    pub formulas: Vec<NoteFormula>,
    pub active_recall_checks: Vec<ActiveRecallCheck>,
    pub examiner_traps: Vec<ExaminerTrap>,
    pub linked_question_ids: Vec<String>,
}

pub struct NoteSection {
    pub section_number: u8,
    pub heading: String,
    pub content: RichText,
    pub callout: Option<NoteCallout>,
}

pub struct NoteCallout {
    pub kind: CalloutKind, // examiner_tip, warning, law, definition
    pub text: RichText,
}

pub struct WorkedExample {
    pub title: String,
    pub problem_statement: RichText,
    pub steps: Vec<SolutionStep>,
    pub final_answer: RichText,
    pub method_tip: Option<String>,
}

pub struct SolutionStep {
    pub step_number: u8,
    pub description: String,
    pub expression: Option<String>, // LaTeX string
}

pub struct ActiveRecallCheck {
    pub check_number: u8,
    pub prompt: String,
    pub options: Vec<String>,
    pub correct_index: u8,
    pub explanation: String,
}

pub struct NoteFormula {
    pub name: String,
    pub latex: String,
    pub variables: Vec<FormulaVariable>,
    pub conditions: Vec<String>,
}

pub struct FormulaVariable {
    pub symbol: String,
    pub name: String,
    pub unit: String,
}

pub struct ExaminerTrap {
    pub misconception: String,
    pub correction: String,
}
```

---

## 3. Concrete Example: Physics (Projectile Motion)

```json
{
  "id": "note_phys_jamb_projectile_motion",
  "exam": "JAMB",
  "subject": "physics",
  "topic_slug": "motion",
  "subtopic_slug": "projectiles",
  "title": "Projectile Motion: Flight Path, Range, and Maximum Height",
  "read_time_minutes": 5,
  "key_takeaway": {
    "text": "Projectile motion combines constant horizontal velocity with constant vertical gravitational acceleration.",
    "inline": []
  },
  "sections": [
    {
      "section_number": 1,
      "heading": "1. Independence of Motion",
      "content": {
        "text": "A projectile launched into the air moves in two dimensions at the same time. The horizontal motion experiences zero acceleration when air resistance is neglected. Gravity pulls downward, accelerating the vertical motion at 9.8 m/s² (or 10 m/s² in standard JAMB calculations). Because gravity acts only downward, the horizontal velocity component never changes throughout the flight.",
        "inline": [
          { "start": 80, "len": 17, "kind": "bold" },
          { "start": 169, "len": 7, "kind": "italic" }
        ]
      },
      "callout": {
        "kind": "examiner_tip",
        "text": {
          "text": "Horizontal velocity (u_x = u cos θ) remains constant at every point on the trajectory, including at maximum height.",
          "inline": [
            { "start": 21, "len": 13, "kind": "bold" }
          ]
        }
      }
    },
    {
      "section_number": 2,
      "heading": "2. Velocity at Maximum Height",
      "content": {
        "text": "At the peak of flight, the projectile stops climbing for an instant. The vertical velocity component becomes zero (v_y = 0). However, the total velocity at maximum height is not zero: the object still moves forward with its original horizontal speed (u cos θ).",
        "inline": [
          { "start": 98, "len": 9, "kind": "bold" }
        ]
      },
      "callout": {
        "kind": "warning",
        "text": {
          "text": "Never set total velocity to zero at the maximum height. Only the vertical component is zero.",
          "inline": [
            { "start": 0, "len": 55, "kind": "bold" }
          ]
        }
      }
    }
  ],
  "worked_examples": [
    {
      "title": "Finding Time of Flight and Maximum Height",
      "problem_statement": {
        "text": "A stone is projected from the ground with a velocity of 40 m/s at an angle of 30 degrees to the horizontal. Calculate: (a) the time taken to reach the maximum height, (b) the total time of flight. (Take g = 10 m/s²)",
        "inline": []
      },
      "steps": [
        {
          "step_number": 1,
          "description": "Identify known variables and formula for time to maximum height",
          "expression": "u = 40\\text{ m/s}, \\quad \\theta = 30^\\circ, \\quad g = 10\\text{ m/s}^2, \\quad t = \\frac{u \\sin \\theta}{g}"
        },
        {
          "step_number": 2,
          "description": "Substitute values into the formula to find t",
          "expression": "t = \\frac{40 \\times \\sin(30^\\circ)}{10} = \\frac{40 \\times 0.5}{10} = \\frac{20}{10} = 2.0\\text{ seconds}"
        },
        {
          "step_number": 3,
          "description": "Calculate total time of flight by doubling the time to maximum height",
          "expression": "T = 2 \\times t = 2 \\times 2.0 = 4.0\\text{ seconds}"
        }
      ],
      "final_answer": {
        "text": "Time to maximum height is 2.0 seconds. Total time of flight is 4.0 seconds.",
        "inline": []
      },
      "method_tip": "Always evaluate sin(30°) = 0.5 first before multiplying by velocity."
    }
  ],
  "formulas": [
    {
      "name": "Time to Maximum Height",
      "latex": "t = \\frac{u \\sin \\theta}{g}",
      "variables": [
        { "symbol": "u", "name": "Initial velocity", "unit": "m/s" },
        { "symbol": "\\theta", "name": "Angle of projection to horizontal", "unit": "degrees" },
        { "symbol": "g", "name": "Gravitational acceleration", "unit": "m/s²" }
      ],
      "conditions": [
        "Level ground launch and landing",
        "Air resistance ignored"
      ]
    },
    {
      "name": "Maximum Height Reached",
      "latex": "H = \\frac{u^2 \\sin^2 \\theta}{2g}",
      "variables": [
        { "symbol": "H", "name": "Maximum vertical height", "unit": "m" }
      ],
      "conditions": [
        "Measured relative to launch plane"
      ]
    },
    {
      "name": "Horizontal Range",
      "latex": "R = \\frac{u^2 \\sin 2\\theta}{g}",
      "variables": [
        { "symbol": "R", "name": "Total horizontal distance", "unit": "m" }
      ],
      "conditions": [
        "Maximum range happens at 45 degrees launch angle"
      ]
    }
  ],
  "active_recall_checks": [
    {
      "check_number": 1,
      "prompt": "What happens to the horizontal velocity of a projectile during flight when air resistance is ignored?",
      "options": [
        "It decreases to zero at maximum height",
        "It increases steadily until landing",
        "It remains constant throughout the entire flight",
        "It reverses direction after reaching the peak"
      ],
      "correct_index": 2,
      "explanation": "Because gravity only acts downward (vertically), there is zero horizontal acceleration. The horizontal speed never changes."
    },
    {
      "check_number": 2,
      "prompt": "At what launch angle does a projectile achieve its maximum horizontal range on flat ground?",
      "options": [
        "30 degrees",
        "45 degrees",
        "60 degrees",
        "90 degrees"
      ],
      "correct_index": 1,
      "explanation": "The range formula depends on sin(2θ). The maximum possible value for sine is 1, which happens when 2θ = 90 degrees, meaning θ = 45 degrees."
    }
  ],
  "examiner_traps": [
    {
      "misconception": "Thinking acceleration at the top of the flight path is zero.",
      "correction": "Gravitational acceleration stays 9.8 m/s² downward at all times, even when vertical velocity is momentarily zero at the peak."
    },
    {
      "misconception": "Using the angle to the vertical instead of horizontal.",
      "correction": "If an exam question states 'projected at 30 degrees to the vertical', you must subtract it from 90 degrees to get 60 degrees to the horizontal before using the standard formulas."
    }
  ],
  "linked_question_ids": [
    "q_claim_2025_physics_40112",
    "q_claim_2025_physics_40113"
  ]
}
```

---

## 4. Why This Multiplies API Value for Developers

When an edtech developer queries this endpoint, they receive:
1. **Curated theory** for their reader view.
2. **Interactive widgets** from `active_recall_checks` (allowing apps to show Seneca-style quick comprehension quizzes between paragraphs).
3. **Step-by-step math cards** from `worked_examples` (allowing apps to show how calculations work before sending students to past papers).
4. **Formula cheat-sheets** from `formulas` (rendering native LaTeX cards).
5. **Trap alerts** from `examiner_traps` (highlighting exam pitfalls).

No competing West African API delivers this level of structured pedagogical granularity.
