# Deploying utmelab-api — set up once, then deploy on demand

**Status: not yet run for this repo.** The pipeline below is the same pattern the
parent UTME-Lab app runs on the same host, and it was proven end to end against
the previous service on that box. The host still holds that service's install
(unit, gate, sudoers, Caddy site, `/etc/utmelab-api/environment`), and the
environment variable names changed with this binary, so **re-run
`vps-onetime-setup.sh` before the first deploy here**. Until then `api.utmelab.com`
is not serving this code.

**You do not SSH per release.** The host config is one-time. After that you
trigger a deploy from the Actions tab (or push a tag) and it builds and ships.

## The loop (what you'll actually do)

| Action | What you type | What happens |
|---|---|---|
| **Work** | `git push` to `main` | CI runs the `quality` workflow (fmt, clippy, doc, tests, site build). **Nothing ships.** |
| **Prerelease** | Actions → `deploy-api` → **Run workflow** | CI builds API + site → ships → gate activates → readiness-checks. Version `v0.0.0-pre.<sha>`. |
| **Release** (when solid) | `git tag v0.1.0 && git push origin v0.1.0` | identical machinery, stable version, same host. |
| **A deploy failed** | nothing | the run goes **red**, `/ready` never answered, nothing was deleted. Fix and run it again. |

No SSH. No manual Caddy/systemd edits after the one-time setup. The site ships
in the same tarball as the binary; Caddy serves it and proxies `/api/*`,
`/health` and `/ready`.

**Deploys are serialized.** Only one runs at a time and none is cancelled
mid-flight, because the gate deletes old release directories — two overlapping
runs could delete the release the other was activating.

## Config lives on the host as installed copies — a repo edit is not enough

Three host files are copies of repo files, so a push never updates them:

| On the host | Repo source | Effect if not updated |
|---|---|---|
| `/usr/local/bin/utmelab-api-deploy` | `docs/deployment/utmelab-api-deploy` | gate validates/polls the old way |
| `/etc/systemd/system/utmelab-api.service` | `docs/deployment/utmelab-api.service` | service runs the old `ExecStart` / env names |
| `/etc/caddy/Caddyfile.api` | `docs/deployment/Caddyfile.api` | routing is stale |

And `/etc/utmelab-api/environment` is written once by the setup script and never
touched by CI. The previous service read `UTMELAB_API_BIND` and friends; this
binary reads `PORT`, `REPLICA_PATH`, `SYNC_SECS`, `RATE_LIMIT_PER_MIN`,
`COOKIE_SECURE`, `TURSO_DB_URL`, `TURSO_DB_TOKEN` (the full set is
`.env.example`). An old env file is not fatal — unknown names are ignored — but
it means the replica lands on the read-only release dir and boot fails, so
replace it.

After any change to those files, on the VPS as a sudoer:

```bash
sudo bash docs/deployment/vps-onetime-setup.sh    # idempotent; re-installs all three
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
  && sudo systemctl reload caddy
```

The script only rewrites config and re-installs the gate — it does not touch
releases, so it is safe to run against a live deployment.

## What's already done on the host (from the parent)

- VPS `209.74.85.163`, SSH `:22022`, UFW (22022/80/443), Caddy, swap.
- `deploy` user + dedicated SSH key; restricted to the two NOPASSWD-sudo gates
  (`utmelab-deploy` and `utmelab-api-deploy`) and nothing else.
- Layout: `/opt/apps/utmelab-api/releases/`, `/var/lib/utmelab-api/`,
  `/etc/utmelab-api/environment`.

Not inherited: **GitHub secrets are per-repository.** `utmelab-api` needs its own
`VPS_HOST` / `VPS_PORT` / `VPS_USER` / `VPS_SSH_KEY` / `VPS_KNOWN_HOSTS`, even
though UTME-Lab already holds the same values.

## One-time VPS setup (SSH once)

Run as a sudoer (e.g. `shedrack`). Paths mirror the parent under
`/opt/apps/utmelab-api`.

