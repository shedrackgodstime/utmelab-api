//! Question reports — the only write path (see `store.rs` for the why).
//!
//! Operational data, like keys: gitignored JSON today, Turso later, behind a
//! shape that does not move.

mod store;

pub use store::{DEFAULT_REPORTS_PER_DAY, QuestionReport, ReportReason, ReportStore};
