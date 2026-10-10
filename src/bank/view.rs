//! Wire projections for the bank.
//!
//! Split from the stored shape so the two can differ without either lying about
//! the other. One rule matters here: **the answer and the explanation are
//! withheld by default** (D27). A quiz consumer needs the stem first, and an
//! answer riding along in a default payload gets rendered by accident.

use serde::Serialize;
use utoipa::ToSchema;

use super::model::{Choice, Explanation, Question};

#[derive(Serialize, ToSchema)]
pub struct RenderedQuestion {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub year: u16,
    pub text: String,
    pub options: Vec<Choice>,
    pub section: Option<String>,
    pub image: Option<String>,
    pub marks: f32,
    pub difficulty: u8,
    pub verified: bool,

    /// Present only when explanations were requested.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub answer: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub explanation: Option<Explanation>,
}

pub fn render(q: &Question, include_explanation: bool) -> RenderedQuestion {
    RenderedQuestion {
        id: q.id.clone(),
        exam: q.exam.clone(),
        subject: q.subject.clone(),
        year: q.year,
        text: q.text.clone(),
        options: q.options.clone(),
        section: q.section.clone(),
        image: q.image.clone(),
        marks: q.marks,
        difficulty: q.difficulty,
        verified: q.verified,
        answer: include_explanation.then(|| q.answer.clone()),
        explanation: include_explanation.then(|| q.explanation.clone()).flatten(),
    }
}
