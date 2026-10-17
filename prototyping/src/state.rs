use std::sync::Arc;

use tokio::sync::Semaphore;

pub type RemoteDb = Arc<libsql::Database>;
pub type SyncDb = Arc<turso::sync::Database>;
pub type DbGate = Arc<Semaphore>;

#[derive(Clone)]
pub struct AppState {
    pub name: Arc<str>,
    pub db_remote: Option<RemoteDb>,
    pub db_sync: Option<SyncDb>,
    pub db_gate: DbGate,
}

#[derive(Clone)]
pub struct NameOnly {
    pub name: Arc<str>,
}

impl axum::extract::FromRef<AppState> for NameOnly {
    fn from_ref(state: &AppState) -> Self {
        Self {
            name: Arc::clone(&state.name),
        }
    }
}

#[derive(Clone)]
pub struct DbOnly {
    pub db_remote: Option<RemoteDb>,
    pub db_sync: Option<SyncDb>,
    pub db_gate: DbGate,
}

impl axum::extract::FromRef<AppState> for DbOnly {
    fn from_ref(state: &AppState) -> Self {
        Self {
            db_remote: state.db_remote.clone(),
            db_sync: state.db_sync.clone(),
            db_gate: Arc::clone(&state.db_gate),
        }
    }
}
