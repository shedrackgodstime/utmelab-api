//! Single-subject paper assembly (P4 payoff, D69).
//!
//! Deterministic, answerless, refused until complete: one seeded RNG stream
//! over topics in slug order shuffles deduped verified rows per ready topic
//! and takes `need` each, so the same seed always builds the same paper and
//! scoring is a stateless re-assembly — no paper table, no stored attempts.
//! Answers never ride the paper; the score endpoint marks only submitted
//! ids, so correctness is revealed solely for guesses already made.

use crate::bank::Store;
use crate::bank::model::Question;
use crate::bank::readiness::{Blueprint, TopicPool, per_topic, topic_pools};
use rand::SeedableRng;
use rand::seq::SliceRandom;
use std::collections::{HashMap, HashSet};

/// One paper section: a ready topic's drawn questions.
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

/// The bank cannot fill this paper today.
#[derive(Debug)]
pub struct Unready {
    pub ready: usize,
    pub total: usize,
    pub gaps: Vec<ReadinessGap>,
}

/// Build the paper for `seed`, or name exactly what is missing.
/// Topics run in slug order through one RNG stream, so assembly is a pure
/// function of (bank, blueprint, seed).
pub fn assemble(
    store: &dyn Store,
    blueprints: &[Blueprint],
    exam: &str,
    subject: &str,
    country: Option<&str>,
    seed: u64,
) -> Result<AssembledPaper, Unready> {
    let account = per_topic(store, blueprints, exam, subject, country);
    if !account.complete {
        return Err(Unready {
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
        sections,
    })
}
