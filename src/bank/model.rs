//! The bank's domain types — the D11 constant, as stored.
//!
//! No HTTP, no storage, no serde renames: this is what a question *is*. Both
//! surfaces (`api/`, `app/`) read these, so neither gets to reshape them.

use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

// ── catalog ──────────────────────────────────────────────────────────────────

/// One exam's offering of a subject (D21). The same concept can appear once per
/// exam, carrying that board's own name — `Use of English` and
/// `English Language` are two true rows, not one row with an alias.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Subject {
    pub slug: String,
    pub exam: String,
    pub name: String,
    pub is_compulsory: bool,
    pub full_exam_questions: u32,
}

/// A topic within one exam's syllabus.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Topic {
    pub slug: String,
    pub subject: String,
    pub exam: String,
    pub name: String,
    pub order: u32,
    pub weight: u32,
}

/// A drill-granular unit. Only exists for topics that hold enough questions to
/// practise (D16).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Subtopic {
    pub slug: String,
    pub topic: String,
    pub name: String,
    pub order: u32,
    #[serde(default)]
    pub objectives: Vec<String>,
}

// ── content ──────────────────────────────────────────────────────────────────

/// One answer choice. Named `Choice` because `Option` is Rust's, not ours.
///
/// `id` is stable identity; the **label** the student sees (A, B, C…) is
/// assigned from array position at render time and is never stored (D15).
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Choice {
    pub id: String,
    pub text: String,
}

/// Why the answer is what it is (D17). `key_point` is the flashcard teaser,
/// `body` the working, `trap` the distractor that catches people.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Explanation {
    pub key_point: String,
    pub body: String,
    #[serde(default)]
    pub trap: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Question {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub year: u16,
    pub text: String,
    pub options: Vec<Choice>,
    /// An **option id**, never a label or an index (D15).
    pub answer: String,
    #[serde(default)]
    pub subtopic_id: Option<String>,
    #[serde(default)]
    pub section: Option<String>,
    #[serde(default)]
    pub passage_id: Option<String>,
    #[serde(default)]
    pub image: Option<String>,
    #[serde(default)]
    pub explanation: Option<Explanation>,
    pub marks: f32,
    pub difficulty: u8,
    pub verified: bool,
}

/// A stimulus shared by many questions — one comprehension passage serving five
/// questions, one cloze serving ten.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Passage {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub year: u16,
    pub kind: String,
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub author: Option<String>,
    pub text: String,
}
