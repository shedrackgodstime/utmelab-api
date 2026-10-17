//! Pure business logic. No axum, no database client: total functions over
//! plain data, unit-testable with no runtime.

pub mod accounts;
pub mod catalog;
pub mod hex;
pub mod models;
pub mod papers;
pub mod reports;
pub mod validate;
