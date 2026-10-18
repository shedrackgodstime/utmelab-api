# Deploying utmelab-api — set up once, then deploy on demand

**Status: live.** `api.utmelab.com` serves this binary and its static site. The
pipeline is the same pattern the parent UTME-Lab app runs on the same host. The
host install (unit, sudoers, Caddy site, `/etc/utmelab-api/environment`) is
one-time, and `vps-onetime-setup.sh` re-installs the two pieces that come from
this repo.

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
`/health`, `/ready`, `/mcp` and `/mcp/admin`. Every one of those needs its own
matcher: the static tier is the fallback, so any surface Caddy does not name is
answered by `file_server` (an empty-body 404), not by the binary.

**Deploys are serialized.** Only one runs at a time and none is cancelled
mid-flight, because the host gate prunes old release directories. Two overlapping
runs could delete the release the other was activating.

## The host gate

The one privileged step is the host's shared `/usr/local/bin/deploy-service`,
called by the deploy job as:

```bash
sudo /usr/local/bin/deploy-service utmelab-api v0.0.0-pre.<sha>
```

It is host-side tooling shared with the parent app. **This repo does not ship
it.** CI has already extracted the release at
`/opt/apps/utmelab-api/releases/<v>` (the binary plus `site/`) by the time it
runs, and the gate owns everything after that: validate the app name and the
version, re-point `/opt/apps/utmelab-api/current`, restart `utmelab-api.service`,
wait for `/ready`, then prune old releases.

Two constraints come from this side of the wire:

1. The version argument arrives from a dispatchable workflow. The gate must
   validate it as strict semver and never interpolate it into a shell command.
   An earlier per-app gate did exactly that; when it moved out of the repo, the
   validation had to move with it.
2. `utmelab-api` listens on **8081**, not the parent's 8080. A gate that polls
   the wrong port fails a boot that is perfectly healthy.

## Config lives on the host as installed copies — a repo edit is not enough

Two host files are copies of repo files, so a push never updates them:

| On the host | Repo source | Effect if not updated |
|---|---|---|
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
sudo bash docs/deployment/vps-onetime-setup.sh    # idempotent; re-installs both
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
  && sudo systemctl reload caddy
```

The script only rewrites host config and the sudoers rule. It never touches
releases or the gate, so it is safe to run against a live deployment.

## What's already done on the host (from the parent)

- VPS `209.74.85.163`, SSH `:22022`, UFW (22022/80/443), Caddy, swap.
- `deploy` user + dedicated SSH key; NOPASSWD sudo is restricted to the deploy
  gate and nothing else. This repo's workflow calls the shared
  `/usr/local/bin/deploy-service`.
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

# 3. The gate is host tooling, shared with the parent app, and is not installed
#    from this repo. Confirm it exists and that it knows this app's port:
ls -l /usr/local/bin/deploy-service

# 4. Restricted sudo. deploy may run exactly the gate, nothing else.
echo 'deploy ALL=(root) NOPASSWD: /usr/local/bin/deploy-service' | sudo tee /etc/sudoers.d/utmelab-api-deploy
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
| `utmelab-api.service` | hardened systemd unit, binds `127.0.0.1:8081`, reads `/etc/utmelab-api/environment` |
| `Caddyfile.api` | `api.utmelab.com` routes `handle` blocks for `/api/*`,`/health`,`/ready`,`/mcp`,`/mcp/*` to :8081; everything else is the static site |
| `vps-onetime-setup.sh` | idempotent, re-runnable: dirs, env, sudoers, service, Caddy site |
| `../../.github/workflows/deploy.yml` | build (Rust + site) → SCP → gate → smoke, on `Run workflow` or `v*` tags |
| `../../.github/workflows/quality.yml` | push/PR gate: fmt, clippy, doc, tests, site build |

## Why this removes the stress

- **Config is one-time** and lives on the host (env file, service, Caddy) — not
  re-done per deploy.
- **Deploys are one click** — you choose to ship; `main` never ships itself.
- **Failures are loud, not hidden.** A release that never answers `/ready` is
  never activated and the run goes red. There is no auto-rollback, so a broken
  build cannot quietly sit behind a healthy-looking symlink.
- **The VPS stays small.** On a healthy deploy the gate prunes every release
  except the active one, so one prerelease (binary plus static site) is all the
  disk carries.
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
identical home page. Four groups:

| Group | Asserts | Catches |
|---|---|---|
| API reaches the binary | `/ready` is 200 (polled, 18×10 s) and not HTML; `/health` is 200 and not HTML; `/api/v1/exams` is **401** without a key; `/openapi.json` is a JSON OpenAPI document; `/mcp` and `/mcp/admin` answer **401**, not an empty 404 | the docs tier shadowing the API, or `/mcp` losing its proxy |
| Discovery is open | `/api/v1/public/summary` is 200 with four numeric totals and `verified <= held`; `/api/v1/public/exams` is 200, cacheable, non-empty, and carries no field outside the coarse key set | a stray gate on the funnel, or a payload that widened |
| Site serves **distinct** pages | `/`, `/docs/`, `/docs/guides/quickstart/`, `/dashboard/` each return 200, a non-empty `<title>`, and **titles that differ from each other** | a `try_files` fallback answering every directory URL |
| Misses and redirects | a random missing path is **404**; an extensionless docs URL is **301/308**, not a 200 | status-blind fallthrough |

Titles are compared as an array, never word-split, because they contain spaces.
Exit is non-zero on any failure, so the deploy run goes red.

**Assert distinct content, not just status codes.** That is the whole point of
the script: a status-only check passes while the site is completely broken.

### Scheduled uptime

`uptime.yml` runs the same script against the public origin once a day, with
`SMOKE_READY_TRIES=1` so it reports an outage immediately instead of waiting out
a boot. Alerting is GitHub's own notification to the repo owner, not a pager.
