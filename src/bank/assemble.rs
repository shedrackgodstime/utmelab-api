//! Single-subject paper assembly (P4 payoff, D69 + D70).
//!
//! Deterministic, answerless, refused until the bank can fill the paper: one
//! seeded RNG stream shuffles the draw and takes the rows the gate names, so
//! the same seed always builds the same paper and scoring is a stateless
//! re-assembly — no paper table, no stored attempts. Answers never ride the
//! paper; the score endpoint marks only submitted ids, so correctness is
//! revealed solely for guesses already made.
//!
//! Two gates, never mixed (D70):
//! * **blueprint** — the subject's per-topic mix is measured *and covers the
//!   paper* (D70's `blueprint_governs`), so each topic's `need =
//!   ceil(expected)` rows are drawn and the paper is balanced by
//!   construction. Refused until every measured topic is ready.
//! * **count** — no measurement exists, so a full-length shuffled draw of
//!   deduped verified rows is what "mock" has always meant. Refused below the
//!   subject's stated paper size; the paper says `mode: "count"` so no
//!   consumer mistakes it for a balanced mock.
//!
//! Where the measurement governs, balance is enforced rather than
//! approximated; where it does not (no measurement, or one that covers only
//! part of the paper), the paper is a labelled full-length draw.

use crate::bank::Store;
use crate::bank::model::Question;
use crate::bank::readiness::{Blueprint, TopicPool, blueprint_governs, per_topic, topic_pools};
use rand::SeedableRng;
use rand::seq::SliceRandom;
use std::collections::{HashMap, HashSet};

/// Which gate built the paper (D70). Disclosed on the wire: a consumer must
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
//  unsubmitted rows say unanswered, never the key (D69).
#[derive(Clone, Debug)]
pub struct MarkedQuestion {
    pub id: String,
    pub submitted: Option<String>,
    pub correct: bool,
}

/// Mark submitted answers against an assembled paper. Pure: same paper +
/// same answers always mark identically, which is what makes scoring
/// stateless.
pub fn mark(
    paper: &AssembledPaper,
    answers: &std::collections::HashMap<String, String>,
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
/// vocabularies — a consumer reading "need 40, have 39" must not have to
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
    /// Count-gated: deduped verified rows below the stated paper size.
    ShortOfCount { need: u32, have: usize },
}

impl Unready {
    /// The client-facing sentence, shared by the paper and score endpoints so
    /// both refusals read identically.
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
                format!("Only {have} verified, distinct questions; a paper needs {need}.")
            }
        }
    }
}

/// Assemble by the gate this subject earns: measured topic mix assembles by
/// blueprint (D69), everything else by count (D70). Never mixed, never
/// falling back.
pub fn assemble(
    store: &dyn Store,
    blueprints: &[Blueprint],
    exam: &str,
    subject: &str,
    country: Option<&str>,
    seed: u64,
) -> Result<AssembledPaper, Unready> {
    if blueprint_governs(blueprints, exam, subject) {
        assemble_blueprint(store, blueprints, exam, subject, country, seed)
    } else {
        assemble_count(store, exam, subject, country, seed)
    }
}

/// Balanced draw: `need` verified deduped rows per ready topic, topics in
/// slug order through one RNG stream, so assembly is a pure function of
/// (bank, blueprint, seed).
pub fn assemble_blueprint(
    store: &dyn Store,
    blueprints: &[Blueprint],
    exam: &str,
    subject: &str,
    country: Option<&str>,
    seed: u64,
) -> Result<AssembledPaper, Unready> {
    let account = per_topic(store, blueprints, exam, subject, country);
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
                    have: t.deduped,
                })
                .collect(),
        });
    }
    let pools = topic_pools(store, exam, subject, country);
    let mut rng = rand::rngs::StdRng::seed_from_u64(seed);
    // Draw order is slug order — fixed independently of insertion order.
    let mut slugs: Vec<&String> = pools.pools.keys().collect();
    slugs.sort();
    let needs: HashMap<&str, u32> = account
        .topics
        .iter()
        .map(|t| (t.topic.as_str(), t.need))
        .collect();
    let mut sections = Vec::new();
    for slug in slugs {
        let need = match needs.get(slug.as_str()) {
            Some(n) => *n as usize,
            None => continue,
        };
        let pool: &TopicPool = &pools.pools[slug];
        // Verified only, deduped by fingerprint (first id wins), shuffled.
        let mut seen = HashSet::new();
        let mut rows: Vec<&Question> = pool.rows.iter().filter(|q| q.verified).collect();
        rows.sort_by(|a, b| a.id.cmp(&b.id));
        rows.retain(|q| seen.insert(q.content_fingerprint()));
        rows.shuffle(&mut rng);
        // One stream across sections keeps the paper a pure function of
        // the seed — never reseed per section.
        sections.push(PaperSection {
            topic: slug.clone(),
            name: pool.name.clone(),
            questions: rows.into_iter().take(need).cloned().collect(),
        });
    }
    Ok(AssembledPaper {
        exam: exam.to_string(),
        subject: subject.to_string(),
        seed,
        mode: PaperMode::Blueprint,
        sections,
    })
}

/// Count-gated draw (D70): a full-length shuffled paper from every deduped
/// verified row the subject holds, whatever its topic mix. Sections group the
/// *drawn* rows by topic for presentation only — the draw itself is flat, so
/// balance is claimed nowhere and `mode` says so.
pub fn assemble_count(
    store: &dyn Store,
    exam: &str,
    subject: &str,
    country: Option<&str>,
    seed: u64,
) -> Result<AssembledPaper, Unready> {
    let need = store
        .subject(exam, subject)
        .map(|s| s.objective_paper_questions)
        .unwrap_or(None)
        .ok_or_else(|| Unready::NoPaperSize {
            subject: subject.to_string(),
        })?;
    let pools = topic_pools(store, exam, subject, country);

    // One flat pool in id order, deduped by fingerprint across *all* pools —
    // the same stem tagged two topics is one question, not two.
    let mut seen = HashSet::new();
    let mut flat: Vec<(String, Question)> = Vec::new();
    for (slug, pool) in &pools.pools {
        for q in pool.rows.iter().filter(|q| q.verified) {
            if seen.insert(q.content_fingerprint()) {
                flat.push((slug.clone(), q.clone()));
            }
        }
    }
    for q in pools.unattributed.iter() {
        if seen.insert(q.content_fingerprint()) {
            flat.push((String::new(), q.clone()));
        }
    }
    flat.sort_by(|a, b| a.1.id.cmp(&b.1.id));
    if (flat.len() as u32) < need {
        return Err(Unready::ShortOfCount {
            need,
            have: flat.len(),
        });
    }

    let mut rng = rand::rngs::StdRng::seed_from_u64(seed);
    let mut drawn: Vec<(String, Question)> = flat;
    drawn.shuffle(&mut rng);
    drawn.truncate(need as usize);

    // Group the drawn rows under their topics (slug order, untagged last).
    // Purely presentational: the draw above is flat, so balance is claimed
    // nowhere and `mode` says so.
    let mut grouped: Vec<PaperSection> = Vec::new();
    let mut index: HashMap<String, usize> = HashMap::new();
    for (slug, q) in drawn {
        let name = pools
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
                    topic: slug.clone(),
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
        exam: exam.to_string(),
        subject: subject.to_string(),
        seed,
        mode: PaperMode::Count,
        sections: grouped,
    })
}