```bash
# 1. Layout + runtime dirs
sudo mkdir -p /opt/apps/utmelab-api/releases
sudo chown deploy:deploy /opt/apps/utmelab-api/releases
sudo chmod 0775 /opt/apps/utmelab-api/releases
sudo mkdir -p /var/lib/utmelab-api && sudo chown utmelab:utmelab /var/lib/utmelab-api

# 2. Secrets (0640 root:utmelab). No data dir and no keys file: the synced
#    replica plus Turso are the only sources. rw token stays server-only.
sudo mkdir -p /etc/utmelab-api
sudo tee /etc/utmelab-api/environment >/dev/null <<'EOF'
PORT=8081
WORKER_THREADS=2
REPLICA_PATH=/var/lib/utmelab-api/sync.db
SYNC_SECS=10
RATE_LIMIT_PER_MIN=60
COOKIE_SECURE=1
TURSO_DB_URL=turso://utmelab-api-ultimatekristency.aws-eu-west-1.turso.io
TURSO_DB_TOKEN=<write-token>
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

## First run, in this order

1. **DNS first** — A record `api.utmelab.com` → `209.74.85.163`, then wait for
   it to resolve (`getent hosts api.utmelab.com`). Nothing TLS works until it
   does, so start it early; it is the only step with real lead time.
2. **Repo secrets** — set `VPS_HOST`, `VPS_PORT`, `VPS_USER`, `VPS_SSH_KEY`,
   `VPS_KNOWN_HOSTS` **on this repo**. GitHub does not share secrets between
   repositories; copying the parent's values in is a manual step.
3. **One-time VPS setup** (needs root) — `bash docs/deployment/vps-onetime-setup.sh`,
   then put the real `TURSO_DB_TOKEN` in `/etc/utmelab-api/environment`. The
   script writes the literal placeholder `REPLACE_WITH_WRITE_TOKEN`; the API
   will not boot without a real value. Use the **rw** token — the readonly one
   fails on session and key writes.
4. **Trigger a deploy** — Actions → `deploy-api` → **Run workflow**. Read the run
   top to bottom; the first attempt is where plumbing bugs surface.
5. **Confirm from outside** — see the next section. Step 5 is not optional.

## Verify from outside, not just from the box

**The gate readiness-checks `127.0.0.1:8081`. It cannot see Caddy.** A green
deploy proves the binary starts, binds and trusts its schema; it says nothing
about the edge. The first release of the previous service deployed green and
served HTML for `/health`, because Caddy's `file_server` outranks
`reverse_proxy` in the default directive order. Loopback was perfect the whole
time.

The deploy job's last step runs `site/scripts/smoke.mjs` against the public
origin and fails the run on any mismatch, so this now happens automatically.
To check by hand:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://api.utmelab.com/ready          # 200
curl -s https://api.utmelab.com/health                                          # "ok" (text, not HTML)
curl -s -o /dev/null -w '%{http_code}\n' https://api.utmelab.com/api/v1/exams   # 401 (keyed)
curl -s https://api.utmelab.com/openapi.json | head -c 40                        # {"openapi":...
curl -s -o /dev/null -w '%{http_code}\n' https://api.utmelab.com/                # 200 (landing)
```

Use `handle` blocks for both tiers. A bare matcher plus `reverse_proxy` will lose
to `file_server` every time.

## Files in this folder

| File | Role |
|---|---|
| `utmelab-api-deploy` | the privileged gate (validate → symlink → restart → readiness → prune) |
| `utmelab-api.service` | hardened systemd unit, binds `127.0.0.1:8081`, reads `/etc/utmelab-api/environment` |
| `Caddyfile.api` | `api.utmelab.com` — `handle` blocks proxy `/api/*`,`/health`,`/ready` to :8081; everything else is the static site |
| `vps-onetime-setup.sh` | idempotent, re-runnable: dirs, env, gate, sudoers, service, Caddy site |
| `../../.github/workflows/deploy.yml` | build (Rust + site) → SCP → gate → smoke, on `Run workflow` or `v*` tags |
| `../../.github/workflows/quality.yml` | push/PR gate: fmt, clippy, doc, tests, site build |

