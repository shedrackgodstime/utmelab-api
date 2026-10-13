//! Exam schemes — how many questions a subject contributes to a real paper.
//!
//! D19: *"the scheme of examination is a constant, not content."* It is also
//! almost entirely **already in our data**: `Subject::objective_paper_questions`
//! carries the per-subject count (JAMB English 60, everything else 40), and
//! the `Exam` record (D66) carries the paper shape, duration and rules. So
//! this module reads those back rather than restating them.
//!
//! **No invented numbers.** Unverified counts are `None`, unverified durations
//! are `None`, and the English mark-scaling is left unmodelled with a note —
//! a scheme endpoint that guesses is worse than one that admits a gap.

use crate::bank::Store;

/// One subject's slot in an exam.
#[derive(Clone, Debug, serde::Serialize, utoipa::ToSchema)]
pub struct SubjectSlot {
    pub slug: String,
    pub name: String,
    pub compulsory: bool,
    /// MCQs the objective paper holds (from `objective_paper_questions`).
    /// `None` where unverified — the slot is carried but uncounted.
    pub questions: Option<u32>,
    /// `None` where the per-question mark is not uniform (English carries
    /// 1–3 depending on section), so a consumer must use each row's `marks`.
    pub marks_per_question: Option<f32>,
}

/// The exam's shape, derived from the subjects we actually carry.
#[derive(Clone, Debug, serde::Serialize, utoipa::ToSchema)]
pub struct Scheme {
    pub exam: String,
    /// `None` where unverified — absent, not zero (same rule as `year_published`).
    pub duration_minutes: Option<u32>,
    pub subjects: Vec<SubjectSlot>,
    /// Human-readable caveats a candidate or consumer must know. The WAEC
    /// "answer 10 of 13" problem (recorded, not solved) lives here.
    pub rules: Vec<String>,
    /// How many questions a full paper contains, summed from what we carry.
    /// This is a lower bound for any exam whose bank is incomplete — an English
    /// paper only counts if `use-of-english` has 60 real questions.
    pub questions_available: u32,
    /// Which subjects can actually fill a slot today.
    pub subjects_ready: Vec<String>,
    /// Subjects in a full paper, from the exam record. `None` where unstated
    /// — and an unstated paper shape is never complete.
    pub subjects_required: Option<u32>,
}

impl Scheme {
    /// Can this exam be assembled as a full mock right now? Requires every
    /// compulsory subject plus enough electives to reach the record's
    /// `subjects_required` (D41; D66 moved the shape out of the call site).
    pub fn is_complete(&self) -> bool {
        let required = match self.subjects_required {
            Some(n) => n as usize,
            // A paper whose shape cannot be stated is never complete.
            None => return false,
        };
        let ready = |slug: &str| self.subjects_ready.iter().any(|s| s == slug);
        let compulsory: Vec<&SubjectSlot> = self.subjects.iter().filter(|s| s.compulsory).collect();
        let compulsory_ready = compulsory.iter().all(|s| ready(&s.slug));
        let electives_ready = self
            .subjects
            .iter()
            .filter(|s| !s.compulsory && ready(&s.slug))
            .count();
        let electives_needed = required.saturating_sub(compulsory.len());
        compulsory_ready && electives_ready >= electives_needed
    }
}

/// Marks per question where it is uniform across the exam. JAMB's non-English
/// papers are 40 × 2.5; English is not, so it is left to each row.
fn uniform_marks(exam: &str, slug: &str) -> Option<f32> {
    match (exam, slug) {
        ("JAMB", "use-of-english") => None,
        (_, _) => Some(2.5),
    }
}

fn rules_for(exam: &crate::bank::Exam) -> Vec<String> {
    // The two generic lines stay code: they describe this bank's contract,
    // not any board. Everything board-specific rides in the exam record.
    let mut rules = vec![
        "Questions per subject come from each subject's `objective_paper_questions`; uncounted where null."
            .to_owned(),
        "Use-of-English questions carry varied marks (1–3); score each row's own `marks`.".to_owned(),
    ];
    rules.extend(exam.rules.iter().cloned());
    rules
}

