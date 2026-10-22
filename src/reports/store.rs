//! Question reports — the only write path on a read-only API.
//!
//! A consumer's user flags a broken question; we get an aggregated review
//! queue. Five constraints make this safe, and all five are load-bearing:
//!
//! 1. **Structured reasons, not a comment box.** An enum, aggregatable, no parsing.
//! 2. **No PII, ever.** No user id, no email, no name. Nothing to moderate
//!    beyond an optional 500-char detail.
//! 3. **Tight separate cap.** Reporting is rare (maybe 1 in 500 questions), so
//!    10 per key per day is generous for legit use and useless for spam.
//! 4. **Dedupe by (key, question, reason).** A double-submit is one report.
//! 5. **Queue, not action.** Reports never touch the bank. Fifty flags gets
//!    human eyes; one flag gets ignored. The output is a work list for us.
//!
//! Operational data, not bank content — same seam discipline as keys (D24/D28):
//! a gitignored JSON file today, Turso later, behind a shape that does not move.

use std::collections::HashSet;
use std::path::{Path, PathBuf};

use rand::Rng;
use serde::{Deserialize, Serialize};

use crate::error::ApiError;

/// Why this question is being flagged. Closed set on purpose — free text cannot
/// be aggregated, and aggregation is the entire point.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReportReason {
    WrongAnswer,
    UnclearStem,
    BrokenOption,
    WrongExplanation,
    Other,
}

impl ReportReason {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "wrong_answer" => Some(Self::WrongAnswer),
            "unclear_stem" => Some(Self::UnclearStem),
            "broken_option" => Some(Self::BrokenOption),
            "wrong_explanation" => Some(Self::WrongExplanation),
            "other" => Some(Self::Other),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::WrongAnswer => "wrong_answer",
            Self::UnclearStem => "unclear_stem",
            Self::BrokenOption => "broken_option",
            Self::WrongExplanation => "wrong_explanation",
            Self::Other => "other",
        }
    }
}

/// Maximum free-text detail. Long enough for "option C says X but the text
/// says Y", short enough to be useless for spam.
pub const MAX_DETAIL_LEN: usize = 500;

/// Per-key daily allowance. Generous for humans, useless for floods.
pub const DEFAULT_REPORTS_PER_DAY: u32 = 10;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct QuestionReport {
    pub id: String,
    pub question_id: String,
    /// Which key reported. Stored for dedupe and abuse review; never exposed
    /// in API responses (the receipt carries only the report id).
    pub key_id: String,
    pub reason: ReportReason,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
    pub created_at: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct ReportFile {
    #[serde(default)]
    reports: Vec<QuestionReport>,
}

/// Dedupe key: same key, same question, same reason — once.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct ReportKey {
    key_id: String,
    question_id: String,
    reason: ReportReason,
}

#[derive(Clone, Debug)]
pub struct ReportStore {
    path: PathBuf,
    file: ReportFile,
    /// Index for O(1) dedupe checks.
    seen: HashSet<ReportKey>,
}

impl ReportStore {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, ApiError> {
        let path = path.as_ref().to_path_buf();

        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent)
                .map_err(|e| ApiError::internal(format!("create {}: {e}", parent.display())))?;
        }

        let file = match std::fs::read(&path) {
            Ok(bytes) => serde_json::from_slice(&bytes)
                .map_err(|e| ApiError::internal(format!("{} is corrupt: {e}", path.display())))?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => ReportFile::default(),
            Err(e) => return Err(ApiError::internal(format!("read {}: {e}", path.display()))),
        };

        let seen = file
            .reports
            .iter()
            .map(|r| ReportKey {
                key_id: r.key_id.clone(),
                question_id: r.question_id.clone(),
                reason: r.reason,
            })
            .collect();

        Ok(Self { path, file, seen })
    }

    pub fn count(&self) -> usize {
        self.file.reports.len()
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Reports by one key in the last 24h, for the daily cap.
    ///
    /// Timestamps are unix seconds stored as strings (same convention as keys).
    /// Unparseable rows count — failing closed on corrupt data.
    pub fn recent_count(&self, key_id: &str) -> usize {
        let now = now_secs();
        self.file
            .reports
            .iter()
            .filter(|r| r.key_id == key_id)
            .filter(|r| {
                r.created_at
                    .parse::<u64>()
                    .map(|t| now.saturating_sub(t) < 86_400)
                    .unwrap_or(true)
            })
            .count()
    }

    /// File under (key, question, reason). Returns the existing report when
    /// this exact flag was already filed — POST is idempotent here by design.
    pub fn file(
        &mut self,
        key_id: &str,
        question_id: &str,
        reason: ReportReason,
        detail: Option<String>,
    ) -> Result<(QuestionReport, bool), ApiError> {
        let key = ReportKey {
            key_id: key_id.to_owned(),
            question_id: question_id.to_owned(),
            reason,
        };

        if let Some(existing) = self
            .file
            .reports
            .iter()
            .find(|r| {
                r.key_id == key.key_id && r.question_id == key.question_id && r.reason == key.reason
            })
            .cloned()
        {
            return Ok((existing, true));
        }

        if let Some(d) = &detail {
            if d.chars().count() > MAX_DETAIL_LEN {
                return Err(ApiError::bad_request(
                    "detail_too_long",
                    format!("Detail is limited to {MAX_DETAIL_LEN} characters."),
                ));
            }
        }

        let record = QuestionReport {
            id: new_id(),
            question_id: question_id.to_owned(),
            key_id: key_id.to_owned(),
            reason,
            detail: detail.filter(|d| !d.trim().is_empty()),
            created_at: now_secs().to_string(),
        };

        self.file.reports.push(record.clone());
        self.seen.insert(key);
        self.persist()?;
        Ok((record, false))
    }

    fn persist(&self) -> Result<(), ApiError> {
        let bytes = serde_json::to_vec_pretty(&self.file)
            .map_err(|e| ApiError::internal(format!("serialise reports: {e}")))?;
        let tmp = self.path.with_extension("json.tmp");

        std::fs::write(&tmp, &bytes)
            .map_err(|e| ApiError::internal(format!("write {}: {e}", tmp.display())))?;
        restrict_permissions(&tmp)?;
        std::fs::rename(&tmp, &self.path)
            .map_err(|e| ApiError::internal(format!("rename into {}: {e}", self.path.display())))?;
        Ok(())
    }
}

