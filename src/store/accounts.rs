//! Account tables: api keys and dashboard users. Only reader/writer of
//! these tables; callers get [`crate::auth::Auth`] or key summaries,
//! never hashes or secrets.

use argon2::{
    password_hash::{phc::PasswordHash, PasswordHasher, PasswordVerifier},
    Algorithm, Argon2, Params, Version,
};

use crate::{auth::Auth, error::AppError, obs, state::DbState};

use super::{upstream, with_conn};

/// Dashboard-scale parameters: ~100ms even in debug builds, inside the
/// 5s route timeout with room for the gated read plus session push.
/// Raise via config if the threat model ever outgrows a dashboard login.
fn hasher() -> Result<Argon2<'static>, AppError> {
    Params::new(8192, 1, 1, None)
        .map(|params| Argon2::new(Algorithm::Argon2id, Version::V0x13, params))
        .map_err(|e| AppError::Internal(format!("argon2 parameters: {e}")))
}

fn hash_key(full: &str) -> String {
    use sha2::Digest;
    crate::core::hex::encode(&sha2::Sha256::digest(full.as_bytes()))
}

fn hash_token(token: &str) -> String {
    hash_key(token)
}

/// A same-cost hash for a missing user, so login timing does not leak
/// whether a username exists.
fn dummy_hash() -> Result<String, AppError> {
    let salt = argon2::password_hash::generate_salt();
    hasher()?
        .hash_password_with_salt(b"dummy-password-for-timing", &salt)
        .map(|h| h.to_string())
        .map_err(|e| AppError::Internal(e.to_string()))
}

/// Verify a raw `<prefix>.<secret>` key. Fails closed on anything odd.
pub(crate) async fn verify_key(s: &DbState, full: &str) -> Result<Auth, AppError> {
    let (prefix, _secret) = full.split_once('.').ok_or(AppError::Unauthorized)?;
    if prefix.is_empty() || full.len() > 256 {
        return Err(AppError::Unauthorized);
    }
    let prefix = prefix.to_string();
    let full = full.to_string();
    with_conn(s, |conn| {
        let prefix = prefix.clone();
        let full = full.clone();
        async move {
            let mut stmt = conn
                .prepare(
                    "SELECT prefix, hash, tier, scopes, revoked FROM api_keys WHERE prefix = ?1",
                )
                .await
                .map_err(upstream)?;
            let mut rows = stmt.query([prefix.as_str()]).await.map_err(upstream)?;
            let row = rows
                .next()
                .await
                .map_err(upstream)?
                .ok_or(AppError::Unauthorized)?;
            let want: String = row.get(1).map_err(upstream)?;
            let tier: String = row.get(2).map_err(upstream)?;
            let scopes: String = row.get(3).map_err(upstream)?;
            let revoked: i64 = row.get(4).map_err(upstream)?;
            let same =
                constant_time_eq::constant_time_eq(hash_key(&full).as_bytes(), want.as_bytes());
            if !same || revoked != 0 {
                return Err(AppError::Unauthorized);
            }
            Ok(Auth {
                key_id: prefix.clone(),
                is_admin: tier == "admin",
                scopes: scopes
                    .split(',')
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect(),
            })
        }
    })
    .await
}

/// Hash a password for storage. CPU-heavy: callers on async workers
/// must wrap this in `spawn_blocking`.
pub(crate) fn hash_password(password: &str) -> Result<String, AppError> {
    let salt = argon2::password_hash::generate_salt();
    hasher()?
        .hash_password_with_salt(password.as_bytes(), &salt)
        .map(|h| h.to_string())
        .map_err(|e| AppError::Internal(e.to_string()))
}

/// Create auth tables. Idempotent; safe to run at boot. Seeds nothing:
/// admin creation is the explicit `seed-admin` dev command, never env.
pub async fn ensure_auth_tables(s: &DbState) -> Result<(), AppError> {
    super::schema::ensure_schema(s).await?;
    super::schema::ensure_column(
        s,
        "dashboard_users",
        "role",
        "role TEXT NOT NULL DEFAULT 'customer'",
    )
    .await?;
    super::schema::ensure_column(s, "api_keys", "owner", "owner TEXT NOT NULL DEFAULT ''").await?;
    backfill_key_owners(s).await?;
    Ok(())
}

