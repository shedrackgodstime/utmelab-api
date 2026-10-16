use std::{net::SocketAddr, sync::Arc};

use tracing_subscriber::{fmt, EnvFilter};
use utmelab_api::{
    config::Config,
    routes,
    state::{AppState, Metrics, SyncCell},
    store,
};

fn main() {
    let _ = dotenvy::dotenv();
    for dead in ["ADMIN_USERNAME", "ADMIN_PASSWORD"] {
        if std::env::var(dead).is_ok() {
            eprintln!(
                "warning: {dead} in environment is ignored; secrets never steer the server (use `seed-admin`, never store them in .env)"
            );
        }
    }
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).is_some_and(|a| a == "seed-admin") {
        let username = args.get(2).cloned().unwrap_or_default();
        let role = args.get(3).cloned().unwrap_or_else(|| "admin".to_string());
        std::process::exit(seed_admin_cmd(username, role));
    }
    let cfg = Config::from_env();
    if let Err(e) = cfg.validate() {
        eprintln!("{e}");
        std::process::exit(1);
    }
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(cfg.worker_threads)
        .max_blocking_threads(cfg.max_blocking_threads)
        .enable_all()
        .build()
        .expect("build runtime")
        .block_on(run(cfg));
}

fn seed_admin_cmd(username: String, role: String) -> i32 {
    if username.is_empty() {
        eprintln!("usage: seed-admin <username> [admin|customer]");
        return 2;
    }
    let cfg = Config::from_env();
    if !cfg.has_db() {
        eprintln!("no TURSO_DB_URL/TOKEN; nothing to seed into");
        return 1;
    }
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("build command runtime");
    rt.block_on(async move {
        let Some(db) = store::sync::ready_db(&cfg).await else {
            eprintln!("could not open replica (is the server running?) or reach cloud");
            return 1;
        };
        let st = utmelab_api::state::DbState::detached(db);
        let bytes: [u8; 18] = rand::random();
        let password: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
        match store::accounts::seed_admin(&st, &username, &password, &role).await {
            Ok(()) => {
                println!("seeded {role} {username}");
                println!("password: {password}");
                println!("store it now; it is never shown again");
                0
            }
            Err(e) => {
                eprintln!("seed failed: {e}");
                1
            }
        }
    })
}

async fn run(cfg: Config) {
    fmt().with_env_filter(EnvFilter::from_default_env()).init();
    tracing::info!(
        workers = cfg.worker_threads,
        blocking = cfg.max_blocking_threads,
        limit = cfg.concurrency_limit,
        db_max = cfg.db_max_concurrent,
        port = cfg.port,
        has_db = cfg.has_db(),
        "starting"
    );

    let metrics = Arc::new(Metrics::default());
    let db: SyncCell = Arc::new(tokio::sync::RwLock::new(None));
    let db_gate = Arc::new(tokio::sync::Semaphore::new(cfg.db_max_concurrent));
    let write_mutex = Arc::new(tokio::sync::Mutex::new(()));
    let contract_ok = Arc::new(std::sync::atomic::AtomicBool::new(true));
    let limiter = Arc::new(utmelab_api::auth::rate_limit::RateLimiter::new());

    let state = AppState {
        name: Arc::from("utmelab-api"),
        db,
        db_gate,
        metrics,
        cookie_secure: cfg.cookie_secure,
        write_mutex,
        contract_ok,
        limiter,
    };
    store::sync::spawn_sync_task(&state, cfg.clone());
    let app = routes::router(state, &cfg);

    let addr = SocketAddr::from(([127, 0, 0, 1], cfg.port));
    tracing::info!("listening on {addr}");

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("bind listener");

    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown_signal())
    .await
    .expect("serve");
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
    tracing::info!("shutdown signal received");
}
