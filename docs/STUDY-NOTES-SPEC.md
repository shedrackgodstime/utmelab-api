# UTME Lab Study Notes: Technical Specification & Implementation Contract

**Status:** Locked and sealed. Working implementation contract.  
**Date:** November 2026.  
**Scope:** Architecture, data schema, API endpoints, stakeholder experience, and execution roadmap for syllabus-mapped study notes.

---

## 1. Architectural Invariants

Every study note implementation must satisfy these five rules:

1. **Zero External Runtime Latency**: Notes live in the local SQLite replica (`db/sync.db`). The serving API never queries external AI APIs or third-party databases during client requests.
2. **Deterministic Syllabus Attachment**: Every note explicitly references a valid `(exam, subject, topic_slug)` record from the production catalog. Notes without verified topic placement cannot be stored or served.
3. **Strict 16 KiB Payload Ceiling**: A complete note (sections, worked examples, formulas, micro-checks, and traps) must serialize to under 16 KiB, honoring the transport buffer limit in `src/routes/mod.rs`.
4. **Structured Rich Text with Media Resolution**: Any stem, explanation, or section content uses `RichText` with character scalar offsets. Embedded figure URLs resolve through the configured `media_base_url`.
5. **Universal Subject Compatibility**: For non-calculation subjects (e.g. Government, Literature, History), `formulas` and `worked_examples` default to empty arrays `[]` rather than null or missing keys.

---

## 2. Relational Database Schema (`READ_SHAPES`)

The table contract added to `src/store/schema.rs`:

```sql
CREATE TABLE IF NOT EXISTS topic_notes (
    id TEXT PRIMARY KEY,
    exam TEXT NOT NULL,
    subject TEXT NOT NULL,
    topic_slug TEXT NOT NULL,
    subtopic_slug TEXT,
    title TEXT NOT NULL,
    read_time_minutes INTEGER NOT NULL,
    key_takeaway TEXT NOT NULL,
    sections TEXT NOT NULL,
    worked_examples TEXT NOT NULL DEFAULT '[]',
    formulas TEXT NOT NULL DEFAULT '[]',
    active_recall_checks TEXT NOT NULL DEFAULT '[]',
    examiner_traps TEXT NOT NULL DEFAULT '[]',
    linked_question_ids TEXT NOT NULL DEFAULT '[]',
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notes_lookup 
ON topic_notes (exam, subject, topic_slug);

CREATE INDEX IF NOT EXISTS idx_notes_subtopic_lookup 
ON topic_notes (exam, subject, subtopic_slug);
```

Declared columns in `src/store/schema.rs`:
```rust
(
    "topic_notes",
    &[
        "id",
        "exam",
        "subject",
        "topic_slug",
        "subtopic_slug",
        "title",
        "read_time_minutes",
        "key_takeaway",
        "sections",
        "worked_examples",
        "formulas",
        "active_recall_checks",
        "examiner_traps",
        "linked_question_ids",
        "content_hash",
    ],
),
```

---

## 3. Rust Domain & Wire Models

The types added to `src/core/models/domain.rs` and `src/core/models/wire.rs`:

```rust
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct TopicNote {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub topic_slug: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub subtopic_slug: Option<String>,
    pub title: String,
    pub read_time_minutes: u8,
    pub key_takeaway: RichText,
    pub sections: Vec<NoteSection>,
    #[serde(default)]
    pub worked_examples: Vec<WorkedExample>,
    #[serde(default)]
    pub formulas: Vec<NoteFormula>,
    #[serde(default)]
    pub active_recall_checks: Vec<ActiveRecallCheck>,
    #[serde(default)]
    pub examiner_traps: Vec<ExaminerTrap>,
    #[serde(default)]
    pub linked_question_ids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NoteSection {
    pub section_number: u8,
    pub heading: String,
    pub content: RichText,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub callout: Option<NoteCallout>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NoteCallout {
    pub kind: String, // "examiner_tip", "warning", "law", "definition"
    pub text: RichText,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct WorkedExample {
    pub title: String,
    pub problem_statement: RichText,
    pub steps: Vec<SolutionStep>,
    pub final_answer: RichText,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub method_tip: Option<String>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct SolutionStep {
    pub step_number: u8,
    pub description: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expression: Option<String>, // LaTeX string
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NoteFormula {
    pub name: String,
    pub latex: String,
    pub variables: Vec<FormulaVariable>,
    #[serde(default)]
    pub conditions: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct FormulaVariable {
    pub symbol: String,
    pub name: String,
    pub unit: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ActiveRecallCheck {
    pub check_number: u8,
    pub prompt: String,
    pub options: Vec<String>,
    pub correct_index: u8,
    pub explanation: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ExaminerTrap {
    pub misconception: String,
    pub correction: String,
}
```