/// One-time backfill for keys created before ownership existed.
/// Writes only when orphans remain.
async fn backfill_key_owners(s: &DbState) -> Result<(), AppError> {
    let orphans: bool = with_conn(s, |conn| async move {
        let mut rows = conn
            .query("SELECT 1 FROM api_keys WHERE owner='' LIMIT 1", ())
            .await
            .map_err(upstream)?;
        Ok(rows.next().await.map_err(upstream)?.is_some())
    })
    .await?;
    if orphans {
        super::write::execute_write(
            s,
            "UPDATE api_keys SET owner='admin' WHERE owner=''",
            vec![],
        )
        .await?;
    }
    Ok(())
}

/// Explicit dev/admin creation: `seed-admin <username> [admin|customer]`.
/// Inserts the row or errors when the name exists. The caller prints the
/// secret once.
pub async fn seed_admin(
    s: &DbState,
    username: &str,
    password: &str,
    role: &str,
) -> Result<(), AppError> {
    if username.is_empty() || username.len() > 64 || password.len() < 12 {
        return Err(AppError::BadRequest(
            "username 1-64 chars, password at least 12".to_string(),
        ));
    }
    crate::core::accounts::check_role(role)?;
    if role != "admin" && role != "customer" {
        return Err(AppError::BadRequest(
            "role is admin or customer".to_string(),
        ));
    }
    let username = username.to_string();
    let exists: bool = with_conn(s, |conn| {
        let username = username.clone();
        async move {
            let mut rows = conn
                .query(
                    "SELECT username FROM dashboard_users WHERE username=?1",
                    [username.as_str()],
                )
                .await
                .map_err(upstream)?;
            Ok(rows.next().await.map_err(upstream)?.is_some())
        }
    })
    .await?;
    if exists {
        return Err(AppError::BadRequest("user already exists".to_string()));
    }
    let hash = hash_password(password)?;
    let n = super::write::execute_write(
        s,
        "INSERT INTO dashboard_users (username, pw_hash, role) VALUES (?1, ?2, ?3)",
        vec![
            turso::Value::Text(username),
            turso::Value::Text(hash),
            turso::Value::Text(role.to_string()),
        ],
    )
    .await?;
    if n != 1 {
        return Err(AppError::Upstream("user not stored".to_string()));
    }
    Ok(())
}

/// Promote a user to admin. Used by recovery flows; day-to-day role
/// changes go through dashboard handlers when they land.
pub async fn promote_admin(s: &DbState, username: &str) -> Result<bool, AppError> {
    set_user_role(s, username, "admin", "recovery").await
}

/// Admin role assignment. Suspended users fail every extractor below.
/// `actor` is recorded, so the change is attributable wherever it came from.
pub async fn set_user_role(
    s: &DbState,
    username: &str,
    role: &str,
    actor: &str,
) -> Result<bool, AppError> {
    crate::core::accounts::check_role(role)?;
    if username.is_empty() || username.len() > 64 {
        return Err(AppError::BadRequest("bad username".to_string()));
    }
    let n = super::write::execute_write(
        s,
        "UPDATE dashboard_users SET role=?1 WHERE username=?2",
        vec![
            turso::Value::Text(role.to_string()),
            turso::Value::Text(username.to_string()),
        ],
    )
    .await?;
    obs::role_changed(actor, username, role, n > 0);
    Ok(n > 0)
}

