//! utmelab-api — the question bank as a public, metered API.
//!
//! Two entrypoints:
//!   * `utmelab-api serve`  — run the HTTP server
//!   * `utmelab-api key …`  — issue and revoke API keys from the CLI
//!
//! Keys are administered from the CLI rather than over HTTP: an admin endpoint
//! would need its own authentication surface, and there is no reason to expose
//! one while a shell is already on the box.
//!
//! All the real work lives in the library crate.

use clap::{Parser, Subcommand};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use utmelab_api::{
    ApiError, AppState, Config, JsonStore, KeyStore, RateLimiter, ReportStore, Store,
};

#[derive(Parser)]
#[command(name = "utmelab-api", version, about = "UTME Lab question bank API")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Run the HTTP server.
    Serve,
    /// Administer API keys.
    Key {
        #[command(subcommand)]
        action: KeyAction,
    },
    /// Move harvested questions from the inbox into the bank (D51).
    Import {
        /// Directory holding harvested subject files.
        #[arg(long, default_value = "data/inbox")]
        inbox: PathBuf,
        /// Directory holding the catalog and questions.json.
        #[arg(long)]
        data: Option<PathBuf>,
        /// Report what would happen; write nothing.
        #[arg(long)]
        dry_run: bool,
        /// Subject map. Defaults to `config/harvest.json`.
        #[arg(long)]
        harvest_config: Option<PathBuf>,
    },
    /// Write the OpenAPI document to a file (or stdout) for the docs build.
    ///
    /// The web tier reads a *file*, not the live URL, so the docs build is
    /// deterministic and does not need the API running (D32).
    Openapi {
        /// Output path. Defaults to stdout.
        #[arg(long, short)]
        out: Option<PathBuf>,
    },
}

#[derive(Subcommand)]
enum KeyAction {
    /// Issue a key. The plaintext is printed once and never stored.
    Create {
        /// Human-readable label, e.g. "myself-laptop".
        #[arg(long)]
        label: String,
        /// Requests per minute. Defaults to the server's configured default.
        #[arg(long)]
        rate_limit: Option<u32>,
    },
    /// Revoke a key by id.
    Revoke {
        #[arg(long)]
        id: String,
    },
    /// List keys. Safe columns only — never secrets.
    List,
    /// Rotate a key: successor issued, old key expires after a grace period.
    Rotate {
        /// Id of the key being replaced.
        #[arg(long)]
        id: String,
        /// Hours the old key stays valid. Defaults to 24.
        #[arg(long, default_value_t = 24)]
        grace_hours: u64,
    },
    /// Migrate the JSON key file into Turso (one-time, D53 Phase 1).
    Import {
        /// Source file. Defaults to the configured `keys_file`.
        #[arg(long)]
        from: Option<PathBuf>,
        /// Report what would happen; write nothing.
        #[arg(long)]
        dry_run: bool,
    },
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "utmelab_api=info".into()),
        )
        .init();

    if let Err(e) = run().await {
        // Printed to stderr; never returned to a client.
        eprintln!("fatal: {e}");
        std::process::exit(1);
    }
}

async fn run() -> Result<(), ApiError> {
    let cli = Cli::parse();
    let config = Config::from_env()?;

    match cli.command {
        Command::Serve => serve(&config).await,
        Command::Key { action } => {
            let backend = open_backend(&config).await?;
            admin(&config, &backend, action).await
        }
        Command::Import {
            inbox,
            data,
            dry_run,
            harvest_config,
        } => {
            let data_dir = data.unwrap_or_else(|| PathBuf::from(&config.data_dir));
            utmelab_api::import::run(&inbox, &data_dir, dry_run, harvest_config.as_deref())
                .map_err(|e| ApiError::config(e.to_string()))?;
            Ok(())
        }
        Command::Openapi { out } => write_openapi(out),
    }
}