## Why this removes the stress

- **Config is one-time** and lives on the host (env file, service, Caddy) — not
  re-done per deploy.
- **Deploys are one click** — you choose to ship; `main` never ships itself.
- **Failures are loud, not hidden** — the gate readiness-checks `/ready` and
  exits red with `systemctl status` + the journal in the run log. No
  auto-rollback, so a broken build can never quietly sit behind a healthy-looking
  symlink.
- **The VPS stays small** — on a healthy deploy the gate deletes every release
  except the active one, so one prerelease (binary + static site) is all the disk
  carries. Raise `UTMELAB_API_KEEP_RELEASES=N` once real releases land.
- **Docs stay grouped** — the site builds in the same tarball; no separate deploy.

## Notes / watch-items

- Port **8081** (the parent uses 8080). Keep 8081 out of UFW — only Caddy
  exposes it.
- `ProtectSystem=strict` makes the root fs read-only for the service. The only
  writable path is `/var/lib/utmelab-api`, so `REPLICA_PATH` **must** point
  inside it. The default `db/sync.db` resolves under the read-only release dir
  and boot fails.
- The replica is the only thing written at runtime: libsql keeps `<db>-wal`,
  `<db>-log` and `<db>-changes` beside the file. Everything else is read from
  Turso or served from memory.
- Caddy obtains a real Let's Encrypt cert for `api.utmelab.com` automatically —
  no `tls internal` needed. Nothing TLS works until DNS resolves.
- `TURSO_*` env names: the local `.env` also carries
  `TURSO_DB_TOKEN_READONLY` / `TURSO_API_KEY`; the service only needs
  `TURSO_DB_URL` + `TURSO_DB_TOKEN`. The parent's `.env` points at a **different**
  database (`utmelab-…`, not `utmelab-api-…`) — separate products, do not mix
  the tokens up.
- There is no `data/` in this repo and nothing JSON is embedded: the release is
  exactly `binary + site/`. `/openapi.json` is a committed file copied into the
  build output by `site/scripts/merge.mjs`; the binary serves no document route.
- The admin surfaces (`/api/internal/admin/*`, `/mcp/admin`) need a dashboard
  user. Until one exists the key lifecycle is unoperable: run
  `cargo run -- seed-admin <username>` against the cloud database once, setting
  the password it prompts for.

## The edge smoke check

Implemented as `site/scripts/smoke.mjs`, run as the last step of the deploy job
against `https://api.utmelab.com`. It asserts distinct rendered content, not just
status codes, because two real outages shipped green by returning `200` with the
identical home page. Three groups:

| Group | Asserts | Catches |
|---|---|---|
| API reaches the binary | `/ready` is 200 (polled, 18×10 s) and not HTML; `/health` is 200 and not HTML; `/api/v1/exams` is **401** without a key; `/openapi.json` is a JSON OpenAPI document | the docs tier shadowing the API |
| Site serves **distinct** pages | `/`, `/docs/`, `/docs/guides/quickstart/`, `/dashboard/` each return 200, a non-empty `<title>`, and **titles that differ from each other** | a `try_files` fallback answering every directory URL |
| Misses and redirects | a random missing path is **404**; an extensionless docs URL is **301/308**, not a 200 | status-blind fallthrough |

Titles are compared as an array — never word-split, they contain spaces. Exit is
non-zero on any failure, so the deploy run goes red.

**Assert distinct content, not just status codes.** That is the whole point of
the script: a status-only check passes while the site is completely broken.

### Still open

There is **no uptime check** on `/ready` between deploys. The same script is
runnable by hand (or on a schedule) to cover that gap; it is a separate decision
with its own failure-noise trade-off.