/// Password login. Returns (token, role) on success.
///
/// Timing-oracle note: a missing user verifies against a dummy hash so
/// absent and wrong-password logins cost the same argon2 pass, which runs
/// on the blocking pool so workers never stall on password CPU.
pub async fn login(
    s: &DbState,
    username: &str,
    password: &str,
) -> Result<(String, String), AppError> {
    use std::sync::LazyLock;
    static DUMMY: LazyLock<String> =
        LazyLock::new(|| dummy_hash().unwrap_or_else(|_| String::from("unusable")));
    if username.is_empty() || username.len() > 64 || password.is_empty() || password.len() > 512 {
        return Err(AppError::Unauthorized);
    }
    let username = username.to_string();
    let password = password.to_string();
    let found: Option<(String, String)> = with_conn(s, |conn| {
        let username = username.clone();
        async move {
            let mut stmt = conn
                .prepare("SELECT pw_hash, role FROM dashboard_users WHERE username=?1")
                .await
                .map_err(upstream)?;
            let mut rows = stmt.query([username.as_str()]).await.map_err(upstream)?;
            Ok(rows.next().await.map_err(upstream)?.and_then(|r| {
                match (r.get::<String>(0).ok(), r.get::<String>(1).ok()) {
                    (Some(a), Some(b)) => Some((a, b)),
                    _ => None,
                }
            }))
        }
    })
    .await?;
    let row_missing = found.is_none();
    let (stored, role) = found.unwrap_or_else(|| (DUMMY.clone(), String::from("customer")));
    let pass_ok = tokio::task::spawn_blocking(move || match PasswordHash::new(&stored) {
        Ok(parsed) => hasher()
            .map(|h| h.verify_password(password.as_bytes(), &parsed).is_ok())
            .unwrap_or(false),
        Err(_) => false,
    })
    .await
    .map_err(|_| AppError::Internal("auth worker failed".to_string()))?;
    if row_missing || !pass_ok {
        return Err(AppError::Unauthorized);
    }
    if !crate::core::accounts::can_login(&role) {
        return Err(AppError::Unauthorized);
    }
    let bytes: [u8; 32] = rand::random();
    let token: String = crate::core::hex::encode(&bytes);
    let exp = crate::auth::session::session_expiry();
    let wrote = super::write::execute_write(
        s,
        "INSERT INTO sessions (token_hash, username, expires_at) VALUES (?1, ?2, ?3)",
        vec![
            turso::Value::Text(hash_token(&token)),
            turso::Value::Text(username),
            turso::Value::Integer(exp),
        ],
    )
    .await?;
    if wrote != 1 {
        return Err(AppError::Upstream("session not stored".to_string()));
    }
    Ok((token, role))
}

/// Resolve a session token to (username, role). Expired sessions die here.
pub async fn verify_session(s: &DbState, token: &str) -> Result<(String, String), AppError> {
    if token.is_empty() || token.len() > 128 {
        return Err(AppError::Unauthorized);
    }
    let token = token.to_string();
    with_conn(s, |conn| {
        let token = token.clone();
        async move {
            let mut stmt = conn
                .prepare(
                    "SELECT s.username, du.role, s.expires_at FROM sessions s JOIN dashboard_users du ON du.username = s.username WHERE s.token_hash=?1",
                )
                .await
                .map_err(upstream)?;
            let mut rows = stmt
                .query([hash_token(&token).as_str()])
                .await
                .map_err(upstream)?;
            let row = rows
                .next()
                .await
                .map_err(upstream)?
                .ok_or(AppError::Unauthorized)?;
            let username: String = row.get(0).map_err(upstream)?;
            let role: String = row.get(1).map_err(upstream)?;
            let exp: i64 = row.get(2).map_err(upstream)?;
            if exp <= crate::auth::session::now_unix() {
                return Err(AppError::Unauthorized);
            }
            Ok((username, role))
        }
    })
    .await
}

/// Delete expired sessions. Hourly janitor, not login-path work.
pub async fn purge_expired(s: &DbState) -> Result<u64, AppError> {
    super::write::execute_write(
        s,
        "DELETE FROM sessions WHERE expires_at < ?1",
        vec![turso::Value::Integer(crate::auth::session::now_unix())],
    )
    .await
}

pub async fn logout_session(s: &DbState, token: &str) -> Result<(), AppError> {
    super::write::execute_write(
        s,
        "DELETE FROM sessions WHERE token_hash=?1",
        vec![turso::Value::Text(hash_token(token))],
    )
    .await?;
    Ok(())
}

#[derive(serde::Serialize)]
pub struct KeySummary {
    pub prefix: String,
    pub tier: String,
    pub scopes: String,
    pub revoked: bool,
}

