mod config;
mod db_init;
mod routes;
mod state;

use std::{net::SocketAddr, sync::Arc, time::Duration};

use config::Config;
use routes::build_router;
use state::AppState;
use tracing_subscriber::{fmt, EnvFilter};

fn main() {
    let _ = dotenvy::dotenv();
    let cfg = Config::from_env();
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(cfg.worker_threads)
        .max_blocking_threads(cfg.max_blocking_threads)
        .enable_all()
        .build()
        .expect("build runtime")
        .block_on(run(cfg));
}

async fn run(cfg: Config) {
    fmt().with_env_filter(EnvFilter::from_default_env()).init();
    tracing::info!(
        workers = cfg.worker_threads,
        blocking = cfg.max_blocking_threads,
        limit = cfg.concurrency_limit,
        port = cfg.port,
        db_max = cfg.db_max_concurrent,
        has_db = cfg.has_db(),
        "starting"
    );

    let (db_remote, db_sync) = db_init::init_dbs(&cfg).await;

    if let Some(sync_db) = db_sync.clone() {
        let secs = cfg.sync_secs;
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(Duration::from_secs(secs)).await;
                match sync_db.pull().await {
                    Ok(true) => tracing::debug!("background pull: changes applied"),
                    Ok(false) => tracing::debug!("background pull: no changes"),
                    Err(e) => tracing::warn!("background pull failed: {e}"),
                }
            }
        });
    }

    let state = AppState {
        name: Arc::from("prototype"),
        db_remote,
        db_sync,
        db_gate: Arc::new(tokio::sync::Semaphore::new(cfg.db_max_concurrent)),
    };
    let app = build_router(state, cfg.clone());

    let addr = SocketAddr::from(([127, 0, 0, 1], cfg.port));
    tracing::info!("listening on {addr}");

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("bind listener");

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .expect("serve");

    tokio::time::sleep(Duration::from_millis(100)).await;
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
    tracing::info!("shutdown signal received");
}
