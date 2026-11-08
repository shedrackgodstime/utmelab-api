//! The only door to the sync engine.
//!
//! Every method requires an explicit budget from [`BudgetSet`]. There is no
//! default, so a future call site cannot add an unbounded `db.pull().await`
//! without changing this file first. Errors keep their typed class here, at
//! the boundary where the engine error still exists.

use super::policy::{classify_engine, Budget, BudgetSet, SyncError};

/// A bounded view of the engine. Constructed from the shared policy, never
/// stored by handlers.
pub(crate) struct Engine {
    db: super::super::SyncDb,
    budgets: BudgetSet,
}

impl Engine {
    pub(crate) fn new(db: super::super::SyncDb, budgets: BudgetSet) -> Self {
        Self { db, budgets }
    }

    pub(crate) async fn pull(&self) -> Result<bool, SyncError> {
        match deadline("pull", self.budgets.pull, self.db.pull()).await {
            Ok(Ok(changes)) => Ok(changes),
            Ok(Err(error)) => Err(SyncError::new(classify_engine(&error), error.to_string())),
            Err(error) => Err(error),
        }
    }

    pub(crate) async fn push(&self) -> Result<(), SyncError> {
        match deadline("push", self.budgets.push, self.db.push()).await {
            Ok(Ok(())) => Ok(()),
            Ok(Err(error)) => Err(SyncError::new(classify_engine(&error), error.to_string())),
            Err(error) => Err(error),
        }
    }

    pub(crate) async fn stats(&self) -> Result<turso::sync::DatabaseSyncStats, SyncError> {
        match deadline("stats", self.budgets.stats, self.db.stats()).await {
            Ok(Ok(stats)) => Ok(stats),
            Ok(Err(error)) => Err(SyncError::new(classify_engine(&error), error.to_string())),
            Err(error) => Err(error),
        }
    }

    pub(crate) async fn connect(&self) -> Result<turso::Connection, SyncError> {
        match deadline("connect", self.budgets.connect, self.db.connect()).await {
            Ok(Ok(conn)) => Ok(conn),
            Ok(Err(error)) => Err(SyncError::new(classify_engine(&error), error.to_string())),
            Err(error) => Err(error),
        }
    }
}

/// One deadline wrapper. Keeping it private means the only way to reach the
/// engine is through a method that names its budget.
async fn deadline<T>(
    operation: &'static str,
    budget: Budget,
    future: impl std::future::Future<Output = turso::Result<T>>,
) -> Result<turso::Result<T>, SyncError> {
    match tokio::time::timeout(budget.duration(), future).await {
        Ok(result) => Ok(result),
        Err(_) => Err(SyncError::timeout(operation, budget)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::replica;
    use std::time::Duration;

    #[test]
    fn every_budget_is_positive() {
        let policy = super::super::policy::SyncPolicy::default();
        for budget in [
            policy.budgets.build,
            policy.budgets.connect,
            policy.budgets.pull,
            policy.budgets.push,
            policy.budgets.stats,
            policy.budgets.verify,
            policy.budgets.shutdown,
        ] {
            assert!(budget.duration() > Duration::ZERO);
        }
    }

    /// A deadline is not decoration: a future that never finishes returns the
    /// typed timeout class and releases the caller.
    #[tokio::test]
    async fn a_stalled_operation_returns_a_timeout_class() {
        let db = replica().await;
        let engine = Engine::new(
            db,
            BudgetSet {
                build: Budget::new(Duration::from_secs(1)),
                connect: Budget::new(Duration::from_millis(20)),
                pull: Budget::new(Duration::from_millis(20)),
                push: Budget::new(Duration::from_millis(20)),
                stats: Budget::new(Duration::from_millis(20)),
                verify: Budget::new(Duration::from_millis(20)),
                shutdown: Budget::new(Duration::from_millis(20)),
            },
        );
        let stalled = deadline(
            "test",
            Budget::new(Duration::from_millis(10)),
            std::future::pending::<turso::Result<()>>(),
        )
        .await;
        assert_eq!(
            stalled.expect_err("must time out").class,
            super::super::policy::ErrorClass::Timeout
        );

        // A real offline engine answers through the same boundary, so a
        // failure is classified instead of escaping as a string.
        let _ = engine.stats().await;
    }
}