fn restrict_permissions(path: &Path) -> Result<(), ApiError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let perms = std::fs::Permissions::from_mode(0o600);
        std::fs::set_permissions(path, perms)
            .map_err(|e| ApiError::internal(format!("chmod {}: {e}", path.display())))?;
    }
    #[cfg(not(unix))]
    let _ = path;
    Ok(())
}

fn new_id() -> String {
    let mut bytes = [0u8; 16];
    rand::rng().fill(&mut bytes);
    format!(
        "rep_{}",
        bytes.iter().map(|b| format!("{b:02x}")).collect::<String>()
    )
}

fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn store(name: &str) -> ReportStore {
        let path = std::env::temp_dir().join(format!(
            "utmelab-reports-{name}-{}.json",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);
        ReportStore::open(path).expect("temp store")
    }

    #[test]
    fn filing_returns_an_id_and_persists() {
        let mut s = store("file");
        let (r, duplicate) = s
            .file(
                "k1",
                "q1",
                ReportReason::WrongAnswer,
                Some("option C contradicts the text".into()),
            )
            .expect("file");
        assert!(!duplicate);
        assert!(r.id.starts_with("rep_"));
        assert_eq!(s.count(), 1);

        let reopened = ReportStore::open(s.path()).expect("reopen");
        assert_eq!(reopened.count(), 1);
    }

    #[test]
    fn same_key_question_reason_files_once() {
        let mut s = store("dedupe");
        let (first, dup1) = s
            .file("k1", "q1", ReportReason::WrongAnswer, None)
            .expect("file");
        let (second, dup2) = s
            .file("k1", "q1", ReportReason::WrongAnswer, None)
            .expect("file");
        assert!(!dup1);
        assert!(dup2);
        assert_eq!(first.id, second.id);
        assert_eq!(s.count(), 1);

        // A different reason is a different report.
        let (_, dup3) = s
            .file("k1", "q1", ReportReason::UnclearStem, None)
            .expect("file");
        assert!(!dup3);
        assert_eq!(s.count(), 2);
    }

    #[test]
    fn oversized_detail_is_rejected() {
        let mut s = store("detail");
        let long = "x".repeat(MAX_DETAIL_LEN + 1);
        let err = s
            .file("k1", "q1", ReportReason::Other, Some(long))
            .expect_err("must reject");
        assert!(matches!(err, ApiError::BadRequest { .. }));
    }

    #[test]
    fn recent_count_drives_the_daily_cap() {
        let mut s = store("cap");
        for i in 0..3 {
            s.file("k1", &format!("q{i}"), ReportReason::WrongAnswer, None)
                .expect("file");
        }
        assert_eq!(s.recent_count("k1"), 3);
        assert_eq!(s.recent_count("k2"), 0);
    }

    #[test]
    fn reasons_round_trip() {
        for (s, r) in [
            ("wrong_answer", ReportReason::WrongAnswer),
            ("unclear_stem", ReportReason::UnclearStem),
            ("broken_option", ReportReason::BrokenOption),
            ("wrong_explanation", ReportReason::WrongExplanation),
            ("other", ReportReason::Other),
        ] {
            assert_eq!(ReportReason::parse(s), Some(r));
            assert_eq!(r.as_str(), s);
        }
        assert_eq!(ReportReason::parse("bogus"), None);
    }
}
