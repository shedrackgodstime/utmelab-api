//! Exam schemes and paper readiness: pure decisions over data the store
//! fetched. No DB, no HTTP here. The handler composes the reads; these
//! functions judge them, so the whole scheme is unit-testable with no
//! runtime and no network.
//!
//! D19: *"the scheme of examination is a constant, not content."* It is
//! also almost entirely already in our data: `subject.objective_paper_questions`
//! carries the per-subject count, the `Exam` record carries duration and
//! rules, and `exam_requirements` carries the scoping rules. So this module
//! reads those back rather than restating them, and admits a gap (`None`)
//! rather than guessing a number.

use std::collections::{HashMap, HashSet};

use rand::seq::SliceRandom;
use rand::SeedableRng;

use super::models::{Blueprint, Exam, Question, Requirement, Scheme, Subject, SubjectSlot};

/// Per-subject figures the store reads once per exam: how many rows we
/// hold, how many are verified, and the marks spread. An input to a
/// decision, so it lives here rather than among the wire shapes.
#[derive(Clone, Debug, Default)]
pub struct SubjectStat {
    pub held: u32,
    pub verified: u32,
    pub distinct_marks: u32,
    pub marks_low: f32,
}

/// No silent defaults: only a one-country exam may imply its scope. A
/// multi-country exam without an explicit country has no scope, and an
/// unscoped paper is never complete.
pub fn effective_country(record: &Exam, asked: Option<&str>) -> Option<String> {
    match asked {
        Some(c) => Some(c.to_owned()),
        None if record.countries.len() == 1 => Some(record.countries[0].clone()),
        None => None,
    }
}

/// The bank's own per-question rate, stated only where it can support the
/// claim: every held row agrees on one mark and the subject holds at least
/// a full paper's worth. A single stray row cannot set a paper's rate, and
/// a null paper size states no rate at all.
fn uniform_rate(stat: &SubjectStat, paper: Option<u32>) -> Option<f32> {
    let paper = paper?;
    if stat.distinct_marks == 1 && stat.held >= paper {
        Some(stat.marks_low)
    } else {
        None
    }
}

fn rules_for(record: &Exam) -> Vec<String> {
    // The two generic lines describe this bank's contract, not any board.
    // Everything board-specific rides in the exam record.
    let mut rules = vec![
        "Questions per subject come from each subject's `objective_paper_questions`; a subject with none is carried but never ready.".to_owned(),
        "A subject's per-question mark is stated only where every held row agrees and a full paper is on file; otherwise score each row's own `marks`.".to_owned(),
    ];
    rules.extend(record.rules.iter().cloned());
    rules
}

/// Build an exam's scheme from the bank. Readiness is decided here from the
/// verified counts the store supplied: a slot with no stated count can
/// never be ready, because holding rows means nothing against a number that
/// was never stated.
pub fn build_scheme(
    record: &Exam,
    subjects: &[Subject],
    stats: &HashMap<String, SubjectStat>,
    country: Option<String>,
    requirements: Vec<Requirement>,
) -> Scheme {
    let slots: Vec<SubjectSlot> = subjects
        .iter()
        .map(|s| {
            let stat = stats.get(&s.slug);
            SubjectSlot {
                slug: s.slug.clone(),
                name: s.name.clone(),
                compulsory: s.is_compulsory,
                questions: s.objective_paper_questions,
                marks_per_question: stat
                    .and_then(|st| uniform_rate(st, s.objective_paper_questions)),
            }
        })
        .collect();

    let subjects_ready: Vec<String> = subjects
        .iter()
        .filter(
            |s| match (s.objective_paper_questions, stats.get(&s.slug)) {
                (Some(need), Some(st)) => st.verified >= need,
                _ => false,
            },
        )
        .map(|s| s.slug.clone())
        .collect();

    let questions_available: u32 = subjects_ready
        .iter()
        .filter_map(|slug| subjects.iter().find(|s| &s.slug == slug))
        .filter_map(|s| s.objective_paper_questions)
        .sum();

    Scheme {
        exam: record.code.clone(),
        duration_minutes: record.duration_minutes,
        subjects: slots,
        rules: rules_for(record),
        questions_available,
        subjects_ready,
        country,
        requirements,
    }
}