/// Which store this process talks to. Turso is the live store (D53); the file
/// backend is a **dev-only escape hatch**, never a silent default.
///
/// Why opt-in and not a fallback: if Turso env is missing, silently dropping to
/// a local file forks the keys — `key create` would write a key the Turso-backed
/// server can never see, and every auth would 401 with nothing explaining why.
/// So a missing Turso config is a hard error unless the operator explicitly
/// asks for the file backend (`UTMELAB_API_KEY_BACKEND=file`, or by setting
/// `UTMELAB_API_KEYS_FILE`). Same selection for serve and CLI, so a created key
/// always lands in the store the server reads.
async fn open_backend(config: &Config) -> Result<utmelab_api::KeyBackend, ApiError> {
    match (&config.turso_url, &config.turso_token) {
        (Some(url), Some(token)) => {
            utmelab_api::KeyBackend::open_remote(url, token, config.key_cache_ttl_secs).await
        }
        _ => {
            let wants_file = std::env::var("UTMELAB_API_KEY_BACKEND").as_deref() == Ok("file")
                || std::env::var("UTMELAB_API_KEYS_FILE").is_ok();
            if wants_file {
                Ok(utmelab_api::KeyBackend::file(KeyStore::open_json(
                    &config.keys_file,
                )?))
            } else {
                Err(ApiError::config(
                    "no key backend: set TURSO_DB_URL + TURSO_DB_TOKEN (keys live in Turso), \
                     or UTMELAB_API_KEY_BACKEND=file for local dev",
                ))
            }
        }
    }
}

async fn serve(config: &Config) -> Result<(), ApiError> {
    // A bad bank must not become a running server (D23). This is a startup
    // failure, not an HTTP one — its message lists every problem found and is
    // printed to stderr, never served.
    let bank = JsonStore::load(config.data_dir()).map_err(|e| ApiError::config(e.to_string()))?;
    let keys = open_backend(config).await?;
    let keys_desc = keys.describe();
    let key_count = keys.count().await.unwrap_or(0);

    tracing::info!(
        bind = %config.bind,
        data = %config.data_dir().display(),
        key_backend = %keys_desc,
        keys = key_count,
        subjects = bank.subject_count(),
        questions = bank.question_count(),
        default_rate_limit = config.default_rate_limit,
        "utmelab-api listening"
    );

    let reports_path = config.reports_file.clone();
    let state = AppState {
        keys: Arc::new(keys),
        bank: Arc::new(bank),
        limiter: Arc::new(Mutex::new(RateLimiter::new())),
        reports: Arc::new(tokio::sync::Mutex::new(
            ReportStore::open(&reports_path)
                .map_err(|e| ApiError::config(format!("reports store: {e}")))?,
        )),
    };

    // R3 follow-through: evict rate-limit buckets for keys that are no longer
    // live, so a long-running process does not grow one entry per key ever
    // issued. Every 15 minutes, against a fresh live-key list.
    {
        let retention = state.clone();
        tokio::spawn(async move {
            let mut tick = tokio::time::interval(std::time::Duration::from_secs(900));
            tick.tick().await; // first tick fires immediately; skip it
            loop {
                tick.tick().await;
                let live: Vec<String> = match retention.keys.list().await {
                    Ok(keys) => keys
                        .into_iter()
                        .filter(|k| k.is_live())
                        .map(|k| k.id)
                        .collect(),
                    Err(e) => {
                        tracing::warn!("rate-limit retention skipped: {e}");
                        continue;
                    }
                };
                if let Ok(mut limiter) = retention.limiter.lock() {
                    limiter.retain(|id| live.iter().any(|live_id| live_id == id));
                }
            }
        });
    }
    let listener = tokio::net::TcpListener::bind(&config.bind)
        .await
        .map_err(|e| ApiError::config(format!("bind {}: {e}", config.bind)))?;

    axum::serve(listener, utmelab_api::router(state))
        .with_graceful_shutdown(shutdown_signal())
        .await
        .map_err(|e| ApiError::internal(format!("server: {e}")))
}

