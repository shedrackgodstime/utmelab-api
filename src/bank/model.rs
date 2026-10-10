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
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
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
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
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

// ── novels (D35) ─────────────────────────────────────────────────────────────

/// The default category. English reading texts are the primary use; Literature
/// texts opt in explicitly.
fn default_novel_category() -> String {
    "english".to_owned()
}

/// A prescribed text. One row per (exam, cycle) — the novel rotates yearly, so
/// `year_prescribed` is load-bearing, not decorative.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Novel {
    pub id: String,
    pub title: String,
    pub author: String,
    /// May be unknown for older set texts — absent, not zero.
    #[serde(default)]
    pub year_published: Option<u16>,
    pub exam: String,
    /// Every cycle this is (or was) the set text for. A novel routinely spans
    /// more than one UTME — *The Lekki Headmaster* covers 2025 and 2026.
    #[serde(default)]
    pub year_prescribed: Vec<u16>,
    /// Which paper sets it: the Use-of-English reading text, or a
    /// Literature-in-English prescribed text. Consumers filter on this.
    #[serde(default = "default_novel_category")]
    pub category: String,
    /// At most one per exam — enforced at load. The current set text.
    #[serde(default)]
    pub featured: bool,
    pub synopsis: String,
    pub setting_place: String,
    pub setting_period: String,
    #[serde(default)]
    pub cover_image: Option<String>,
}

/// One file in `data/novels/`. The directory is the index — no separate list
/// to keep in sync. Dropping a novel is deleting its file.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct NovelDoc {
    #[serde(flatten)]
    pub novel: Novel,
    #[serde(default)]
    pub chapters: Vec<NovelChapter>,
    #[serde(default)]
    pub characters: Vec<NovelCharacter>,
    #[serde(default)]
    pub themes: Vec<NovelTheme>,
    #[serde(default)]
    pub questions: Vec<NovelQuestion>,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct NovelChapter {
    pub number: u8,
    pub title: String,
    /// Null means not yet written — absence is the signal (D16).
    #[serde(default)]
    pub summary: Option<String>,
    #[serde(default)]
    pub key_events: Vec<String>,
}

/// Character types use JAMB's own vocabulary (round/flat/foil/hero/antihero/
/// villain/heroine) because that is literally what the syllabus tests.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct NovelCharacter {
    pub name: String,
    pub role: String,
    pub character_type: String,
    pub description: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct NovelTheme {
    pub name: String,
    pub description: String,
    #[serde(default)]
    pub evidence: Vec<String>,
}

/// A quiz item about the book. Reuses Option/answer/Explanation machinery —
/// a novel question is answered, shuffled and explained exactly like a subject
/// question. It points at a chapter, not a subtopic, and the novel is the
/// passage, so there is no passage_id.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct NovelQuestion {
    pub id: String,
    #[serde(default)]
    pub chapter_number: Option<u8>,
    pub text: String,
    pub options: Vec<Choice>,
    /// An option id, same contract as Question.answer (D15).
    pub answer: String,
    #[serde(default)]
    pub explanation: Option<Explanation>,
    pub verified: bool,
}
