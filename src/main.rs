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
            let mut keys = KeyStore::open_json(&config.keys_file)?;
            admin(&config, &mut keys, action)
        }
        Command::Import {
            inbox,
            data,
            dry_run,
        } => {
            let data_dir = data.unwrap_or_else(|| PathBuf::from(&config.data_dir));
            utmelab_api::import::run(&inbox, &data_dir, dry_run)
                .map_err(|e| ApiError::config(e.to_string()))?;
            Ok(())
        }
        Command::Openapi { out } => write_openapi(out),
    }
}

async fn serve(config: &Config) -> Result<(), ApiError> {
    // A bad bank must not become a running server (D23). This is a startup
    // failure, not an HTTP one — its message lists every problem found and is
    // printed to stderr, never served.
    let bank = JsonStore::load(config.data_dir()).map_err(|e| ApiError::config(e.to_string()))?;
    let keys = KeyStore::open_json(&config.keys_file)?;

    tracing::info!(
        bind = %config.bind,
        data = %config.data_dir().display(),
        keys_file = %keys.path().display(),
        keys = keys.count(),
        subjects = bank.subject_count(),
        questions = bank.question_count(),
        default_rate_limit = config.default_rate_limit,
        "utmelab-api listening"
    );

    let reports_path = config.reports_file.clone();
    let state = AppState {
        keys,
        bank: Arc::new(bank),
        limiter: Arc::new(Mutex::new(RateLimiter::new())),
        reports: Arc::new(Mutex::new(
            ReportStore::open(&reports_path)
                .map_err(|e| ApiError::config(format!("reports store: {e}")))?,
        )),
    };
    let listener = tokio::net::TcpListener::bind(&config.bind)
        .await
        .map_err(|e| ApiError::config(format!("bind {}: {e}", config.bind)))?;

    axum::serve(listener, utmelab_api::router(state))
        .with_graceful_shutdown(shutdown_signal())
        .await
        .map_err(|e| ApiError::internal(format!("server: {e}")))
}

fn admin(config: &Config, keys: &mut KeyStore, action: KeyAction) -> Result<(), ApiError> {
    match action {
        KeyAction::Create { label, rate_limit } => {
            let limit = rate_limit.unwrap_or(config.default_rate_limit);
            let (record, plaintext) = keys.create(&label, limit)?;

            // The only moment the plaintext exists outside the issuer's hands.
            println!("\n  API KEY CREATED — copy it now, it is never shown again\n");
            println!("    {plaintext}\n");
            println!("    id          {}", record.id);
            println!("    label       {}", record.label);
            println!("    rate limit  {} req/min", record.rate_limit);
        }
        KeyAction::Revoke { id } => {
            if keys.revoke(&id)? {
                println!("revoked {id}");
            } else {
                println!("no live key with id {id}");
            }
        }
    }
    Ok(())
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
    let _ = tokio::signal::ctrl_c().await;
    tracing::info!("shutting down");
}