---

## 4. API Endpoints Contract

Mounted under `src/api/v1/notes.rs` and merged into `src/api/v1/mod.rs`:

### `GET /api/v1/notes/{exam}/{subject}/{topic_slug}`
* **Auth**: Requires `x-api-key` header with `read:catalog` scope.
* **Params**:
  * `exam`: Exam code (`JAMB`, `WAEC`, `NECO`).
  * `subject`: Subject slug (e.g. `physics`).
  * `topic_slug`: Topic identifier (e.g. `motion`).
* **Response**: `200 OK` with `TopicNote` payload. `404 Not Found` if no note exists.

### `GET /api/v1/notes/subtopic/{exam}/{subject}/{subtopic_slug}`
* **Auth**: Requires `x-api-key` header with `read:catalog` scope.
* **Params**:
  * `subtopic_slug`: Specific subtopic identifier (e.g. `projectiles`).
* **Response**: `200 OK` with `TopicNote` payload.

### Syllabus Enhancement (`GET /api/v1/subjects/{exam}/{slug}/syllabus`)
* Topic and Subtopic objects in the syllabus tree gain:
  * `has_note: bool`
  * `note_id: Option<String>`

---

## 5. End-to-End User Experience

```text
[Syllabus Screen]
   │ Student selects "Physics" -> "Motion" -> "Projectiles"
   │ (App sees has_note = true)
   ▼
[Study Note Screen]
   ├── 1. Hero Summary: "5 min read" + Key Takeaway
   ├── 2. Core Concept Micro-Section (RichText with bold keywords)
   ├── 3. Examiner Tip Callout Box
   ├── 4. Active Recall Pop-Quiz Widget (Student taps option -> immediate feedback)
   ├── 5. Worked Example Card (Collapsible algebraic steps in LaTeX)
   ├── 6. Formula Cheat Cards (Symbol, meaning, SI units)
   └── 7. Examiner Traps (Misconception vs Correction warning box)
   │
   ▼
[Call-to-Action Footer]
   │ "Ready to test yourself? 18 official questions available."
   │ Student taps "Start Quiz"
   ▼
[CBT Practice Quiz Screen]
   │ App calls GET /api/v1/questions?subtopic=projectiles
   │ Interactive test starts with real past questions
```

---

## 6. Phased Implementation Roadmap

1. **Step 1: Core Models & Schema Declaration**
   * Add `TopicNote` and helper structs to `src/core/models/domain.rs` and `wire.rs`.
   * Add `topic_notes` table to `store::schema::READ_SHAPES`.
2. **Step 2: Database Storage & Query Methods**
   * Write `store::catalog::fetch_topic_note` and `store::catalog::fetch_subtopic_note` in `src/store/catalog.rs`.
   * Update `store::catalog::fetch_syllabus_tree` to populate `has_note` and `note_id`.
3. **Step 3: Route Handlers & OpenAPI Documentation**
   * Create `src/api/v1/notes.rs` with `#[utoipa::path]` annotations.
   * Mount in `src/api/v1/mod.rs` and update OpenAPI contract test.
4. **Step 4: Unit & Integration Tests**
   * Test keyed access, scope verification, ETag support, 404 behavior, and media URL resolution on seeded test replicas.
5. **Step 5: Manual Note Authoring**
   * Author reference notes by hand in the API repository.
   * Load them with the `seed-reference-notes` command after verifying syllabus placement.