/// Build the scheme for an exam from the bank, or `None` if we carry no
/// subject for it.
pub fn scheme_for(store: &dyn Store, exam: &str) -> Option<Scheme> {
    let subjects = store.subjects(exam);
    if subjects.is_empty() {
        return None;
    }
    // Validation guarantees every carried subject names a known exam, so a
    // missing record here is unreachable in a loaded bank.
    let record = store.exam(exam)?;

    let slots: Vec<SubjectSlot> = subjects
        .iter()
        .map(|s| SubjectSlot {
            slug: s.slug.clone(),
            name: s.name.clone(),
            compulsory: s.is_compulsory,
            questions: s.objective_paper_questions,
            marks_per_question: uniform_marks(exam, &s.slug),
        })
        .collect();

    // A slot with no verified count can never be ready: holding rows means
    // nothing against a number that was never stated.
    let subjects_ready: Vec<String> = subjects
        .iter()
        .filter(|s| {
            let need = match s.objective_paper_questions {
                Some(n) => n as usize,
                None => return false,
            };
            let page = store.questions_page(
                crate::bank::QuestionFilter {
                    exam: Some(exam),
                    subject: Some(&s.slug),
                    verified: Some(true),
                    ..Default::default()
                },
                1,
                u32::MAX,
            );
            page.total_records >= need
        })
        .map(|s| s.slug.clone())
        .collect();

    Some(Scheme {
        exam: exam.to_owned(),
        duration_minutes: record.duration_minutes,
        questions_available: subjects_ready
            .iter()
            .filter_map(|slug| subjects.iter().find(|s| &s.slug == slug))
            .filter_map(|s| s.objective_paper_questions)
            .sum(),
        subjects_ready,
        subjects: slots,
        subjects_required: record.subjects_required,
        rules: rules_for(record),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bank::{JsonStore, QuestionFilter};

    fn store() -> JsonStore {
        JsonStore::load(std::path::Path::new("data")).expect("bank loads")
    }

    #[test]
    fn scheme_reads_the_question_counts_out_of_the_subjects() {
        let bank = store();
        let scheme = scheme_for(&bank, "JAMB").expect("JAMB is carried");
        let english = scheme
            .subjects
            .iter()
            .find(|s| s.slug == "use-of-english")
            .expect("english is carried");
        assert_eq!(english.questions, Some(60), "JAMB English is 60 questions");
        assert!(english.compulsory, "English is compulsory");
        assert_eq!(
            english.marks_per_question, None,
            "English marks vary per row, so the scheme must not claim a rate"
        );
        let maths = scheme
            .subjects
            .iter()
            .find(|s| s.slug == "mathematics")
            .expect("maths is carried");
        assert_eq!(maths.questions, Some(40));
        assert_eq!(maths.marks_per_question, Some(2.5));
    }

    #[test]
    fn an_unknown_exam_has_no_scheme() {
        let bank = store();
        assert!(scheme_for(&bank, "WASSCE-2099").is_none());
    }

    #[test]
    fn unverified_duration_is_absent_rather_than_guessed() {
        let bank = store();
        assert_eq!(
            scheme_for(&bank, "JAMB").expect("JAMB").duration_minutes,
            Some(120)
        );
        assert_eq!(
            scheme_for(&bank, "WAEC").expect("WAEC").duration_minutes,
            None,
            "we have not verified WAEC's duration, so we do not publish one"
        );
    }

    #[test]
    fn waec_scheme_carries_the_attempt_a_subset_warning() {
        let bank = store();
        let scheme = scheme_for(&bank, "WAEC").expect("WAEC is carried");
        assert!(
            scheme.rules.iter().any(|r| r.contains("answer N of M")),
            "the recorded WAEC Paper 2 problem must reach the consumer"
        );
    }

    #[test]
    fn readiness_never_overstates_what_we_hold() {
        let bank = store();
        let scheme = scheme_for(&bank, "JAMB").expect("JAMB is carried");
        assert_eq!(scheme.subjects_required, Some(4));
        assert!(
            !scheme.is_complete(),
            "155 questions cannot fill 4 JAMB subjects — readiness must say so"
        );
        for slug in &scheme.subjects_ready {
            let page = bank.questions_page(
                QuestionFilter {
                    exam: Some("JAMB"),
                    subject: Some(slug.as_str()),
                    verified: Some(true),
                    ..Default::default()
                },
                1,
                200,
            );
            let required = scheme
                .subjects
                .iter()
                .find(|s| &s.slug == slug)
                .expect("ready subject has a slot")
                .questions
                .expect("a ready slot always carries a verified count");
            assert!(
                page.total_records >= required as usize,
                "{slug} was named ready without holding its {required} questions"
            );
        }
    }

    #[test]
    fn an_uncounted_slot_is_carried_but_never_ready() {
        // D66: a null count is carried on the scheme and can never be ready —
        // holding rows means nothing against a number never stated.
        let bank = store();
        let scheme = scheme_for(&bank, "WAEC").expect("WAEC is carried");
        assert!(
            scheme.subjects.iter().all(|s| s.questions.is_none()),
            "no WAEC count is verified, so every slot is uncounted"
        );
        assert!(
            scheme.subjects_ready.is_empty(),
            "uncounted slots must never read as ready"
        );
        assert!(
            !scheme.is_complete(),
            "an unstated paper shape is never complete"
        );
    }
}