/// Keys visible to the caller: everyone sees their own, admin sees all.
/// `owner=None` means the admin-wide view; customers always pass `Some`.
pub async fn list_keys(s: &DbState, owner: Option<&str>) -> Result<Vec<KeySummary>, AppError> {
    let owner = owner.map(str::to_string);
    with_conn(s, |conn| {
        let owner = owner.clone();
        async move {
            let mut rows = match owner.as_deref() {
            None => {
                conn.query(
                    "SELECT prefix, tier, scopes, revoked FROM api_keys ORDER BY prefix LIMIT 200",
                    (),
                )
                .await
                .map_err(upstream)?
            }
            Some(o) => {
                conn.query(
                    "SELECT prefix, tier, scopes, revoked FROM api_keys WHERE owner=?1 ORDER BY prefix LIMIT 200",
                    [o],
                )
                .await
                .map_err(upstream)?
            }
        };
        let mut out = Vec::new();
        while let Some(row) = rows.next().await.map_err(upstream)? {
            let revoked: i64 = row.get(3).map_err(upstream)?;
            out.push(KeySummary {
                prefix: row.get(0).map_err(upstream)?,
                tier: row.get(1).map_err(upstream)?,
                scopes: row.get(2).map_err(upstream)?,
                revoked: revoked != 0,
            });
        }
        Ok(out)
        }
    })
    .await
}

pub async fn set_revoked(
    s: &DbState,
    prefix: &str,
    revoked: bool,
    actor: &str,
) -> Result<bool, AppError> {
    crate::core::accounts::check_prefix(prefix)?;
    let n = super::write::execute_write(
        s,
        "UPDATE api_keys SET revoked=?1 WHERE prefix=?2",
        vec![
            turso::Value::Integer(revoked as i64),
            turso::Value::Text(prefix.to_string()),
        ],
    )
    .await?;
    obs::key_revoked(actor, prefix, revoked, n > 0);
    Ok(n > 0)
}

/// The public half of a raw key, for audit logs. A generated key always
/// carries a `.`; falling back to the whole string only avoids a panic on
/// an impossible shape.
fn key_prefix(full: &str) -> &str {
    full.split_once('.')
        .map(|(prefix, _)| prefix)
        .unwrap_or(full)
}

/// Customer key creation. Commercial tier, catalog read scope, owned by
/// the caller. Returns the full plaintext key exactly once — the table
/// only ever holds the hash.
pub async fn create_key(s: &DbState, owner: &str) -> Result<String, AppError> {
    if owner.is_empty() || owner.len() > 64 {
        return Err(AppError::BadRequest("bad owner".to_string()));
    }
    let full = create_key_raw(s, "commercial", "read:catalog,write:reports", owner).await?;
    obs::key_created(owner, key_prefix(&full), "commercial");
    Ok(full)
}

/// Admin-only key creation. Admin tier, full scopes, owned by nobody so it
/// shows in the staff-wide key list. Returns the plaintext once — the table
/// only ever holds the hash.
pub async fn create_admin_key(s: &DbState, actor: &str) -> Result<String, AppError> {
    let full = create_key_raw(
        s,
        "admin",
        "manage:keys,write:catalog,write:reports,read:catalog",
        "",
    )
    .await?;
    obs::key_created(actor, key_prefix(&full), "admin");
    Ok(full)
}

/// Shared insert path for every key kind. Only tier/scopes/owner differ;
/// generation, hashing, insert, and row-count check are identical.
async fn create_key_raw(
    s: &DbState,
    tier: &str,
    scopes: &str,
    owner: &str,
) -> Result<String, AppError> {
    let prefix: String = crate::core::hex::encode(&rand::random::<[u8; 6]>());
    let secret: String = crate::core::hex::encode(&rand::random::<[u8; 24]>());
    let full = format!("{prefix}.{secret}");
    let n = super::write::execute_write(
        s,
        "INSERT INTO api_keys (prefix, hash, tier, scopes, revoked, owner) VALUES (?1, ?2, ?3, ?4, 0, ?5)",
        vec![
            turso::Value::Text(prefix),
            turso::Value::Text(hash_key(&full)),
            turso::Value::Text(tier.to_string()),
            turso::Value::Text(scopes.to_string()),
            turso::Value::Text(owner.to_string()),
        ],
    )
    .await?;
    if n != 1 {
        return Err(AppError::Upstream("key not stored".to_string()));
    }
    Ok(full)
}

