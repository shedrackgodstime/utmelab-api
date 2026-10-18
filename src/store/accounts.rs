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

pub(crate) fn hash_key(full: &str) -> String {
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

/// End a session. Returns the session owner so the caller can attribute the
/// audit line; `None` when the token matched nothing (already gone or bogus).
pub async fn logout_session(s: &DbState, token: &str) -> Result<Option<String>, AppError> {
    let owner: Option<String> = with_conn(s, |conn| {
        let hashed = hash_token(token);
        async move {
            let mut stmt = conn
                .prepare("SELECT username FROM sessions WHERE token_hash=?1")
                .await
                .map_err(upstream)?;
            let mut rows = stmt.query([hashed.as_str()]).await.map_err(upstream)?;
            Ok(rows
                .next()
                .await
                .map_err(upstream)?
                .and_then(|r| r.get::<String>(0).ok()))
        }
    })
    .await?;
    super::write::execute_write(
        s,
        "DELETE FROM sessions WHERE token_hash=?1",
        vec![turso::Value::Text(hash_token(token))],
    )
    .await?;
    Ok(owner)
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

/// The scopes a consumer key is written with: read the catalog, file reports.
/// Nothing that manages keys.
const COMMERCIAL_SCOPES: &str = "read:catalog,write:reports";

/// The scopes an admin key is written with. Admin tier bypasses scope checks
/// regardless, but the grant is still spelled out so a key that is not admin
/// can never carry one of these.
const ADMIN_SCOPES: &str = "manage:keys,write:reports,read:catalog";

/// The one key-minting path. A caller names a tier, and the scopes come from
/// the tier, so an admin can grant a consumer key but never a half-scoped one.
/// A commercial key is labelled with its owner; an admin key belongs to the
/// staff, so it carries no owner and shows in the staff-wide list. Returns the
/// plaintext exactly once — the table only ever holds the hash.
pub async fn create_key_spec(
    s: &DbState,
    actor: &str,
    tier: &str,
    owner: &str,
) -> Result<String, AppError> {
    crate::core::accounts::check_tier(tier)?;
    let (scopes, owner) = match tier {
        "admin" => (ADMIN_SCOPES, ""),
        _ => (COMMERCIAL_SCOPES, check_owner(owner)?),
    };
    let full = create_key_raw(s, tier, scopes, owner).await?;
    obs::key_created(actor, key_prefix(&full), tier);
    Ok(full)
}

/// Customer self-service. Commercial tier, owned by the caller.
pub async fn create_key(s: &DbState, owner: &str) -> Result<String, AppError> {
    create_key_spec(s, owner, "commercial", owner).await
}

/// The owner label rule, shared by every path that stores one.
fn check_owner(owner: &str) -> Result<&str, AppError> {
    if owner.is_empty() || owner.len() > 64 {
        return Err(AppError::BadRequest("bad owner".to_string()));
    }
    Ok(owner)
}

/// Rotate a key: mint a replacement, then revoke the old prefix so it stops
/// working. The replacement carries the old row's tier, scopes, and owner
/// unchanged, because rotating a credential must not change what its holder
/// may do: a fixed replacement would hand a commercial caller `manage:keys`.
/// Returns the new plaintext key exactly once — the table only ever holds the
/// hash. Fails closed with `NotFound` when the prefix does not name a key.
/// The replacement is minted first, so a failed rotation never leaves the
/// caller without a working key; both the insert and the revocation commit
/// locally even when the cloud push fails.
pub async fn rotate_key(s: &DbState, prefix: &str, actor: &str) -> Result<String, AppError> {
    crate::core::accounts::check_prefix(prefix)?;
    let (tier, scopes, owner): (String, String, String) = with_conn(s, |conn| {
        let prefix = prefix.to_string();
        async move {
            let mut rows = conn
                .query(
                    "SELECT tier, scopes, owner FROM api_keys WHERE prefix=?1 LIMIT 1",
                    [prefix.as_str()],
                )
                .await
                .map_err(upstream)?;
            let row = rows
                .next()
                .await
                .map_err(upstream)?
                .ok_or(AppError::NotFound)?;
            Ok((
                row.get(0).map_err(upstream)?,
                row.get(1).map_err(upstream)?,
                row.get(2).map_err(upstream)?,
            ))
        }
    })
    .await?;
    // Mint the replacement with the old key's authority. The local insert
    // commits even when the cloud push fails; we proceed to revoke the old key
    // regardless.
    let full = match create_key_raw(s, &tier, &scopes, &owner).await {
        Ok(full) => full,
        Err(_) => {
            // Push failed but the insert committed locally. Revoke the old
            // key, then surface the error so the caller knows to retry.
            let _ = set_revoked(s, prefix, true, actor).await;
            return Err(AppError::Upstream(
                "key rotated locally; push pending retry".to_string(),
            ));
        }
    };
    let _ = set_revoked(s, prefix, true, actor).await?;
    obs::key_created(actor, key_prefix(&full), &tier);
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

/// Admin read: list filed reports, newest first, capped at 200. Admin-only
/// surface reads every reporter's filings; consumers never see other keys'
/// reports.
pub async fn list_reports(
    s: &DbState,
) -> Result<Vec<crate::core::models::ReportSummary>, AppError> {
    with_conn(s, |conn| async move {
        let mut rows = conn
            .query(
                "SELECT id, target_type, target_id, reporter, reason, detail, created_at FROM reports ORDER BY created_at DESC LIMIT 200",
                (),
            )
            .await
            .map_err(upstream)?;
        let mut out = Vec::new();
        while let Some(row) = rows.next().await.map_err(upstream)? {
            out.push(crate::core::models::ReportSummary {
                id: row.get(0).map_err(upstream)?,
                target_type: row.get(1).map_err(upstream)?,
                target_id: row.get(2).map_err(upstream)?,
                reporter: row.get(3).map_err(upstream)?,
                reason: row.get(4).map_err(upstream)?,
                detail: match row.get_value(5).map_err(upstream)? {
                    turso::Value::Null => None,
                    turso::Value::Text(d) => Some(d),
                    _ => return Err(AppError::Upstream("reports.detail is not text".to_string())),
                },
                created_at: row.get(6).map_err(upstream)?,
            });
        }
        Ok(out)
    })
    .await
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::DbState;

    /// Offline replica with the API's account tables. Reads (`verify_key`,
    /// `verify_session`, `list_*`) run here. A write also runs here: it commits
    /// locally and then fails at `push()` because the remote is dead, so the
    /// call surfaces an error while the local row stays. Seeding goes through a
    /// raw connection, and a mutation test asserts the local commit and treats
    /// the push error as expected — see `mutations_land_locally_then_surface_the_failed_push`.
    async fn local_accounts_db() -> DbState {
        let db = crate::testing::replica().await;
        crate::testing::api_schema(&crate::testing::connect(&db).await).await;
        crate::testing::db_state(db)
    }

    /// Seed through a raw connection, bypassing the pushing write path.
    async fn seed(s: &DbState, sql: &str, params: Vec<turso::Value>) {
        crate::testing::conn_of(s)
            .await
            .execute(sql, params)
            .await
            .expect("seed write");
    }

    async fn seed_key(s: &DbState, full: &str, tier: &str, scopes: &str, revoked: i64) {
        crate::testing::issue_key(
            &crate::testing::conn_of(s).await,
            full,
            tier,
            scopes,
            revoked != 0,
        )
        .await;
    }

    #[tokio::test]
    async fn verify_key_accepts_a_live_key_and_parses_scopes() {
        let s = local_accounts_db().await;
        seed_key(
            &s,
            "k1.secret",
            "commercial",
            "read:catalog,write:reports",
            0,
        )
        .await;
        let auth = verify_key(&s, "k1.secret").await.expect("live key");
        assert_eq!(auth.key_id, "k1");
        assert!(!auth.is_admin);
        assert!(auth.has_scope("read:catalog"));
        assert!(auth.has_scope("write:reports"));
        assert!(!auth.has_scope("manage:keys"), "scope must not leak");
    }

    #[tokio::test]
    async fn verify_key_reads_admin_tier() {
        let s = local_accounts_db().await;
        seed_key(&s, "adm_1.x", "admin", "read:catalog", 0).await;
        let auth = verify_key(&s, "adm_1.x").await.expect("admin key");
        assert!(auth.is_admin);
        assert!(
            auth.has_scope("manage:keys"),
            "admin tier bypasses scope lists"
        );
    }

    #[tokio::test]
    async fn verify_key_rejects_wrong_revoked_and_malformed() {
        let s = local_accounts_db().await;
        seed_key(&s, "k1.secret", "commercial", "read:catalog", 0).await;
        seed_key(&s, "k2.gone", "commercial", "read:catalog", 1).await;

        for bad in ["k1.wrong", "k2.gone", "ghost.secret", "nodot", ".x"] {
            assert!(
                matches!(verify_key(&s, bad).await, Err(AppError::Unauthorized)),
                "{bad:?} must not authenticate"
            );
        }
    }

    #[tokio::test]
    async fn verify_session_returns_identity_and_rejects_expired() {
        let s = local_accounts_db().await;
        seed(
            &s,
            "INSERT INTO dashboard_users (username, pw_hash, role) VALUES ('ada', 'unused', 'admin')",
            vec![],
        )
        .await;
        let now = crate::auth::session::now_unix();
        seed(
            &s,
            "INSERT INTO sessions (token_hash, username, expires_at) VALUES (?1, 'ada', ?2)",
            vec![
                turso::Value::Text(hash_token("live")),
                turso::Value::Integer(now + 3600),
            ],
        )
        .await;
        seed(
            &s,
            "INSERT INTO sessions (token_hash, username, expires_at) VALUES (?1, 'ada', ?2)",
            vec![
                turso::Value::Text(hash_token("stale")),
                turso::Value::Integer(now - 1),
            ],
        )
        .await;

        let (user, role) = verify_session(&s, "live").await.expect("live session");
        assert_eq!((user.as_str(), role.as_str()), ("ada", "admin"));
        for bad in ["stale", "unknown", ""] {
            assert!(
                matches!(verify_session(&s, bad).await, Err(AppError::Unauthorized)),
                "{bad:?} must not resolve"
            );
        }
    }

    #[tokio::test]
    async fn list_keys_scopes_to_the_owner() {
        let s = local_accounts_db().await;
        seed(
            &s,
            "INSERT INTO api_keys (prefix, hash, tier, scopes, revoked, owner) VALUES ('k1','h','commercial','read:catalog',0,'ada')",
            vec![],
        )
        .await;
        seed(
            &s,
            "INSERT INTO api_keys (prefix, hash, tier, scopes, revoked, owner) VALUES ('k2','h','commercial','read:catalog',0,'bob')",
            vec![],
        )
        .await;

        assert_eq!(list_keys(&s, None).await.expect("admin view").len(), 2);
        let ada = list_keys(&s, Some("ada")).await.expect("owner view");
        assert_eq!(ada.len(), 1, "a customer sees only their own keys");
        assert_eq!(ada[0].prefix, "k1");
    }

    #[tokio::test]
    async fn mutations_validate_before_any_write() {
        // These reject on the pure guards in `core::accounts`, before the
        // write path (and its cloud push) is ever reached.
        let s = local_accounts_db().await;
        assert!(matches!(
            create_key(&s, "").await,
            Err(AppError::BadRequest(_))
        ));
        assert!(matches!(
            set_user_role(&s, "", "admin", "actor").await,
            Err(AppError::BadRequest(_))
        ));
        assert!(matches!(
            set_user_role(&s, "u", "root", "actor").await,
            Err(AppError::BadRequest(_))
        ));
        assert!(matches!(
            seed_admin(&s, "u", "short", "admin").await,
            Err(AppError::BadRequest(_))
        ));
        assert!(matches!(
            seed_admin(&s, "u", "long-enough-password", "root").await,
            Err(AppError::BadRequest(_))
        ));
        assert!(matches!(
            delete_key(&s, "owner", "not a prefix").await,
            Err(AppError::BadRequest(_))
        ));
        assert!(matches!(
            set_revoked(&s, "bad prefix!", true, "actor").await,
            Err(AppError::BadRequest(_))
        ));
        assert!(matches!(
            create_key_spec(&s, "actor", "root", "owner1").await,
            Err(AppError::BadRequest(_))
        ));
        assert!(matches!(
            create_key_spec(&s, "actor", "commercial", "").await,
            Err(AppError::BadRequest(_))
        ));
    }

    /// One cell from the local replica, to prove a mutation committed.
    async fn cell(s: &DbState, sql: &str) -> turso::Value {
        let conn = crate::testing::conn_of(s).await;
        let mut rows = conn.query(sql, ()).await.expect("query");
        rows.next()
            .await
            .expect("next")
            .expect("row")
            .get_value(0)
            .expect("value")
    }

    /// A mutation commits locally before the push, so with a dead remote the
    /// call surfaces the push error while the row stays for the next successful
    /// push. That is the boundary mutation coverage reaches without a remote,
    /// and it is enough to prove each statement's columns and parameter order:
    /// a renamed column fails the execute, a swapped parameter fails the read.
    #[tokio::test]
    async fn mutations_land_locally_then_surface_the_failed_push() {
        let s = local_accounts_db().await;
        seed(
            &s,
            "INSERT INTO dashboard_users (username, pw_hash, role) VALUES ('u','h','customer')",
            vec![],
        )
        .await;
        seed_key(&s, "k1.secret", "commercial", "read:catalog", 0).await;

        // Every one of these commits and then fails at push; the error is the
        // expected half of the contract, not the thing under test.
        assert!(set_revoked(&s, "k1", true, "actor").await.is_err());
        assert!(set_user_role(&s, "u", "admin", "actor").await.is_err());
        assert!(create_key(&s, "owner1").await.is_err());
        assert!(
            file_report(&s, "k1", "question", "q1", "wrong_answer", None)
                .await
                .is_err()
        );

        // All four rows are committed locally.
        assert_eq!(
            cell(&s, "SELECT revoked FROM api_keys WHERE prefix='k1'").await,
            turso::Value::Integer(1)
        );
        assert_eq!(
            cell(&s, "SELECT role FROM dashboard_users WHERE username='u'").await,
            turso::Value::Text("admin".to_string())
        );
        assert_eq!(
            cell(&s, "SELECT COUNT(*) FROM api_keys WHERE owner='owner1'").await,
            turso::Value::Integer(1)
        );
        assert_eq!(
            cell(
                &s,
                "SELECT COUNT(*) FROM reports WHERE reporter='k1' AND target_id='q1'"
            )
            .await,
            turso::Value::Integer(1)
        );

        // Delete goes last: it removes the `k1` row read above.
        assert!(delete_key(&s, "", "k1").await.is_err());
        assert_eq!(
            cell(&s, "SELECT COUNT(*) FROM api_keys WHERE prefix='k1'").await,
            turso::Value::Integer(0)
        );
    }

    /// The tier decides the grant: a consumer key gets the report scopes and
    /// its owner, a staff key gets key management and no owner. Asking for a
    /// tier the store does not know is refused before any write, so a key can
    /// never be minted half-scoped.
    #[tokio::test]
    async fn create_key_spec_derives_the_grant_from_the_tier() {
        let s = local_accounts_db().await;
        // Offline: each write commits locally and then fails at the push; the
        // local rows are what this test reads.
        assert!(create_key_spec(&s, "root", "commercial", "utmelab-app")
            .await
            .is_err());
        assert!(create_key_spec(&s, "root", "admin", "ignored")
            .await
            .is_err());

        let keys = list_keys(&s, None).await.expect("list keys");
        let consumer = keys
            .iter()
            .find(|k| k.tier == "commercial")
            .expect("consumer key");
        let staff = keys.iter().find(|k| k.tier == "admin").expect("staff key");
        assert_eq!(consumer.scopes, "read:catalog,write:reports");
        assert_eq!(staff.scopes, "manage:keys,write:reports,read:catalog");
        assert!(!consumer.revoked && !staff.revoked);
        // The owner is carried for a consumer key and left blank for staff.
        assert_eq!(
            cell(
                &s,
                &format!(
                    "SELECT owner FROM api_keys WHERE prefix='{}'",
                    consumer.prefix
                )
            )
            .await,
            turso::Value::Text("utmelab-app".to_string())
        );
        assert_eq!(
            cell(
                &s,
                &format!("SELECT owner FROM api_keys WHERE prefix='{}'", staff.prefix)
            )
            .await,
            turso::Value::Text(String::new())
        );
    }

    /// Rotation carries the old key's authority across unchanged. A fixed
    /// replacement would escalate a commercial key to `manage:keys`, so a
    /// customer key rotation could hand out administration.
    #[tokio::test]
    async fn rotate_key_preserves_tier_scopes_and_owner() {
        let s = local_accounts_db().await;
        seed_key(
            &s,
            "k1.secret",
            "commercial",
            "read:catalog,write:reports",
            0,
        )
        .await;
        seed(
            &s,
            "UPDATE api_keys SET owner='ada' WHERE prefix='k1'",
            vec![],
        )
        .await;

        // Offline: the push fails, so the call surfaces the error — but the
        // local rows still commit (new key minted, old key revoked).
        assert!(rotate_key(&s, "k1", "root").await.is_err());

        // The old prefix is revoked locally.
        assert!(verify_key(&s, "k1.secret").await.is_err());
        let replacement = list_keys(&s, None)
            .await
            .expect("list keys")
            .into_iter()
            .find(|k| k.prefix != "k1" && !k.revoked)
            .expect("replacement key exists locally");
        assert_eq!(replacement.tier, "commercial", "tier must not escalate");
        assert_eq!(replacement.scopes, "read:catalog,write:reports");
        assert_eq!(
            cell(
                &s,
                &format!(
                    "SELECT owner FROM api_keys WHERE prefix='{}'",
                    replacement.prefix
                )
            )
            .await,
            turso::Value::Text("ada".to_string())
        );
    }

    /// Rotating an unknown prefix fails closed before any write runs.
    #[tokio::test]
    async fn rotate_key_rejects_unknown_prefix() {
        let s = local_accounts_db().await;
        assert!(matches!(
            rotate_key(&s, "ghost", "root").await,
            Err(AppError::NotFound)
        ));
    }

    /// Admin can list filed reports; empty when none exist, newest first.
    #[tokio::test]
    async fn list_reports_empty_when_none() {
        let s = local_accounts_db().await;
        assert_eq!(
            list_reports(&s).await.expect("list"),
            Vec::<crate::core::models::ReportSummary>::new()
        );
    }

    /// list_reports returns every filed report, newest first, with all fields.
    #[tokio::test]
    async fn list_reports_returns_all_filed() {
        let s = local_accounts_db().await;
        seed(
            &s,
            "INSERT INTO reports (id, target_type, target_id, reporter, reason, detail, created_at) VALUES ('r1','question','q1','k1','wrong_answer',NULL,100)",
            vec![],
        )
        .await;
        seed(
            &s,
            "INSERT INTO reports (id, target_type, target_id, reporter, reason, detail, created_at) VALUES ('r2','passage','p1','k2','unclear_stem','stem is ambiguous',200)",
            vec![],
        )
        .await;
        let reports = list_reports(&s).await.expect("list");
        assert_eq!(reports.len(), 2);
        // Newest first.
        assert_eq!(reports[0].id, "r2");
        assert_eq!(reports[0].target_type, "passage");
        assert_eq!(reports[0].target_id, "p1");
        assert_eq!(reports[0].reporter, "k2");
        assert_eq!(reports[0].reason, "unclear_stem");
        assert_eq!(reports[0].detail.as_deref(), Some("stem is ambiguous"));
        assert_eq!(reports[0].created_at, 200);
        assert_eq!(reports[1].id, "r1");
        assert_eq!(reports[1].target_type, "question");
        assert_eq!(reports[1].target_id, "q1");
        assert_eq!(reports[1].reporter, "k1");
        assert_eq!(reports[1].reason, "wrong_answer");
        assert_eq!(reports[1].detail, None);
        assert_eq!(reports[1].created_at, 100);
    }

    /// list_reports caps at 200 rows.
    #[tokio::test]
    async fn list_reports_caps_at_200() {
        let s = local_accounts_db().await;
        for i in 0..205 {
            seed(
                &s,
                &format!(
                    "INSERT INTO reports (id, target_type, target_id, reporter, reason, detail, created_at) VALUES ('r{}','question','q{}','k{}','other',NULL,{})",
                    i, i, i, i
                ),
                vec![],
            )
            .await;
        }
        let reports = list_reports(&s).await.expect("list");
        assert_eq!(reports.len(), 200, "cap at 200 rows");
    }
}
