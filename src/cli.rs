use utmelab_api::{config::Config, store};

pub fn run(args: &[String]) -> Option<i32> {
    let command = args.first().map(String::as_str)?;
    let exit_code = match command {
        "seed-admin" => seed_admin_cmd(
            args.get(1).cloned().unwrap_or_default(),
            args.get(2).cloned().unwrap_or_else(|| "admin".to_string()),
        ),
        "import-theory" => import_theory_cmd(args.get(1).cloned().unwrap_or_default()),
        "import-lessons" => import_lessons_cmd(args.get(1).cloned().unwrap_or_default()),
        "clean-content-schema" => clean_content_schema_cmd(),
        "admin-pull" => admin_pull_cmd(args.get(1).cloned().unwrap_or_default()),
        _ => return None,
    };
    Some(exit_code)
}

fn admin_pull_cmd(base_url: String) -> i32 {
    let base_url = if base_url.is_empty() {
        std::env::var("UTMELAB_API_BASE_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:3100".to_string())
    } else {
        base_url
    };
    let api_key = match std::env::var("UTMELAB_ADMIN_API_KEY") {
        Ok(value) if !value.trim().is_empty() => value,
        _ => {
            eprintln!(
                "usage: UTMELAB_ADMIN_API_KEY='...' cargo run --release -- admin-pull [base-url]"
            );
            return 2;
        }
    };
    let url = format!("{}/mcp/admin", base_url.trim_end_matches('/'));
    let initialize = match std::process::Command::new("curl")
        .args([
            "--fail-with-body",
            "--silent",
            "--show-error",
            "--request",
            "POST",
            "--header",
            "content-type: application/json",
            "--header",
            "accept: application/json, text/event-stream",
            "--header",
        ])
        .arg(format!("x-api-key: {api_key}"))
        .args(["--data-raw", r#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"utmelab-cli","version":"0.0.1"}}}"#])
        .arg(&url)
        .output()
    {
        Ok(output) => output,
        Err(error) => {
            eprintln!("admin pull request failed: {error}");
            return 1;
        }
    };
    if !initialize.status.success() {
        eprint!(
            "admin MCP initialize failed: {}",
            String::from_utf8_lossy(&initialize.stderr)
        );
        return 1;
    }
    let output = match std::process::Command::new("curl")
        .args([
            "--fail-with-body",
            "--silent",
            "--show-error",
            "--request",
            "POST",
            "--header",
            "content-type: application/json",
            "--header",
            "accept: application/json, text/event-stream",
            "--header",
        ])
        .arg(format!("x-api-key: {api_key}"))
        .args(["--data-raw", r#"{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"pull_now","arguments":{}}}"#])
        .arg(url)
        .output()
    {
        Ok(output) => output,
        Err(error) => {
            eprintln!("admin pull request failed: {error}");
            return 1;
        }
    };
    if !output.status.success() {
        eprint!(
            "admin pull failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        return 1;
    }
    println!(
        "admin pull completed: {}",
        String::from_utf8_lossy(&output.stdout)
    );
    0
}

fn seed_admin_cmd(username: String, role: String) -> i32 {
    if username.is_empty() {
        eprintln!("usage: seed-admin <username> [admin|customer]");
        return 2;
    }
    let cfg = match Config::from_env() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("{e}");
            return 1;
        }
    };
    if !cfg.has_db() {
        eprintln!("no TURSO_DB_URL/TOKEN; nothing to seed into");
        return 1;
    }
    let rt = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(r) => r,
        Err(e) => {
            eprintln!("failed to start command runtime: {e}");
            return 1;
        }
    };
    rt.block_on(async move {
        let Some(db) = store::sync::ready_db(&cfg).await else {
            eprintln!("could not open replica (is the server running?) or reach cloud");
            return 1;
        };
        let st = utmelab_api::state::DbState::detached(db);
        let bytes: [u8; 18] = rand::random();
        let password: String = utmelab_api::core::hex::encode(&bytes);
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

fn import_lessons_cmd(path_str: String) -> i32 {
    if path_str.is_empty() {
        eprintln!("usage: import-lessons <path/to/lessons.json>");
        return 2;
    }
    let content = match std::fs::read_to_string(&path_str) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("failed to read file '{path_str}': {e}");
            return 1;
        }
    };
    let bundle: store::lessons::LessonBundle = match serde_json::from_str(&content) {
        Ok(bundle) => bundle,
        Err(e) => {
            eprintln!("invalid lessons json: {e}");
            return 1;
        }
    };
    let cfg = match Config::from_env() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("{e}");
            return 1;
        }
    };
    if !cfg.has_db() {
        eprintln!("no TURSO_DB_URL/TOKEN; nothing to import into");
        return 1;
    }
    let rt = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(r) => r,
        Err(e) => {
            eprintln!("failed to start runtime: {e}");
            return 1;
        }
    };
    rt.block_on(async move {
        let Some(db) = store::sync::ready_db(&cfg).await else {
            eprintln!("could not open replica or reach cloud");
            return 1;
        };
        let st = utmelab_api::state::DbState::detached(db.clone());
        if let Err(e) = store::schema::ensure_schema(&st).await {
            eprintln!("ensure schema failed: {e}");
            return 1;
        }
        match store::lessons::import_bundle(&st, &bundle).await {
            Ok(count) => match store::sync::push_db(&db, &cfg).await {
                Ok(()) => {
                    println!("imported and pushed {count} lesson records from {path_str}");
                    0
                }
                Err(e) => {
                    eprintln!("lesson import committed locally but cloud push failed: {e}");
                    1
                }
            },
            Err(e) => {
                eprintln!("import lessons failed: {e}");
                1
            }
        }
    })
}

