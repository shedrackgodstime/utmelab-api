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
    /// Country scope this scheme was computed for, if any. Absent means the
    /// full honest view — and completeness is only ever claimed for a scope.
    pub country: Option<String>,
    /// The paper-assembly rules evaluated here, copied from the exam's
    /// requirement rows so a consumer sees what completeness meant.
    pub requirements: Vec<crate::bank::Requirement>,
}

impl Scheme {
    /// Can this exam be assembled as a full mock right now, in this scheme's
    /// country scope? Every requirement group must hold at least its
    /// `min_select` ready subjects. A group with an empty subject list draws
    /// from every exam subject outside explicitly listed groups; no groups at
    /// all means the shape cannot be stated, and an unstated paper is never
    /// complete (D41).
    pub fn is_complete(&self) -> bool {
        if self.requirements.is_empty() {
            return false;
        }
        let claimed: std::collections::HashSet<&str> = self
            .requirements
            .iter()
            .flat_map(|r| r.subjects.iter().map(String::as_str))
            .collect();
        let all: Vec<&str> = self.subjects.iter().map(|s| s.slug.as_str()).collect();
        self.requirements.iter().all(|r| {
            let pool: Vec<&str> = if r.subjects.is_empty() {
                all.iter()
                    .filter(|s| !claimed.contains(*s))
                    .copied()
                    .collect()
            } else {
                r.subjects.iter().map(String::as_str).collect()
            };
            pool.iter()
                .filter(|s| self.subjects_ready.iter().any(|x| x == *s))
                .count()
                >= r.min_select as usize
        })
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
///
/// `country` scopes readiness and completeness: a single-country exam
/// defaults to its only country, anything else needs the parameter said out
/// loud — an unstated scope is never complete, and readiness counts only
/// in-scope rows.
pub fn scheme_for(store: &dyn Store, exam: &str, country: Option<&str>) -> Option<Scheme> {
    let subjects = store.subjects(exam);
    if subjects.is_empty() {
        return None;
    }
    // Validation guarantees every carried subject names a known exam, so a
    // missing record here is unreachable in a loaded bank.
    let record = store.exam(exam)?;

    // No silent defaults: only a one-country exam may imply its scope.
    let effective: Option<String> = match country {
        Some(cc) => Some(cc.to_owned()),
        None if record.countries.len() == 1 => Some(record.countries[0].clone()),
        None => None,
    };

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
                    country: effective.as_deref(),
                    ..Default::default()
                },
                1,
                u32::MAX,
            );
            page.total_records >= need
        })
        .map(|s| s.slug.clone())
        .collect();

    let requirements: Vec<crate::bank::Requirement> = match effective.as_deref() {
        Some(cc) => store.requirements(exam, cc).into_iter().cloned().collect(),
        None => Vec::new(),
    };

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
        country: effective,
        requirements,
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
        let scheme = scheme_for(&bank, "JAMB", None).expect("JAMB is carried");
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
        assert!(scheme_for(&bank, "WASSCE-2099", None).is_none());
    }

    #[test]
    fn unverified_duration_is_absent_rather_than_guessed() {
        let bank = store();
        assert_eq!(
            scheme_for(&bank, "JAMB", None)
                .expect("JAMB")
                .duration_minutes,
            Some(120)
        );
        assert_eq!(
            scheme_for(&bank, "WAEC", None)
                .expect("WAEC")
                .duration_minutes,
            None,
            "we have not verified WAEC's duration, so we do not publish one"
        );
    }

    #[test]
    fn waec_scheme_carries_the_attempt_a_subset_warning() {
        let bank = store();
        let scheme = scheme_for(&bank, "WAEC", None).expect("WAEC is carried");
        assert!(
            scheme.rules.iter().any(|r| r.contains("answer N of M")),
            "the recorded WAEC Paper 2 problem must reach the consumer"
        );
    }

    #[test]
    fn readiness_never_overstates_what_we_hold() {
        let bank = store();
        let scheme = scheme_for(&bank, "JAMB", None).expect("JAMB is carried");
        assert_eq!(scheme.country, Some("NG".to_owned()));
        assert_eq!(scheme.requirements.len(), 2);
        assert!(
            scheme.is_complete(),
            "english, maths, physics and chemistry all fill their slots — readiness must say so"
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
        let scheme = scheme_for(&bank, "WAEC", None).expect("WAEC is carried");
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

    #[test]
    fn a_single_country_exam_implies_its_scope() {
        // JAMB runs in NG only: no country param needed, and the record's
        // requirement rows drive completeness.
        let bank = store();
        let scheme = scheme_for(&bank, "JAMB", None).expect("JAMB is carried");
        assert_eq!(scheme.country, Some("NG".to_owned()));
        assert_eq!(scheme.requirements.len(), 2);
        let explicit = scheme_for(&bank, "JAMB", Some("NG")).expect("JAMB is carried");
        assert_eq!(explicit.country, Some("NG".to_owned()));
        assert_eq!(explicit.subjects_ready, scheme.subjects_ready);
    }

    #[test]
    fn a_multi_country_exam_without_a_scope_is_never_complete() {
        // WAEC runs in five countries: without ?country= there is no scope,
        // no requirements, and no completeness — but the tree still serves.
        let bank = store();
        let scheme = scheme_for(&bank, "WAEC", None).expect("WAEC is carried");
        assert_eq!(scheme.country, None);
        assert!(scheme.requirements.is_empty());
        assert!(!scheme.is_complete());
    }
}
