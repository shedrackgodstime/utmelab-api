-- 0001_api_keys.sql — extracted verbatim from src/keys/turso.rs DDL (D53).
-- The single source of the api_keys table. Applied by src/db on boot.
CREATE TABLE IF NOT EXISTS api_keys (
    id            TEXT PRIMARY KEY,
    key_hash      TEXT NOT NULL UNIQUE,
    key_prefix    TEXT,
    label         TEXT NOT NULL,
    account_id    TEXT NOT NULL DEFAULT 'local',
    plan          TEXT NOT NULL DEFAULT 'free',
    scopes        TEXT NOT NULL DEFAULT 'questions:read reports:write',
    rate_limit    INTEGER NOT NULL,
    quota_monthly INTEGER,
    created_at    TEXT NOT NULL,
    last_used_at  TEXT,
    expires_at    TEXT,
    suspended_at  TEXT,
    suspend_reason TEXT,
    revoked_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_keys_account ON api_keys(account_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
