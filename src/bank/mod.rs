//! The bank: domain types, the storage seam, and the JSON implementation.
//!
//! Nothing in here knows about HTTP. Both `api/` and `app/` depend on it; it
//! depends on neither.

mod json;
mod model;
mod store;
mod view;

pub use json::{JsonStore, StoreError};
pub use model::{Novel, NovelDoc, Subject, Subtopic, Topic};
pub use store::{DEFAULT_PER_PAGE, MAX_PER_PAGE, QuestionFilter, Store};
pub use view::{RenderedNovelQuestion, RenderedQuestion, render, render_novel_question};

use serde::Serialize;
use utoipa::ToSchema;

/// The syllabus tree with coverage counts (D19).
#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct Syllabus {
    pub exam: String,
    pub subject: Subject,
    pub topics: Vec<SyllabusTopic>,
    pub summary: SyllabusSummary,
}

#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct SyllabusTopic {
    pub slug: String,
    pub name: String,
    pub order: u32,
    pub weight: u32,
    pub question_count: usize,
    /// Notes are shape-only until D18 is activated.
    pub note_available: bool,
    pub subtopics: Vec<SyllabusSubtopic>,
}

#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct SyllabusSubtopic {
    pub slug: String,
    pub name: String,
    pub order: u32,
    pub question_count: usize,
    pub objectives: Vec<String>,
}

#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct SyllabusSummary {
    pub topics: usize,
    pub topics_with_questions: usize,
    pub subtopics: usize,
    pub subtopics_with_questions: usize,
    pub questions: usize,
}