/// Can this exam be assembled in this scheme's country scope? Every
/// requirement group must hold at least its `min_select` ready subjects. A
/// group with an empty subject list draws from every exam subject outside
/// the explicitly listed groups; no groups at all means the shape cannot be
/// stated, and an unstated paper is never complete.
pub fn is_complete(scheme: &Scheme) -> bool {
    if scheme.requirements.is_empty() {
        return false;
    }
    let claimed: HashSet<&str> = scheme
        .requirements
        .iter()
        .flat_map(|r| r.subjects.iter().map(String::as_str))
        .collect();
    let all: Vec<&str> = scheme.subjects.iter().map(|s| s.slug.as_str()).collect();
    scheme.requirements.iter().all(|r| {
        let pool: Vec<&str> = if r.subjects.is_empty() {
            all.iter()
                .filter(|s| !claimed.contains(*s))
                .copied()
                .collect()
        } else {
            r.subjects.iter().map(String::as_str).collect()
        };
        pool.iter()
            .filter(|s| scheme.subjects_ready.iter().any(|x| x == *s))
            .count()
            >= r.min_select as usize
    })
}

// ── assembly ────────────────────────────────────────────────────────────

/// One syllabus topic as stored, with its subtopics and the facts a reader
/// needs: order, weight, objectives, and stated country scope. Scope is not
/// applied here — an empty `countries` means every member country. The wire
/// form with live counts is `core::models::SyllabusTopic`.
#[derive(Clone, Debug)]
pub struct SyllabusTopic {
    pub slug: String,
    pub name: String,
    pub order: u32,
    pub weight: u32,
    pub objectives: Vec<String>,
    /// Countries this topic belongs to. Empty means every member country.
    pub countries: Vec<String>,
    pub subtopics: Vec<SyllabusSubtopic>,
}

/// One subtopic under a topic. The board states objectives at topic level
/// (D50); a subtopic carries its own only where the bank states them.
#[derive(Clone, Debug)]
pub struct SyllabusSubtopic {
    pub slug: String,
    pub name: String,
    pub order: u32,
    pub objectives: Vec<String>,
}

/// Everything assembly and readiness need for one exam subject, fetched
/// once by the store. `rows` holds every row the subject has, with
/// `verified` already derived under D62.
#[derive(Clone, Debug)]
pub struct SubjectBank {
    pub subject: Subject,
    pub blueprints: Vec<Blueprint>,
    pub syllabus: Vec<SyllabusTopic>,
    pub rows: Vec<Question>,
}

/// Which gate built a paper (D70). Disclosed on the wire: a consumer must
/// be able to tell a balanced mock from a full-length draw.
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, utoipa::ToSchema)]
#[serde(rename_all = "lowercase")]
pub enum PaperMode {
    /// Balanced per measured topic expectation (D68/D69).
    Blueprint,
    /// Full-length shuffled draw; topic mix not measured (D70).
    Count,
}

/// One paper section: a topic's drawn questions.
#[derive(Clone, Debug)]
pub struct PaperSection {
    pub topic: String,
    pub name: String,
    pub questions: Vec<Question>,
}

/// An assembled paper. Answers live nowhere in here — render answerless.
#[derive(Clone, Debug)]
pub struct AssembledPaper {
    pub exam: String,
    pub subject: String,
    pub seed: u64,
    pub mode: PaperMode,
    pub sections: Vec<PaperSection>,
}

impl AssembledPaper {
    pub fn total(&self) -> usize {
        self.sections.iter().map(|s| s.questions.len()).sum()
    }
}

/// One marked row. Correctness is reported only for submitted ids —
/// unsubmitted rows say unanswered, never the key (D69).
#[derive(Clone, Debug)]
pub struct MarkedQuestion {
    pub id: String,
    pub submitted: Option<String>,
    pub correct: bool,
}

/// One gap blocking assembly.
#[derive(Clone, Debug)]
pub struct ReadinessGap {
    pub topic: String,
    pub name: String,
    pub expected: f64,
    pub need: u32,
    pub have: usize,
}