fn clean_content_schema_cmd() -> i32 {
    let cfg = match Config::from_env() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("{e}");
            return 1;
        }
    };
    if !cfg.has_db() {
        eprintln!("no TURSO_DB_URL/TOKEN; nothing to clean");
        return 1;
    }
    let rt = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(r) => r,
        Err(e) => {
            eprintln!("failed to start command runtime: {e}");
            return 1;
        }
    };
    rt.block_on(async move {
        let Some(db) = store::sync::ready_db(&cfg).await else {
            eprintln!("could not open replica or reach cloud");
            return 1;
        };
        let st = utmelab_api::state::DbState::detached(db.clone());
        if let Err(e) = store::schema::ensure_schema(&st).await {
            eprintln!("content schema cleanup failed: {e}");
            return 1;
        }
        match store::sync::push_db(&db, &cfg).await {
            Ok(()) => {
                println!("removed retired textbook and notes tables from the Turso database");
                0
            }
            Err(e) => {
                eprintln!("content schema cleanup push failed: {e}");
                1
            }
        }
    })
}

fn import_theory_cmd(path_str: String) -> i32 {
    if path_str.is_empty() {
        eprintln!("usage: import-theory <path/to/theory_questions.json>");
        return 2;
    }
    let content = match std::fs::read_to_string(&path_str) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("failed to read file '{path_str}': {e}");
            return 1;
        }
    };
    let cfg = match Config::from_env() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("{e}");
            return 1;
        }
    };
    if !cfg.has_db() {
        eprintln!("no TURSO_DB_URL/TOKEN; nothing to import into");
        return 1;
    }
    let rt = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(r) => r,
        Err(e) => {
            eprintln!("failed to start command runtime: {e}");
            return 1;
        }
    };
    rt.block_on(async move {
        let Some(db) = store::sync::ready_db(&cfg).await else {
            eprintln!("could not open replica (is the server running?) or reach cloud");
            return 1;
        };
        let st = utmelab_api::state::DbState::detached(db.clone());
        if let Err(e) = store::schema::ensure_schema(&st).await {
            eprintln!("ensure schema failed: {e}");
            return 1;
        }
        match store::catalog::import_theory_questions_from_json(&st, &content).await {
            Ok(count) => match store::sync::push_db(&db, &cfg).await {
                Ok(()) => {
                    println!("imported and pushed {count} theory questions from {path_str}");
                    0
                }
                Err(e) => {
                    eprintln!("theory import committed locally but cloud push failed: {e}");
                    1
                }
            },
            Err(e) => {
                eprintln!("import theory failed: {e}");
                1
            }
        }
    })
}
