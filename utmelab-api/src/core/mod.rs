//! Pure business logic. No axum, no database client: total functions over
//! plain data, unit-testable with no runtime.

pub mod accounts;
pub mod catalog;
pub mod models;
pub mod reports;
pub mod validate;
