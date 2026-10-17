use std::sync::Arc;

use crate::config::Config;
use crate::state::{RemoteDb, SyncDb};

pub async fn init_dbs(cfg: &Config) -> (Option<RemoteDb>, Option<SyncDb>) {
    if !cfg.has_db() {
        tracing::warn!("no TURSO_DB_URL/TOKEN, /db-* will return 503");
        return (None, None);
    }
    let url = cfg.normalized_url();
    let token = cfg.turso_token.clone();

    let remote = libsql::Builder::new_remote(url.clone(), token.clone())
        .build()
        .await
        .map(Arc::new)
        .map_err(|e| tracing::warn!("remote build failed: {e}"))
        .ok();

    let sync = turso::sync::Builder::new_remote(&cfg.replica_path)
        .with_remote_url(&url)
        .with_auth_token(&token)
        .bootstrap_if_empty(true)
        .build()
        .await
        .map(Arc::new)
        .map_err(|e| tracing::warn!("sync build failed: {e}"))
        .ok();

    if let Some(db) = sync.as_ref() {
        match db.pull().await {
            Ok(true) => tracing::info!("initial pull: changes applied"),
            Ok(false) => tracing::info!("initial pull: already fresh"),
            Err(e) => tracing::warn!("initial pull failed: {e}"),
        }
    }

    (remote, sync)
}
