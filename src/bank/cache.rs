//! On-disk snapshot of the served bank (`var/bank_cache.json`).
//!
//! Turso is the source of truth; this file is a boot accelerator and nothing
//! more. Boot and refresh both flow through here:
//!
//! 1. Read Turso's cheap count-hash version (13 `COUNT(*)` queries).
//! 2. Read + parse the snapshot file. Version matches → hand the structs to
//!    [`JsonStore::from_parts`], which re-validates fail-closed — a corrupt
//!    cache refuses exactly like a corrupt bank, never silently.
//! 3. Anything else (missing file, parse failure, version mismatch) → caller
//!    falls through to a full fetch, then rewrites the snapshot.
//!
//! Cache failures never fail boot: every error path returns `None` and the
//! caller fetches from Turso. Nothing except boot/refresh reads this file.

use crate::bank::StoreParts;
use crate::bank::model::{
    Country, Exam, NovelDoc, Passage, Question, Requirement, Subject, Subtopic, Topic, Verification,
};
use std::path::Path;

/// The exact inputs [`JsonStore::from_parts`] needs, frozen to disk.
#[derive(serde::Serialize, serde::Deserialize)]
pub(crate) struct Snapshot {
    pub(crate) version: String,
    pub(crate) exams: Vec<Exam>,
    pub(crate) countries: Vec<Country>,
    pub(crate) subjects: Vec<Subject>,
    pub(crate) topics: Vec<Topic>,
    pub(crate) subtopics: Vec<Subtopic>,
    pub(crate) questions: Vec<Question>,
    pub(crate) requirements: Vec<Requirement>,
    pub(crate) scope: Vec<(String, Vec<String>)>,
    pub(crate) verifications: Vec<Verification>,
    pub(crate) novels: Vec<NovelDoc>,
    pub(crate) passages: Vec<Passage>,
    pub(crate) blueprints: Vec<crate::bank::readiness::Blueprint>,
}

impl Snapshot {
    fn into_parts(self) -> StoreParts {
        StoreParts {
            exams: self.exams,
            countries: self.countries,
            subjects: self.subjects,
            topics: self.topics,
            subtopics: self.subtopics,
            questions: self.questions,
            requirements: self.requirements,
            scope: self.scope,
            verifications: self.verifications,
            novels: self.novels,
            passages: self.passages,
            blueprints: self.blueprints,
            withheld_questions: Vec::new(),
            withheld_notes: 0,
            version: self.version,
        }
    }
}

/// Read a usable snapshot, or `None` (caller fetches from Turso).
/// `version` is Turso's current count-hash: only an exact match loads.
pub(crate) fn load(path: &Path, version: &str) -> Option<StoreParts> {
    let raw = std::fs::read_to_string(path).ok()?;
    let snap: Snapshot = serde_json::from_str(&raw).ok()?;
    if snap.version != version {
        return None;
    }
    Some(snap.into_parts())
}

/// Persist a fresh fetch. Failure only warns — the cache is an accelerator,
/// and a failed write must never fail boot or refresh.
pub(crate) fn save(path: &Path, snap: &Snapshot) {
    let write = || -> Result<(), String> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let body = serde_json::to_string(&snap).map_err(|e| e.to_string())?;
        std::fs::write(path, body).map_err(|e| e.to_string())
    };
    if let Err(e) = write() {
        tracing::warn!("bank cache write failed (serving from Turso fetch): {e}");
    }
}
