# Deploying utmelab-api — set up once, then deploy on demand

**You do not SSH per release.** The VPS config is one-time; after that you
trigger a deploy from the Actions tab (or push a tag) and it builds and ships.
This is the same proven pattern the parent UTME-Lab app already runs on this host
(`docs/deployment/` in the parent repo, verified 2026-09-14).

## The loop (what you'll actually do)

| Action | What you type | What happens |
|---|---|---|
| **Work** | `git push` to `main` | **Nothing ships.** `main` is for working. |
| **Prerelease** | Actions → `deploy-api` → **Run workflow** | CI builds API + docs → ships → gate activates → health-checks. Version `v0.0.0-pre.<sha>`. |
| **Release** (v0.1.0, when solid) | `git tag v0.1.0 && git push origin v0.1.0` | identical machinery, stable version, same host. |
| **A deploy failed** | nothing | the run goes **red**, `/health` never answered, nothing was deleted. Fix and run it again. |

No SSH. No manual Caddy/systemd edits after the one-time setup. The docs ship
in the same tarball as the binary (D32: Caddy serves `web/`, proxies `/api/*`).

**Deploys are serialized.** Only one runs at a time and none is cancelled
mid-flight, because the gate deletes old release directories — two overlapping
runs could delete the release the other was activating.

## What's already done on the host (from the parent)

- VPS `209.74.85.163`, SSH `:22022`, UFW (22022/80/443), Caddy, swap.
- `deploy` user + dedicated SSH key; restricted to the two NOPASSWD-sudo gates
  (`utmelab-deploy` and `utmelab-api-deploy`) and nothing else.