async fn admin(
    config: &Config,
    keys: &utmelab_api::KeyBackend,
    action: KeyAction,
) -> Result<(), ApiError> {
    match action {
        KeyAction::Create { label, rate_limit } => {
            let limit = rate_limit.unwrap_or(config.default_rate_limit);
            let (record, plaintext) = keys.create(&label, limit).await?;

            // The only moment the plaintext exists outside the issuer's hands.
            println!("\n  API KEY CREATED — copy it now, it is never shown again\n");
            println!("    {plaintext}\n");
            println!("    id          {}", record.id);
            println!("    label       {}", record.label);
            println!("    rate limit  {} req/min", record.rate_limit);
        }
        KeyAction::Revoke { id } => {
            if keys.revoke(&id).await? {
                println!("revoked {id}");
            } else {
                println!("no live key with id {id}");
            }
        }
        KeyAction::List => {
            let rows = keys.list().await?;
            if rows.is_empty() {
                println!("no keys");
            } else {
                // Safe columns only: id, prefix, label, plan, rate, status.
                // No hashes, no plaintext — ever.
                println!(
                    "{:<36} {:<11} {:<24} {:<6} {:>8}  STATUS",
                    "ID", "PREFIX", "LABEL", "PLAN", "RATE/MIN"
                );
                for k in &rows {
                    println!(
                        "{:<36} {:<11} {:<24} {:<6} {:>8}  {}",
                        k.id,
                        k.key_prefix.as_deref().unwrap_or("-"),
                        truncate(&k.label, 24),
                        k.plan,
                        k.rate_limit,
                        k.status().as_str(),
                    );
                }
            }
        }
        KeyAction::Rotate { id, grace_hours } => match keys.rotate(&id, grace_hours).await? {
            Some((record, plaintext)) => {
                println!("\n  API KEY ROTATED — copy the new key now, it is never shown again\n");
                println!("    {plaintext}\n");
                println!("    new id      {}", record.id);
                println!("    label       {}", record.label);
                println!("    old id      {id} (expires in {grace_hours}h)");
            }
            None => println!("no live key with id {id}"),
        },
        KeyAction::Import { from, dry_run } => {
            let source = from.unwrap_or_else(|| config.keys_file.clone());
            let report = keys.import_file(&source, dry_run).await?;

            println!(
                "source {src}: {total} rows",
                src = source.display(),
                total = report.total
            );
            if dry_run {
                println!("  would insert {}", report.inserted);
            } else {
                println!("  inserted {}", report.inserted);
            }
            println!("  skipped (already present): {}", report.skipped);
            for s in report.skips.iter().take(20) {
                println!("      {s}");
            }
            println!("  refused (malformed): {}", report.refused);
            for r in report.refusals.iter().take(20) {
                println!("      {r}");
            }
            if dry_run {
                println!("\n(dry run — nothing written)");
            }
        }
    }
    Ok(())
}

fn truncate(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        return text.to_owned();
    }
    let mut out: String = text.chars().take(max.saturating_sub(1)).collect();
    out.push('…');
    out
}

fn write_openapi(out: Option<PathBuf>) -> Result<(), ApiError> {
    let doc = serde_json::to_vec_pretty(&utmelab_api::openapi_document())
        .map_err(|e| ApiError::internal(format!("serialise spec: {e}")))?;

    match out {
        Some(path) => {
            if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
                std::fs::create_dir_all(parent)
                    .map_err(|e| ApiError::internal(format!("create {}: {e}", parent.display())))?;
            }
            std::fs::write(&path, doc)
                .map_err(|e| ApiError::internal(format!("write {}: {e}", path.display())))?;
            println!("wrote {}", path.display());
        }
        None => println!("{}", String::from_utf8_lossy(&doc)),
    }
    Ok(())
}

async fn shutdown_signal() {
    // Caddy and systemd stop us with SIGTERM, not ctrl-C — a service that only
    // listens for ctrl-C gets SIGKILL'd mid-deploy and drops in-flight writes.
    let term = async {
        let _ = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("SIGTERM handler")
            .recv()
            .await;
    };
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {}
        _ = term => {}
    }
    tracing::info!("shutting down");
}
