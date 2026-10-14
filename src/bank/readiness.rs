//! Per-topic readiness: blueprint × coverage (P4 step 1, D68).
//!
//! For each measured blueprint row: `need = ceil(expected)`; `have` =
//! distinct content fingerprints over verified, servable, in-scope rows
//! attributed through subtopic → topic. Ready iff `have >= need`.
//! Untagged rows count as unattributed, never assigned. Topics without a
//! measured expectation are reported, not judged.
//!
//! Source-agnostic: works over `&dyn Store`, so file and Turso banks answer
//! identically. No HTTP anywhere in it.

use crate::bank::model::Question;
use crate::bank::{QuestionFilter, Store};
use std::collections::{HashMap, HashSet};

/// One row of `data/blueprints.json` (D63). Field-for-field with the file;
/// `None` where the file carries null.
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct Blueprint {
    pub exam: String,
    pub subject: String,
    pub level: String,
    pub topic: Option<String>,
    pub section: Option<String>,
    #[serde(default)]
    pub members: Vec<String>,
    pub paper_size: u32,
    pub pct: Option<f64>,
    pub pct_low: Option<f64>,
    pub pct_high: Option<f64>,
    pub expected: Option<f64>,
    pub expected_low: Option<f64>,
    pub expected_high: Option<f64>,
    pub source: Option<String>,
    pub sample: Option<String>,
    pub method: String,
    pub confidence: Option<String>,
    pub status: String,
    #[serde(default)]
    pub note: String,
}

/// Read every blueprint row. Fails on unreadable or unparseable files —
/// expectations with no provenance are worse than none.
pub fn load_blueprints(dir: &std::path::Path) -> Result<Vec<Blueprint>, String> {
    let raw = std::fs::read_to_string(dir.join("blueprints.json")).map_err(|e| e.to_string())?;
    serde_json::from_str(&raw).map_err(|e| e.to_string())
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
    pub deduped: usize,
    pub ready: bool,
}

/// A subject's readiness account.
#[derive(Debug)]
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
}

impl SubjectReadiness {
    pub fn total(&self) -> usize {
        self.topics.len()
    }
}

/// Blueprint × coverage for one exam subject. Only measured-topic rows
/// judge; everything else is reported. Untagged verified rows are counted
/// as unattributed — assigning them would be fabrication (D68).
pub fn per_topic(
    store: &dyn Store,
    blueprints: &[Blueprint],
    exam: &str,
    subject: &str,
    country: Option<&str>,
) -> SubjectReadiness {
    let pools = topic_pools(store, exam, subject, country);

    let mut topics = Vec::new();
    let mut unmeasured = 0usize;
    for bp in blueprints
        .iter()
        .filter(|b| b.exam == exam && b.subject == subject)
    {
        let (slug, expected) = match (&bp.topic, bp.expected) {
            (Some(slug), Some(e)) if bp.level == "topic" => (slug.clone(), e),
            _ => {
                unmeasured += 1;
                continue;
            }
        };
        let pool = pools.pools.get(&slug);
        let (held, verified, deduped, name) = match pool {
            Some(p) => {
                let verified: Vec<&Question> = p.rows.iter().filter(|q| q.verified).collect();
                let mut seen = HashSet::new();
                for q in &verified {
                    seen.insert(q.content_fingerprint());
                }
                (p.rows.len(), verified.len(), seen.len(), p.name.clone())
            }
            None => (0, 0, 0, String::new()),
        };
        let need = expected.ceil() as u32;
        topics.push(TopicReadiness {
            topic: slug,
            name,
            expected,
            need,
            held,
            verified,
            deduped,
            ready: deduped as u32 >= need,
        });
    }
    topics.sort_by(|a, b| a.topic.cmp(&b.topic));
    let ready = topics.iter().filter(|t| t.ready).count();
    let complete = !topics.is_empty() && ready == topics.len();
    SubjectReadiness {
        exam: exam.to_string(),
        subject: subject.to_string(),
        topics,
        unmeasured,
        unattributed: pools.unattributed_verified,
        ready,
        complete,
    }
}

/// One topic's servable, in-scope, attributed rows.
pub struct TopicPool {
    pub name: String,
    pub rows: Vec<Question>,
}

/// The attributed bank for one exam subject: every pool keyed by topic
/// slug, plus the verified rows no topic can claim.
pub struct PoolSet {
    pub pools: HashMap<String, TopicPool>,
    pub unattributed_verified: usize,
}

/// Attribute servable in-scope rows to topics through subtopic tags, once.
/// Both readiness and assembly build from this — one bucketing, two uses.
pub fn topic_pools(store: &dyn Store, exam: &str, subject: &str, country: Option<&str>) -> PoolSet {
    // Subtopic → topic from the syllabus tree (scope already applied).
    let mut subtopic_topic: HashMap<String, String> = HashMap::new();
    let mut names: HashMap<String, String> = HashMap::new();
    if let Some(tree) = store.syllabus(exam, subject, country) {
        for t in &tree.topics {
            names.insert(t.slug.clone(), t.name.clone());
            for st in &t.subtopics {
                subtopic_topic.insert(st.slug.clone(), t.slug.clone());
            }
        }
    }
    // One full page holds the whole subject many times over (largest
    // today: <200 servable rows; page cap is MAX_PER_PAGE).
    let full = store.questions_page(
        QuestionFilter {
            exam: Some(exam),
            subject: Some(subject),
            verified: None,
            country,
            ..Default::default()
        },
        1,
        crate::bank::MAX_PER_PAGE,
    );
    let mut pools: HashMap<String, TopicPool> = HashMap::new();
    // Every tree topic gets a pool, even empty — readiness names all
    // measured topics, not just ones holding rows.
    for (slug, name) in &names {
        pools.insert(
            slug.clone(),
            TopicPool {
                name: name.clone(),
                rows: Vec::new(),
            },
        );
    }
    let mut unattributed_verified = 0usize;
    for q in full.questions {
        match q.subtopic_id.as_deref().and_then(|s| subtopic_topic.get(s)) {
            Some(t) => pools
                .entry(t.clone())
                .or_insert_with(|| TopicPool {
                    name: names.get(t).cloned().unwrap_or_default(),
                    rows: Vec::new(),
                })
                .rows
                .push(q),
            None => {
                if q.verified {
                    unattributed_verified += 1;
                }
            }
        }
    }
    PoolSet {
        pools,
        unattributed_verified,
    }
}
