//! What the API answers with.
//!
//! Every type here is a response, not a stored row. The `Rendered*` types
//! are the served form of a domain type (the answer is withheld unless it
//! was asked for), and the page envelope is shared so a new paged endpoint
//! copies a constructor instead of a formula. `ReportFiled` is the outcome
//! of a write a consumer made.

use super::domain::{Choice, Explanation, RichText, Subject};

/// One page of a collection in the shape every paged endpoint serves.
/// The envelope lives here, once, so a new paged endpoint cannot
/// re-derive the counts: `total_pages` comes from `total_records` and
/// `per_page` through [`Page::new`], never from the call site.
///
/// The collection field is `questions` because both surfaces that page
/// today page questions; a future non-question page renames it there.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct Page<T> {
    pub questions: Vec<T>,
    pub page: u32,
    pub per_page: u32,
    pub total_pages: u32,
    pub total_records: usize,
    pub includes_explanation: bool,
}

impl<T> Page<T> {
    /// Build the envelope. `per_page` has already passed
    /// [`crate::core::catalog::page_bounds`], so it is never zero.
    pub fn new(
        questions: Vec<T>,
        page: u32,
        per_page: u32,
        total_records: usize,
        includes_explanation: bool,
    ) -> Self {
        Self {
            questions,
            page,
            per_page,
            total_pages: if total_records == 0 {
                0
            } else {
                total_records.div_ceil(per_page as usize) as u32
            },
            total_records,
            includes_explanation,
        }
    }
}

/// Page of questions as served. Counts describe the filtered set, not
/// the bank — a consumer pages `total_pages`, never guesses.
pub type QuestionPageResponse = Page<RenderedQuestion>;

/// Outcome of filing a consumer flag. `duplicate` is true when an
/// identical filing already existed; `id` is then the original's.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct ReportFiled {
    pub id: String,
    pub target_type: String,
    pub target_id: String,
    pub reason: String,
    pub duplicate: bool,
}

/// One node of a subject's syllabus as served: what you must be able to do
/// (objectives) beside what you can actually practise (`question_count`).
/// The stored form is `core::papers::SyllabusTopic`; this one adds counts.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct SyllabusTopic {
    pub slug: String,
    pub name: String,
    pub order: u32,
    pub weight: u32,
    pub question_count: usize,
    pub objectives: Vec<String>,
    /// Countries this topic belongs to. Empty means every member country.
    pub countries: Vec<String>,
    pub subtopics: Vec<SyllabusSubtopic>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct SyllabusSubtopic {
    pub slug: String,
    pub name: String,
    pub order: u32,
    pub question_count: usize,
    pub objectives: Vec<String>,
    /// Inherited from the parent topic — a subtopic carries no scope of its own.
    pub countries: Vec<String>,
}

/// Counts over a subject's syllabus, for progress bars and checklists.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct SyllabusSummary {
    pub topics: usize,
    pub topics_with_questions: usize,
    pub subtopics: usize,
    pub subtopics_with_questions: usize,
    pub questions: usize,
}

/// One subject's whole topic tree with live counts.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct Syllabus {
    pub exam: String,
    pub subject: Subject,
    pub topics: Vec<SyllabusTopic>,
    pub summary: SyllabusSummary,
}

/// Coverage without the tree: the same counts and nothing else.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct Coverage {
    pub exam: String,
    pub subject: Subject,
    pub summary: SyllabusSummary,
}

/// One novel quiz row as served. `novel_id` is stamped by the caller —
/// the stored row does not carry it.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct RenderedNovelQuestion {
    pub id: String,
    pub novel_id: String,
    pub chapter_number: Option<u8>,
    pub text: RichText,
    pub options: Vec<Choice>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub answer: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub explanation: Option<Explanation>,
    pub verified: bool,
}

/// One page of novel quiz rows. Counts describe the chapter-filtered
/// set, same envelope rule as questions.
pub type NovelQuestionPage = Page<RenderedNovelQuestion>;

/// One question as served. Identical to storage except the answer and
/// working, which are present only when explicitly requested — an answer
/// in a default payload gets rendered by somebody, eventually, by
/// accident. `verified` comes from the verification log, never a stored flag.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct RenderedQuestion {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub year: u16,
    pub source: String,
    pub text: RichText,
    pub options: Vec<Choice>,
    pub section: Option<String>,
    /// A stimulus this row belongs to — fetch it, never ignore it: the
    /// stem may be unanswerable without it.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub passage_id: Option<String>,
    pub marks: f32,
    pub difficulty: u8,
    pub verified: bool,
    /// Present only when explanations were requested.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub answer: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub explanation: Option<Explanation>,
}

/// Totals for the discovery surface, served without a key.
///
/// `held` is every row on file; `verified` is the subset whose latest human
/// verification passed under the rule every keyed read applies (see
/// `store::catalog`). Both are here on purpose: a funnel can say "2,244
/// questions, 2,190 human-verified", and either number agrees with what a key
/// actually fetches (`?verified=true` for the second).
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct PublicSummary {
    pub exams: u32,
    pub subjects: u32,
    pub held: u32,
    pub verified: u32,
}

/// One exam as the discovery surface serves it: identity, size, and its
/// subjects. No board rules, no paper shape, nothing a key is for.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct PublicExam {
    pub code: String,
    pub name: String,
    /// Member countries running this exam. Empty where unstated.
    pub countries: Vec<String>,
    pub status: String,
    /// Minutes for a full sitting. Null where the board's shape is unstated.
    pub duration_minutes: Option<u32>,
    /// Rows held, summed over `subjects`.
    pub held: u32,
    /// Human-verified rows, summed over `subjects`.
    pub verified: u32,
    pub subjects: Vec<PublicSubject>,
}

/// One subject on the discovery surface: the name, whether the board makes
/// it compulsory, and how many rows sit behind it.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct PublicSubject {
    pub slug: String,
    pub name: String,
    pub is_compulsory: bool,
    /// MCQs the objective paper holds. Null where unverified, never zero
    /// standing in for a fact nobody stated.
    pub objective_paper_questions: Option<u32>,
    pub held: u32,
    pub verified: u32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn page_envelope_counts_whole_and_partial_pages() {
        let empty: Page<u8> = Page::new(vec![], 1, 50, 0, false);
        assert_eq!(empty.total_pages, 0, "an empty set has no pages");
        assert_eq!(empty.total_records, 0);

        let exact: Page<u8> = Page::new(vec![1], 1, 50, 100, false);
        assert_eq!(exact.total_pages, 2, "100 over 50 is exactly two pages");

        let partial: Page<u8> = Page::new(vec![1], 3, 50, 101, true);
        assert_eq!(partial.total_pages, 3, "101 over 50 rounds up to three");
        assert_eq!(partial.page, 3);
        assert!(partial.includes_explanation);
    }
}
