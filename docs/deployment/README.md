# Deploying utmelab-api — write once, then push-to-deploy

**You do not SSH per release.** The VPS config is one-time; after that,
`git push` builds and ships automatically, and a bad push self-heals. This is
the same proven pattern the parent UTME-Lab app already runs on this host
(`docs/deployment/` in the parent repo, verified 2026-09-14).

## The loop (what you'll actually do)

| Action | What you type | What happens |
|---|---|---|
| **Prerelease** (iterate, no "release") | `git push` to `main` | CI builds API + docs → ships → gate activates → health-checked. Version `v0.0.0-pre.<sha>`. |
| **Release** (v0.1.0, when solid) | `git tag v0.1.0 && git push origin v0.1.0` | identical machinery, stable version, same host. |
| **Roll back** | (automatic) | gate keeps the previous release if health fails. Manual: re-run gate with the older version. |

No SSH. No manual Caddy/systemd edits after the one-time setup. The docs ship
in the same tarball as the binary (D32: Caddy serves `web/`, proxies `/api/*`).

## What's already done on the host (from the parent)

- VPS `209.74.85.163`, SSH `:22022`, UFW (22022/80/443), Caddy, swap.
- `deploy` user + dedicated SSH key; restricted to one NOPASSWD-sudo gate.
- GitHub secrets `VPS_HOST/VPS_PORT/VPS_USER/VPS_SSH_KEY/VPS_KNOWN_HOSTS` already set (parent reuses them).

So the API needs **only** the additions below — done once, over SSH.

## One-time VPS setup (SSH once)

Run as a sudoer (e.g. `shedrack`). Paths mirror the parent under `/opt/apps/utmelab-api`.

```bash
# 1. Layout + runtime dirs
sudo mkdir -p /opt/apps/utmelab-api/releases
sudo chown deploy:deploy /opt/apps/utmelab-api/releases
sudo chmod 0775 /opt/apps/utmelab-api/releases
sudo mkdir -p /var/lib/utmelab-api && sudo chown utmelab:utmelab /var/lib/utmelab-api

# 2. Secrets (0640 root:utmelab). Turso values you already have; rw token
#    stays server-only — never in web/ or CI.
sudo tee /etc/utmelab-api/environment >/dev/null <<'EOF'
UTMELAB_API_BIND=127.0.0.1:8081
UTMELAB_API_DATA_DIR=/opt/apps/utmelab-api/current/data
UTMELAB_API_KEYS_FILE=/var/lib/utmelab-api/api_keys.json
UTMELAB_API_REPORTS_FILE=/var/lib/utmelab-api/reports.json
TURSO_DB_URL=turso://utmelab-api-ultimatekristency.aws-eu-west-1.turso.io
TURSO_DB_TOKEN=<write-token>
KEY_CACHE_TTL_SECS=30
EOF
sudo chown root:utmelab /etc/utmelab-api/environment
sudo chmod 0640 /etc/utmelab-api/environment

# 3. Install the gate (the ONLY privileged code). From this repo:
sudo install -o root -g root -m 0755 docs/deployment/utmelab-api-deploy /usr/local/bin/utmelab-api-deploy

# 4. Restricted sudo — deploy may run exactly the gate, nothing else.
echo 'deploy ALL=(root) NOPASSWD: /usr/local/bin/utmelab-api-deploy' | sudo tee /etc/sudoers.d/utmelab-api-deploy
sudo chmod 0440 /etc/sudoers.d/utmelab-api-deploy
sudo visudo -c   # must be OK

# 5. systemd service. From this repo:
sudo install -m 0644 docs/deployment/utmelab-api.service /etc/systemd/system/utmelab-api.service
sudo systemctl daemon-reload
sudo systemctl enable utmelab-api    # not started yet — no release

# 6. Caddy site (requires DNS api.utmelab.com -> this host). From this repo:
sudo install -m 0644 docs/deployment/Caddyfile.api /etc/caddy/Caddyfile.api
# then add to /etc/caddy/Caddyfile:   import /etc/caddy/Caddyfile.api
sudo caddy validate && sudo systemctl reload caddy
```

Then push. The workflow builds, ships, runs `utmelab-api-deploy <v>`, and prints
health. First run activates; `api.utmelab.com` serves docs + `/api/v1/*`.

## Files in this folder

| File | Role |
|---|---|
| `utmelab-api-deploy` | the privileged gate (validate → symlink → restart → health → auto-rollback) |
| `utmelab-api.service` | hardened systemd unit, binds `127.0.0.1:8081`, reads `/etc/utmelab-api/environment` |
| `Caddyfile.api` | `api.utmelab.com` — proxies `/api/*`,`/health`,`/openapi.json` to :8081, serves static docs |
| `../.github/workflows/deploy.yml` | build (Rust + bun docs) → SCP → gate, on push to main and on `v*` tags |

## Why this removes the stress

- **Config is one-time** and lives on the host (env file, service, Caddy) — not
  re-done per deploy.
- **Deploys are `git push`** — CI does build+ship+activate; you never log in.
- **Failures are safe** — the gate health-checks `/health` and keeps the previous
  release; a broken prerelease can't take the API down.
- **It's reusable** — the parent app runs the identical pattern on the same box;
  the next project copies these four files and changes names + ports.
- **Docs stay grouped** — `web/` builds in the same tarball; no separate deploy.

## Notes / watch-items

- Port **8081** (parent uses 8080). Keep 8081 out of UFW — only Caddy exposes it.
- `ProtectSystem=strict` in the unit makes the root fs read-only for the app;
  the only writable path is `/var/lib/utmelab-api` (file-backed keys/reports).
  With Turso configured the API writes almost nothing at runtime.
- After DNS points `api.utmelab.com` here, Caddy issues a real Let's Encrypt
  cert automatically — no `tls internal` needed (unlike the parent's cutover,
  DNS is new for this host).
- `TURSO_*` env names: your `.env` also carries `TURSO_DB_TOKEN_READONLY` /
  `TURSO_API_KEY`; the service only needs `TURSO_DB_URL` + `TURSO_DB_TOKEN`.