Not inherited: **GitHub secrets are per-repository.** `utmelab-api` needs its own
`VPS_HOST` / `VPS_PORT` / `VPS_USER` / `VPS_SSH_KEY` / `VPS_KNOWN_HOSTS`, even
though UTME-Lab already holds the same values. See "First run" below.

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
# --adapter caddyfile is required; plain `caddy validate` parses as JSON and
# fails with "unexpected end of JSON input", which aborts the reload below.
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy
```

Or skip the manual steps entirely — `bash docs/deployment/vps-onetime-setup.sh`
does all six, is idempotent, and can be re-run safely.

Then trigger a deploy (Actions → `deploy-api` → **Run workflow**). The workflow
builds, ships, runs `utmelab-api-deploy <v>`, and prints health. First run
activates; `api.utmelab.com` serves docs + `/api/v1/*`.

## First run, in this order

**Status 2026-10-11: done and live.** This section is what was actually executed,
in this order. Do them in sequence.

1. **DNS first** — A record `api.utmelab.com` → `209.74.85.163`, then wait for
   it to resolve (`getent hosts api.utmelab.com`). Nothing TLS works until it
   does, so start it early — it was the only step with real lead time.
2. **Repo secrets** — set `VPS_HOST`, `VPS_PORT`, `VPS_USER`, `VPS_SSH_KEY`,
   `VPS_KNOWN_HOSTS` **on this repo**. GitHub does not share secrets between
   repositories; copying the parent's values in is a manual step. The repo was
   completely empty of secrets before this, which is why the first deploy never
   reached the VPS.
3. **One-time VPS setup** (needs root) — `bash docs/deployment/vps-onetime-setup.sh`,
   then put the real `TURSO_DB_TOKEN` in `/etc/utmelab-api/environment`. The
   script writes the literal placeholder `REPLACE_WITH_WRITE_TOKEN`; the API
   will not boot without it (keys live in Turso, no file fallback). Use the
   **rw** token — the readonly one fails on key writes.
4. **Trigger a deploy** — Actions → `deploy-api` → **Run workflow**. Read the run
   top to bottom; the first attempt surfaced four separate bugs (below).
5. **Confirm from outside** — `curl -s https://api.utmelab.com/health` must be
   JSON, and `curl -s -o /dev/null -w '%{http_code}' \
   https://api.utmelab.com/api/v1/questions` must be **401**. Step 5 is not
   optional; see the health-check caveat below.

## Verify from outside, not just from the box

**The gate health-checks `127.0.0.1:8081`. It cannot see Caddy.** A green deploy
proves the binary starts and binds; it says nothing about the edge. The first
release deployed green and served HTML for `/health`, because Caddy's
`file_server` outranks `reverse_proxy` in the default directive order and
`try_files {path} /index.html` answered every request. Loopback was perfect the
whole time.

So after any change to `Caddyfile.api`, check the public URL yourself:

```bash
curl -s https://api.utmelab.com/health          # JSON, not the docs homepage
curl -s -o /dev/null -w '%{http_code}\n' https://api.utmelab.com/api/v1/questions   # 401
curl -s -o /dev/null -w '%{http_code}\n' https://api.utmelab.com/                    # 200, docs
```

Use `handle` blocks for both tiers. A bare matcher plus `reverse_proxy` will lose
to `file_server` every time.

## What the first deploy fixed

The pipeline had never completed a run, so all of this was latent. Recorded so the
same six are not rediscovered:

| # | Symptom | Cause |
|---|---|---|
| 1 | Setup aborted at step 2/6 | script wrote `/etc/utmelab-api/environment` without creating `/etc/utmelab-api` |
| 2 | `@astrojs/markdown-remark` too old to render `.mdx` | `astro@6.4.8` pins markdown-remark `7.2.0`; `@astrojs/mdx` needs `^7.3.0`. Fixed by astro → `^7.3.8`. |
| 3 | `No files were found: ${APP}-…tar.gz` | `with:` values are not shell-expanded; `${APP}` must be `${{ env.APP }}` |
| 4 | `Artifact not found: utmelab-api-v0.0.0-pre.` | deploy job resolved the version with `git rev-parse` but had no `checkout`. Now a build job output. |
| 5 | `scp: stat local "<VPS_PORT>"` | `scp`'s port flag is `-P`; lowercase `-p` means preserve-attributes, so the port was parsed as the source path. Also `~/.ssh/deploy` in an unquoted variable never tilde-expands. |
| 6 | `/health` returned the docs homepage | `file_server` ordered before `reverse_proxy`; see above |

Bug 5 is worth remembering for its own sake: the log masks secrets, so a
mis-parsed `VPS_PORT` prints as `stat local "***"`, which reads like a missing
file rather than a flag error.

## Files in this folder

| File | Role |
|---|---|
| `utmelab-api-deploy` | the privileged gate (validate → symlink → restart → health → prune) |
| `utmelab-api.service` | hardened systemd unit, binds `127.0.0.1:8081`, reads `/etc/utmelab-api/environment` |
| `Caddyfile.api` | `api.utmelab.com` — `handle` blocks proxy `/api/*`,`/health`,`/openapi.json` to :8081; everything else is static docs |
| `vps-onetime-setup.sh` | idempotent, re-runnable: dirs, env, gate, sudoers, service, Caddy site |
| `../.github/workflows/deploy.yml` | build (Rust + bun docs) → SCP → gate, on `Run workflow` or `v*` tags |

## Why this removes the stress

- **Config is one-time** and lives on the host (env file, service, Caddy) — not
  re-done per deploy.
- **Deploys are one click** — you choose to ship; `main` never ships itself.
- **Failures are loud, not hidden** — the gate health-checks `/health` and exits
  red with `systemctl status` + the journal in the run log. No auto-rollback, so
  a broken build can never quietly sit behind a healthy-looking symlink.
- **The VPS stays small** — on a healthy deploy the gate deletes every release
  except the active one, so one prerelease (~24 MB unpacked: binary + bank +
  docs) is all the disk ever carries. Raise `UTMELAB_API_KEEP_RELEASES=N` once
  real releases land and history is worth keeping.
- **It's reusable** — the parent app runs the identical pattern on the same box;
  the next project copies these files and changes names + ports.
- **Docs stay grouped** — `web/` builds in the same tarball; no separate deploy.

## Notes / watch-items

- Port **8081** (parent uses 8080). Keep 8081 out of UFW — only Caddy exposes it.
- `ProtectSystem=strict` in the unit makes the root fs read-only for the app;
  the only writable path is `/var/lib/utmelab-api` (file-backed keys/reports).
  With Turso configured the API writes almost nothing at runtime.
- Caddy issues a real Let's Encrypt cert automatically for `api.utmelab.com` —
  no `tls internal` needed, unlike the parent's cutover, because DNS for this
  name was new. Issued 2026-10-11, valid to 2027-01-09.
- `TURSO_*` env names: the local `.env` also carries `TURSO_DB_TOKEN_READONLY` /
  `TURSO_API_KEY`; the service only needs `TURSO_DB_URL` + `TURSO_DB_TOKEN`. Note
  the parent's `.env` points at a *different* database (`utmelab-…`, not
  `utmelab-api-…`) — they are separate products, do not mix the tokens up.
- `UTMELAB_API_KEYS_FILE` is vestigial. Since D53 keys live in Turso and
  `KeyBackend::File` is test/import-only; the value is still read from the env
  file but its only consumer is `key import`'s default source path. Harmless,
  mildly misleading.
- `UTMELAB_API_DATA_DIR` is transitional: it must hold exactly
  `questions.json` — catalog + novels are embedded in the binary
  (`JsonStore::load_embedded`). Releases ship only that one file. Once
  questions move to Turso, the env var and the `data/` dir go away entirely:
  the release is `binary + web/`.
- `data/inbox/` (~2 MB of unverified harvested questions) never ships. Nothing
  in production reads it — it is import staging, local-only.