/// Customer key deletion. Scoped to the caller's own keys: the owner
/// predicate makes another user's prefix undeletable, not an error.
pub async fn delete_key(s: &DbState, owner: &str, prefix: &str) -> Result<bool, AppError> {
    crate::core::accounts::check_prefix(prefix)?;
    let n = super::write::execute_write(
        s,
        "DELETE FROM api_keys WHERE prefix=?1 AND owner=?2",
        vec![
            turso::Value::Text(prefix.to_string()),
            turso::Value::Text(owner.to_string()),
        ],
    )
    .await?;
    let found = n > 0;
    obs::key_deleted(owner, prefix, found);
    Ok(found)
}

#[derive(serde::Serialize)]
pub struct UserSummary {
    pub username: String,
    pub role: String,
}

/// Admin view of dashboard accounts. No hashes, ever.
pub async fn list_users(s: &DbState) -> Result<Vec<UserSummary>, AppError> {
    with_conn(s, |conn| async move {
        let mut rows = conn
            .query(
                "SELECT username, role FROM dashboard_users ORDER BY username LIMIT 200",
                (),
            )
            .await
            .map_err(upstream)?;
        let mut out = Vec::new();
        while let Some(row) = rows.next().await.map_err(upstream)? {
            out.push(UserSummary {
                username: row.get(0).map_err(upstream)?,
                role: row.get(1).map_err(upstream)?,
            });
        }
        Ok(out)
    })
    .await
}

/// File a consumer flag against any reportable target. Returns
/// `(id, duplicate)`: first filing mints an `rpt_` id (201 upstream),
/// a repeat returns the original id (200). Daily cap enforced here,
/// beside the data, so no caller can skip it.
pub async fn file_report(
    s: &DbState,
    reporter: &str,
    target_type: &str,
    target_id: &str,
    reason: &str,
    detail: Option<&str>,
) -> Result<(String, bool), AppError> {
    let now = crate::auth::session::now_unix();
    let day_start = now - now % 86400;
    let reporter = reporter.to_string();
    let count: i64 = with_conn(s, |conn| {
        let reporter = reporter.clone();
        async move {
            let mut rows = conn
                .query(
                    "SELECT COUNT(*) FROM reports WHERE reporter=?1 AND created_at>=?2",
                    vec![
                        turso::Value::Text(reporter),
                        turso::Value::Integer(day_start),
                    ],
                )
                .await
                .map_err(upstream)?;
            Ok(rows
                .next()
                .await
                .map_err(upstream)?
                .and_then(|r| r.get(0).ok())
                .unwrap_or(0))
        }
    })
    .await?;
    if count as u32 >= crate::core::reports::MAX_REPORTS_PER_DAY {
        return Err(AppError::RateLimited);
    }
    let id: String = {
        let bytes: [u8; 8] = rand::random();
        format!("rpt_{}", crate::core::hex::encode(&bytes))
    };
    let n = super::write::execute_write(
        s,
        "INSERT OR IGNORE INTO reports (id, target_type, target_id, reporter, reason, detail, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        vec![
            turso::Value::Text(id.clone()),
            turso::Value::Text(target_type.to_string()),
            turso::Value::Text(target_id.to_string()),
            turso::Value::Text(reporter.clone()),
            turso::Value::Text(reason.to_string()),
            match detail {
                Some(d) => turso::Value::Text(d.to_string()),
                None => turso::Value::Null,
            },
            turso::Value::Integer(now),
        ],
    )
    .await?;
    if n == 1 {
        return Ok((id, false));
    }
    let original: Option<String> = with_conn(s, |conn| {
        let reporter = reporter.clone();
        async move {
            let mut rows = conn
                .query(
                    "SELECT id FROM reports WHERE reporter=?1 AND target_type=?2 AND target_id=?3 AND reason=?4",
                    vec![
                        turso::Value::Text(reporter),
                        turso::Value::Text(target_type.to_string()),
                        turso::Value::Text(target_id.to_string()),
                        turso::Value::Text(reason.to_string()),
                    ],
                )
                .await
                .map_err(upstream)?;
            Ok(rows
                .next()
                .await
                .map_err(upstream)?
                .and_then(|r| r.get(0).ok()))
        }
    })
    .await?;
    match original {
        Some(id) => Ok((id, true)),
        None => Err(AppError::Upstream("report not stored".to_string())),
    }
}