/// Why the bank cannot fill this paper today. Two gates, two honest
/// vocabularies, so a consumer reading "need 40, have 39" never has to
/// guess which number it is waiting on.
#[derive(Debug)]
pub enum Unready {
    /// Blueprint-gated: named topics fall short of their expectation (D68).
    Blueprint {
        ready: usize,
        total: usize,
        gaps: Vec<ReadinessGap>,
    },
    /// Count-gated: the subject states no paper size, so none can be
    /// assembled without inventing one (D50 — absence is the answer).
    NoPaperSize { subject: String },
    /// Count-gated: verified rows below the stated paper size.
    ShortOfCount { need: u32, have: usize },
}

impl Unready {
    /// The client-facing sentence, shared by the paper and score endpoints
    /// so both refusals read identically.
    pub fn detail(&self) -> String {
        match self {
            Self::Blueprint { ready, total, gaps } => format!(
                "Only {ready}/{total} topics ready; short on: {}",
                gaps.iter()
                    .map(|g| format!("{} (need {}, have {})", g.topic, g.need, g.have))
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
            Self::NoPaperSize { subject } => format!(
                "{subject} states no objective paper size, so no full-length mock can be assembled without inventing one."
            ),
            Self::ShortOfCount { need, have } => {
                format!("Only {have} verified questions on file; a paper needs {need}.")
            }
        }
    }
}

/// One topic's servable, attributed rows.
pub struct TopicPool {
    pub name: String,
    pub rows: Vec<Question>,
}

/// The attributed bank for one exam subject: rows grouped by topic slug,
/// plus the verified rows no topic can claim (kept, not just counted —
/// count-gated assembly draws from them too, D70).
pub struct PoolSet {
    pub pools: HashMap<String, TopicPool>,
    pub unattributed: Vec<Question>,
}

impl PoolSet {
    pub fn unattributed_verified(&self) -> usize {
        self.unattributed.len()
    }
}

/// Attribute the subject's rows to topics through their subtopic tags, once.
/// Readiness and assembly both build from this — one bucketing, two uses.
/// Every syllabus topic gets a pool even when empty, so readiness can name a
/// measured topic that currently holds nothing.
pub fn pools(bank: &SubjectBank) -> PoolSet {
    let mut subtopic_topic: HashMap<String, String> = HashMap::new();
    let mut names: HashMap<String, String> = HashMap::new();
    for t in &bank.syllabus {
        names.insert(t.slug.clone(), t.name.clone());
        for st in &t.subtopics {
            subtopic_topic.insert(st.slug.clone(), t.slug.clone());
        }
    }
    let mut pools: HashMap<String, TopicPool> = HashMap::new();
    for (slug, name) in &names {
        pools.insert(
            slug.clone(),
            TopicPool {
                name: name.clone(),
                rows: Vec::new(),
            },
        );
    }
    let mut unattributed: Vec<Question> = Vec::new();
    for q in &bank.rows {
        match q.subtopic_id.as_deref().and_then(|s| subtopic_topic.get(s)) {
            Some(t) => pools
                .entry(t.clone())
                .or_insert_with(|| TopicPool {
                    name: names.get(t).cloned().unwrap_or_default(),
                    rows: Vec::new(),
                })
                .rows
                .push(q.clone()),
            // An untagged verified row is held, never assigned: a topic may
            // not claim a row that nothing attributes (D68).
            None => {
                if q.verified {
                    unattributed.push(q.clone());
                }
            }
        }
    }
    PoolSet {
        pools,
        unattributed,
    }
}

/// The cohorts (exam years) a subject holds rows for, ascending. Every row
/// carries the cohort it was prepared for, so this is the pool a per-paper
/// expectation would be drawn from.
pub fn cohorts(bank: &SubjectBank) -> Vec<u16> {
    let mut years: Vec<u16> = bank.rows.iter().map(|q| q.year).collect();
    years.sort_unstable();
    years.dedup();
    years
}

/// One topic's readiness account.
#[derive(Clone, Debug)]
pub struct TopicReadiness {
    pub topic: String,
    pub name: String,
    pub expected: f64,
    pub need: u32,
    pub held: usize,
    pub verified: usize,
    pub ready: bool,
}

/// A subject's readiness account: measured expectations against verified
/// coverage. `governed` false means the paper is served by the count gate
/// and `complete` is coverage arithmetic, not a promise (D71).
#[derive(Clone, Debug)]
pub struct SubjectReadiness {
    pub exam: String,
    pub subject: String,
    pub topics: Vec<TopicReadiness>,
    /// Blueprint rows with no measured expectation (unmapped/section rows).
    pub unmeasured: usize,
    /// Verified rows no topic can claim (untagged).
    pub unattributed: usize,
    pub ready: usize,
    pub complete: bool,
    pub governed: bool,
    pub cohorts: Vec<u16>,
}

impl SubjectReadiness {
    pub fn total(&self) -> usize {
        self.topics.len()
    }
}

/// Blueprint × coverage for one exam subject. Only measured-topic rows
/// judge; everything else is reported. Untagged verified rows are counted
/// as unattributed — assigning them would be fabrication (D68).
pub fn per_topic(bank: &SubjectBank) -> SubjectReadiness {
    let poolset = pools(bank);
    let mut topics = Vec::new();
    let mut unmeasured = 0usize;
    for bp in &bank.blueprints {
        let (slug, expected) = match (&bp.topic, bp.expected) {
            (Some(slug), Some(e)) if bp.level == "topic" => (slug.clone(), e),
            _ => {
                unmeasured += 1;
                continue;
            }
        };
        let (held, verified, name) = match poolset.pools.get(&slug) {
            Some(p) => (
                p.rows.len(),
                p.rows.iter().filter(|q| q.verified).count(),
                p.name.clone(),
            ),
            None => (0, 0, String::new()),
        };
        let need = expected.ceil() as u32;
        topics.push(TopicReadiness {
            topic: slug,
            name,
            expected,
            need,
            held,
            verified,
            ready: verified as u32 >= need,
        });
    }
    topics.sort_by(|a, b| a.topic.cmp(&b.topic));
    let ready = topics.iter().filter(|t| t.ready).count();
    let complete = !topics.is_empty() && ready == topics.len();
    let years = cohorts(bank);
    SubjectReadiness {
        exam: bank.subject.exam.clone(),
        subject: bank.subject.slug.clone(),
        topics,
        unmeasured,
        unattributed: poolset.unattributed_verified(),
        ready,
        complete,
        governed: governs(&bank.blueprints, years.len()),
        cohorts: years,
    }
}

/// Does the blueprint predicate govern this subject's papers (D70/D71)?
///
/// Three conditions, all required:
/// 1. measured per-topic expectations exist (a `topic`-level row carrying a
///    value — a range-reported row with `expected: null` is not measured);
/// 2. those rows cover the paper — their summed expectation reaches the
///    stated `paper_size`;
/// 3. the bank holds at least two cohorts for the subject.
///
/// Condition 3 is D71's, and it is the honest one: a per-paper topic
/// expectation is measured across years of papers, so one cohort can hold at
/// most what that one paper contained. With a single cohort the predicate is
/// either unmeetable or self-fulfilling, so the count gate serves it and the
/// readiness account says why.
pub fn governs(blueprints: &[Blueprint], cohorts: usize) -> bool {
    if cohorts < 2 {
        return false;
    }
    let measured: Vec<&Blueprint> = blueprints
        .iter()
        .filter(|b| b.level == "topic" && b.topic.is_some() && b.expected.is_some())
        .collect();
    if measured.is_empty() {
        return false;
    }
    let paper_size = blueprints.iter().map(|b| b.paper_size).max().unwrap_or(0);
    measured
        .iter()
        .map(|b| b.expected.unwrap_or(0.0).ceil() as u32)
        .sum::<u32>()
        >= paper_size
}

/// Assemble by the gate this subject earns: a whole measured topic mix
/// assembles by blueprint (D69), everything else by count (D70). Never
/// mixed, never falling back.
pub fn assemble(bank: &SubjectBank, seed: u64) -> Result<AssembledPaper, Unready> {
    if governs(&bank.blueprints, cohorts(bank).len()) {
        assemble_blueprint(bank, seed)
    } else {
        assemble_count(bank, seed)
    }
}

/// Balanced draw: `need` verified rows per ready topic, topics in slug order
/// through one RNG stream, so assembly is a pure function of (bank,
/// blueprint, seed).
fn assemble_blueprint(bank: &SubjectBank, seed: u64) -> Result<AssembledPaper, Unready> {
    let account = per_topic(bank);
    if !account.complete {
        return Err(Unready::Blueprint {
            ready: account.ready,
            total: account.total(),
            gaps: account
                .topics
                .iter()
                .filter(|t| !t.ready)
                .map(|t| ReadinessGap {
                    topic: t.topic.clone(),
                    name: t.name.clone(),
                    expected: t.expected,
                    need: t.need,
                    have: t.verified,
                })
                .collect(),
        });
    }
    let poolset = pools(bank);
    let mut rng = rand::rngs::StdRng::seed_from_u64(seed);
    // Draw order is slug order — fixed independently of insertion order.
    let mut slugs: Vec<&String> = poolset.pools.keys().collect();
    slugs.sort();
    let needs: HashMap<&str, u32> = account
        .topics
        .iter()
        .map(|t| (t.topic.as_str(), t.need))
        .collect();
    let mut sections = Vec::new();
    for slug in slugs {
        let Some(need) = needs.get(slug.as_str()).copied() else {
            continue;
        };
        let pool = &poolset.pools[slug];
        let mut rows: Vec<Question> = pool.rows.iter().filter(|q| q.verified).cloned().collect();
        rows.sort_by(|a, b| a.id.cmp(&b.id));
        // One stream across sections keeps the paper a pure function of the
        // seed — never reseed per section.
        rows.shuffle(&mut rng);
        sections.push(PaperSection {
            topic: slug.clone(),
            name: pool.name.clone(),
            questions: rows.into_iter().take(need as usize).collect(),
        });
    }
    Ok(AssembledPaper {
        exam: bank.subject.exam.clone(),
        subject: bank.subject.slug.clone(),
        seed,
        mode: PaperMode::Blueprint,
        sections,
    })
}

/// Count-gated draw (D70): a full-length shuffled paper from every verified
/// row the subject holds, whatever its topic mix. Sections group the *drawn*
/// rows by topic for presentation only — the draw itself is flat, so balance
/// is claimed nowhere and `mode` says so.
fn assemble_count(bank: &SubjectBank, seed: u64) -> Result<AssembledPaper, Unready> {
    let need = bank
        .subject
        .objective_paper_questions
        .ok_or_else(|| Unready::NoPaperSize {
            subject: bank.subject.slug.clone(),
        })?;
    let poolset = pools(bank);

    // A flat pool of verified rows. Each row carries one subtopic, so it
    // lands in exactly one pool, and the bank holds no duplicate content
    // today, so the draw needs no cross-pool dedup.
    let mut flat: Vec<(String, Question)> = Vec::new();
    for (slug, pool) in &poolset.pools {
        for q in pool.rows.iter().filter(|q| q.verified) {
            flat.push((slug.clone(), q.clone()));
        }
    }
    for q in &poolset.unattributed {
        flat.push((String::new(), q.clone()));
    }
    flat.sort_by(|a, b| a.1.id.cmp(&b.1.id));
    if (flat.len() as u32) < need {
        return Err(Unready::ShortOfCount {
            need,
            have: flat.len(),
        });
    }

    let mut rng = rand::rngs::StdRng::seed_from_u64(seed);
    let mut drawn = flat;
    drawn.shuffle(&mut rng);
    drawn.truncate(need as usize);

    // Group the drawn rows under their topics (slug order, untagged last).
    // Purely presentational: the draw above is flat.
    let mut grouped: Vec<PaperSection> = Vec::new();
    let mut index: HashMap<String, usize> = HashMap::new();
    for (slug, q) in drawn {
        let name = poolset
            .pools
            .get(&slug)
            .map(|p| p.name.clone())
            .unwrap_or_default();
        match index.get(&slug) {
            Some(i) => grouped[*i].questions.push(q),
            None => {
                index.insert(slug.clone(), grouped.len());
                grouped.push(PaperSection {
                    name: if slug.is_empty() {
                        "Untagged".to_string()
                    } else {
                        name
                    },
                    topic: slug,
                    questions: vec![q],
                });
            }
        }
    }
    grouped.sort_by(|a, b| {
        b.topic
            .is_empty()
            .cmp(&a.topic.is_empty())
            .then_with(|| a.topic.cmp(&b.topic))
    });
    Ok(AssembledPaper {
        exam: bank.subject.exam.clone(),
        subject: bank.subject.slug.clone(),
        seed,
        mode: PaperMode::Count,
        sections: grouped,
    })
}

/// Mark submitted answers against an assembled paper. Pure: same paper plus
/// same answers always mark identically, which is what makes scoring
/// stateless.
pub fn mark(
    paper: &AssembledPaper,
    answers: &HashMap<String, String>,
) -> (usize, Vec<MarkedQuestion>) {
    let mut score = 0usize;
    let mut out = Vec::new();
    for section in &paper.sections {
        for q in &section.questions {
            match answers.get(&q.id) {
                Some(given) => {
                    let correct = given == &q.answer;
                    if correct {
                        score += 1;
                    }
                    out.push(MarkedQuestion {
                        id: q.id.clone(),
                        submitted: Some(given.clone()),
                        correct,
                    });
                }
                None => out.push(MarkedQuestion {
                    id: q.id.clone(),
                    submitted: None,
                    correct: false,
                }),
            }
        }
    }
    (score, out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn exam(code: &str, countries: &[&str], duration: Option<u32>) -> Exam {
        Exam {
            code: code.to_string(),
            name: format!("{code} board"),
            countries: countries.iter().map(|c| c.to_string()).collect(),
            status: "live".to_string(),
            has_full_paper: None,
            subjects_required: None,
            duration_minutes: duration,
            rules: vec!["board rule".to_string()],
        }
    }

    fn subject(slug: &str, name: &str, paper: Option<u32>) -> Subject {
        Subject {
            slug: slug.to_string(),
            exam: "JAMB".to_string(),
            name: name.to_string(),
            is_compulsory: slug == "use-of-english",
            objective_paper_questions: paper,
        }
    }

    fn stat(held: u32, verified: u32, distinct: u32, mark: f32) -> SubjectStat {
        SubjectStat {
            held,
            verified,
            distinct_marks: distinct,
            marks_low: mark,
        }
    }

    #[test]
    fn a_single_country_exam_implies_its_scope() {
        let record = exam("JAMB", &["NG"], Some(120));
        assert_eq!(effective_country(&record, None), Some("NG".to_string()));
        assert_eq!(
            effective_country(&record, Some("GH")),
            Some("GH".to_string()),
            "an explicit scope always wins"
        );
    }

    #[test]
    fn a_multi_country_exam_has_no_implied_scope() {
        let record = exam("WAEC", &["NG", "GH"], None);
        assert_eq!(effective_country(&record, None), None);
    }

    #[test]
    fn a_slot_is_ready_only_when_its_stated_count_is_met_by_verified_rows() {
        let record = exam("JAMB", &["NG"], None);
        let subjects = vec![
            subject("use-of-english", "Use of English", Some(60)),
            subject("maths", "Mathematics", Some(40)),
            subject("physics", "Physics", Some(40)),
            subject("uncounted", "Uncounted", None),
        ];
        let mut stats = HashMap::new();
        stats.insert("use-of-english".to_string(), stat(167, 167, 4, 1.0));
        stats.insert("maths".to_string(), stat(40, 40, 1, 2.5));
        stats.insert("physics".to_string(), stat(39, 39, 1, 2.5));
        stats.insert("uncounted".to_string(), stat(500, 500, 1, 2.5));
        let scheme = build_scheme(&record, &subjects, &stats, Some("NG".into()), Vec::new());
        assert_eq!(scheme.subjects_ready, vec!["use-of-english", "maths"]);
        assert_eq!(scheme.questions_available, 100, "60 + 40 ready");
        // English marks vary, so no rate; maths holds a full paper at one
        // mark; physics is short and uncounted states nothing.
        let english = scheme.subjects.iter().find(|s| s.slug == "use-of-english");
        assert_eq!(english.and_then(|s| s.marks_per_question), None);
        let maths = scheme.subjects.iter().find(|s| s.slug == "maths");
        assert_eq!(maths.and_then(|s| s.marks_per_question), Some(2.5));
        let uncounted = scheme.subjects.iter().find(|s| s.slug == "uncounted");
        assert_eq!(uncounted.and_then(|s| s.marks_per_question), None);
    }

    #[test]
    fn an_unstated_paper_is_never_complete() {
        let record = exam("WAEC", &["NG", "GH"], None);
        let subjects = vec![subject("english-language", "English Language", Some(60))];
        let scheme = build_scheme(&record, &subjects, &HashMap::new(), None, Vec::new());
        assert!(
            !is_complete(&scheme),
            "no requirement rows, no completeness"
        );
    }

    #[test]
    fn completeness_holds_each_group_at_its_min_select() {
        let record = exam("JAMB", &["NG"], Some(120));
        let subjects = vec![
            subject("use-of-english", "Use of English", Some(60)),
            subject("maths", "Mathematics", Some(40)),
            subject("physics", "Physics", Some(40)),
        ];
        let mut stats = HashMap::new();
        stats.insert("use-of-english".to_string(), stat(60, 60, 4, 2.5));
        stats.insert("maths".to_string(), stat(40, 40, 1, 2.5));
        stats.insert("physics".to_string(), stat(40, 40, 1, 2.5));
        let requirements = vec![
            Requirement {
                group: "core".to_string(),
                min_select: 1,
                subjects: vec!["use-of-english".to_string()],
            },
            // The elective group draws from every subject not in `core`.
            Requirement {
                group: "elective".to_string(),
                min_select: 2,
                subjects: vec![],
            },
        ];
        let scheme = build_scheme(&record, &subjects, &stats, Some("NG".into()), requirements);
        assert!(is_complete(&scheme), "1 core + 2 electives are ready");
    }

    #[test]
    fn a_short_elective_group_is_incomplete() {
        let record = exam("JAMB", &["NG"], None);
        let subjects = vec![
            subject("use-of-english", "Use of English", Some(60)),
            subject("maths", "Mathematics", Some(40)),
        ];
        let mut stats = HashMap::new();
        stats.insert("use-of-english".to_string(), stat(60, 60, 4, 2.5));
        stats.insert("maths".to_string(), stat(10, 10, 1, 2.5));
        let requirements = vec![
            Requirement {
                group: "core".to_string(),
                min_select: 1,
                subjects: vec!["use-of-english".to_string()],
            },
            Requirement {
                group: "elective".to_string(),
                min_select: 3,
                subjects: vec![],
            },
        ];
        let scheme = build_scheme(&record, &subjects, &stats, Some("NG".into()), requirements);
        assert!(
            !is_complete(&scheme),
            "only one elective is ready, three needed"
        );
    }

    // ── assembly ────────────────────────────────────────────────────────

    fn question(id: &str, year: u16, subtopic: Option<&str>, verified: bool) -> Question {
        Question {
            id: id.to_string(),
            exam: "JAMB".to_string(),
            subject: "maths".to_string(),
            year,
            source: "authored".to_string(),
            text: crate::core::models::RichText {
                text: id.to_string(),
                inline: vec![],
            },
            options: vec![],
            answer: "a".to_string(),
            subtopic_id: subtopic.map(str::to_string),
            section: None,
            passage_id: None,
            explanation: None,
            marks: 1.0,
            difficulty: 1,
            verified,
        }
    }

    fn blueprint(topic: &str, expected: f64) -> Blueprint {
        Blueprint {
            exam: "JAMB".to_string(),
            subject: "maths".to_string(),
            level: "topic".to_string(),
            topic: Some(topic.to_string()),
            section: None,
            members: vec![],
            paper_size: 2,
            pct: None,
            pct_low: None,
            pct_high: None,
            expected: Some(expected),
            expected_low: None,
            expected_high: None,
            source: None,
            sample: None,
            method: "measured-topic".to_string(),
            confidence: None,
            status: "provisional".to_string(),
            note: String::new(),
        }
    }

    fn bank(rows: Vec<Question>) -> SubjectBank {
        SubjectBank {
            subject: Subject {
                slug: "maths".to_string(),
                exam: "JAMB".to_string(),
                name: "Mathematics".to_string(),
                is_compulsory: false,
                objective_paper_questions: Some(2),
            },
            blueprints: vec![],
            syllabus: vec![SyllabusTopic {
                slug: "algebra".to_string(),
                name: "Algebra".to_string(),
                order: 1,
                weight: 0,
                objectives: vec![],
                countries: vec![],
                subtopics: vec![SyllabusSubtopic {
                    slug: "linear".to_string(),
                    name: "Linear equations".to_string(),
                    order: 1,
                    objectives: vec![],
                }],
            }],
            rows,
        }
    }

    fn paper_ids(paper: &AssembledPaper) -> Vec<String> {
        paper
            .sections
            .iter()
            .flat_map(|s| s.questions.iter().map(|q| q.id.clone()))
            .collect()
    }

    #[test]
    fn a_count_paper_draws_a_full_paper_of_verified_rows_only() {
        let b = bank(vec![
            question("q1", 2025, Some("linear"), true),
            question("q2", 2025, None, true),
            question("q3", 2025, Some("linear"), false),
        ]);
        let paper = assemble(&b, 1).expect("count gate serves it");
        assert_eq!(paper.mode, PaperMode::Count);
        assert_eq!(paper.total(), 2);
        let ids = paper_ids(&paper);
        assert!(ids.contains(&"q1".to_string()) && ids.contains(&"q2".to_string()));
        assert!(
            !ids.contains(&"q3".to_string()),
            "unverified rows never ride a paper"
        );
    }

    #[test]
    fn the_same_seed_builds_the_same_paper() {
        let rows: Vec<Question> = (0..20)
            .map(|i| question(&format!("q{i:02}"), 2025, None, true))
            .collect();
        let b = bank(rows);
        let a1 = assemble(&b, 7).expect("assemble");
        let a2 = assemble(&b, 7).expect("assemble");
        assert_eq!(paper_ids(&a1), paper_ids(&a2), "same seed, same paper");
    }

    #[test]
    fn a_subject_without_a_stated_paper_size_cannot_assemble() {
        let mut b = bank(vec![question("q1", 2025, None, true)]);
        b.subject.objective_paper_questions = None;
        let err = assemble(&b, 1).expect_err("no paper size");
        assert!(matches!(err, Unready::NoPaperSize { .. }));
    }

    #[test]
    fn a_short_count_paper_names_the_shortfall() {
        let b = bank(vec![question("q1", 2025, None, true)]);
        match assemble(&b, 1).expect_err("short") {
            Unready::ShortOfCount { need, have } => {
                assert_eq!(need, 2);
                assert_eq!(have, 1);
            }
            other => panic!("wrong gate: {other:?}"),
        }
    }

    #[test]
    fn a_single_cohort_never_activates_the_blueprint_gate() {
        let mut b = bank(vec![
            question("q1", 2025, Some("linear"), true),
            question("q2", 2025, Some("linear"), true),
        ]);
        b.blueprints = vec![blueprint("algebra", 2.0)];
        assert!(
            !governs(&b.blueprints, cohorts(&b).len()),
            "one cohort is not a measured expectation (D71)"
        );
        let paper = assemble(&b, 1).expect("count gate serves it");
        assert_eq!(paper.mode, PaperMode::Count);
    }

    #[test]
    fn marking_reports_only_submitted_rows() {
        let b = bank(vec![
            question("q1", 2025, None, true),
            question("q2", 2025, None, true),
        ]);
        let paper = assemble(&b, 1).expect("assemble");
        let mut answers = HashMap::new();
        answers.insert("q1".to_string(), "a".to_string());
        answers.insert("q2".to_string(), "b".to_string());
        let (score, marked) = mark(&paper, &answers);
        assert_eq!(score, 1);
        assert_eq!(marked.len(), 2);
        assert!(marked.iter().find(|m| m.id == "q1").expect("q1").correct);
        assert!(!marked.iter().find(|m| m.id == "q2").expect("q2").correct);
    }
}
