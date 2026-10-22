//! The shapes shared across the crate, split by role so one file cannot
//! become a dumping ground:
//!
//! - `domain`: the bank as stored, the Rust half of the `READ_SHAPES`
//!   contract.
//! - `wire`: what the API answers with.
//! - `admin`: the service and the caller's own key.
//!
//! All three are re-exported here, so `core::models::Question` and
//! `core::models::Page` keep resolving. The split is about where a type is
//! defined, not where it is named.

mod admin;
mod domain;
mod wire;

pub use admin::*;
pub use domain::*;
pub use wire::*;
