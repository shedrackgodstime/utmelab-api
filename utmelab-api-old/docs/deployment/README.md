# Deploying utmelab-api — set up once, then deploy on demand

**Status 2026-10-15: WITHDRAWN.** The API is not in production and is not
ready to be. `v0.1.0` is deliberately not cut — see the note at the end. The
host is left as scaffolding so a future deploy is a one-click operation.

> The running `v0.0.0-pre.6bcf7d8` deployment was **removed rather than
> patched**, so the next deploy meets an empty host. Nothing of the API is
> reachable: `api.utmelab.com` no longer serves (HTTP `000`).
>
> **To restore the public endpoint** (host config is all still in place):
> ```bash
> echo 'import /etc/caddy/Caddyfile.api' >> /etc/caddy/Caddyfile
> systemctl reload caddy
> systemctl enable --now utmelab-api        # after a release exists
> ```
> Everything else the deploy needs is untouched: the unit file, the gate, the
> sudoers rule, `/etc/utmelab-api/environment`, and a `deploy`-writable
> `releases/`.

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
in the same tarball as the binary (D32: Caddy serves `site/`, proxies `/api/*`).

**Deploys are serialized.** Only one runs at a time and none is cancelled
mid-flight, because the gate deletes old release directories — two overlapping
runs could delete the release the other was activating.

## ⚠ Renamed `web/` → `site/` (2026-10-12) — re-run the host setup first

The docs project was `web/` and is now `site/`. The built site ships in the
tarball as `release/site/` and Caddy serves it from
`/opt/apps/utmelab-api/current/site`.

Two things on the VPS are **installed copies** of repo files, so they still hold
the old name and will not pick this up from a push:

| On the host | Old path it hardcodes | Effect if not updated |
|---|---|---|
| `/usr/local/bin/utmelab-api-deploy` | `releases/<v>/web/index.html` | gate dies: *"has no web/index.html"* |
| `/etc/caddy/Caddyfile.api` | `root * …/current/web` | docs 404 after activation |

Before the next deploy, on the VPS as a sudoer:

```bash
sudo bash docs/deployment/vps-onetime-setup.sh    # idempotent; re-installs both
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
  && sudo systemctl reload caddy
```

The script only rewrites config and re-installs the gate — it does not touch
releases, so it is safe to run against a live deployment.

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
#    stays server-only — never in site/ or CI. Per D73 there is no
#    UTMELAB_API_DATA_DIR and no keys file: Turso is the only source and
#    nothing JSON is embedded or shipped.
sudo tee /etc/utmelab-api/environment >/dev/null <<'EOF'
UTMELAB_API_BIND=127.0.0.1:8081
UTMELAB_API_REPORTS_FILE=/var/lib/utmelab-api/reports.json
UTMELAB_BANK_CACHE_FILE=/var/lib/utmelab-api/bank_cache.json
UTMELAB_BANK_REFRESH_SECS=300
KEY_CACHE_TTL_SECS=30
TURSO_DB_URL=turso://utmelab-api-ultimatekristency.aws-eu-west-1.turso.io
TURSO_DB_TOKEN=<write-token>
EOF
sudo chown root:utmelab /etc/utmelab-api/environment
sudo chmod 0640 /etc/utmelab-api/environment

# 2b. the bank snapshot path must be writable by the service
sudo mkdir -p /var/lib/utmelab-api && sudo chown utmelab:utmelab /var/lib/utmelab-api

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
- **Docs stay grouped** — `site/` builds in the same tarball; no separate deploy.

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
- `UTMELAB_API_DATA_DIR` and `UTMELAB_API_KEYS_FILE` are **removed** from the host
  env file (D73, 2026-10-15). `config.data_dir()` is consumed nowhere outside
  `config.rs`, and keys have lived in Turso since D53. They were dead config
  that made the host look like it still served JSON.
- The release is `binary + site/`. Per D73 the embedded catalog/novels are being
  dropped and `data/questions.json` no longer ships — nothing JSON is needed to
  serve. `data/` and `JsonStore` stay in the repo for local tagging, verification
  and `import --turso`; that loop never runs on the host.
- `UTMELAB_BANK_CACHE_FILE` must point inside `/var/lib/utmelab-api`. The default
  is `var/bank_cache.json`, which resolves under the read-only release dir, so
  the cache could never be written and every boot did a full Turso re-fetch.

## v0.1.0 is deliberately not cut

The prerelease pipeline is proven end to end — it has built, shipped, activated
and health-checked six times on this host — but the API is **not ready**. It is
being held while D73 lands: nothing JSON should be embedded in the served binary
or shipped in the release, and that removal is a code change, not a deploy.

Do not tag `v0.1.0` until that is done and the release artifact is
`binary + site/` with no `data/`.

## Proposal (not implemented) — an edge smoke check after every deploy

**Status: proposal only. Nothing has been written, and nothing runs today.**
This section is the proposal. Decide it, then implement it.

### The hole

A green build and a green deploy gate prove nothing about what the internet
actually gets. The gate health-checks `127.0.0.1:8081`, so Caddy, TLS and route
resolution are all outside what it can observe. `cargo test` does not see them
either, and `astro preview` resolves directories itself — so the site works
locally and fails on the host, which is the worst combination.

Two bugs shipped green through exactly that hole:

1. **The docs tier shadowed the API.** Caddy orders `file_server` *before*
   `reverse_proxy`, so `try_files {path} /index.html` answered `/health` and
   every `/api/*` route with HTML. The binary was live and correct on loopback
   the whole time. Only a request from outside would have caught it.
2. **Every docs URL rendered the home page.** `try_files` matched real files
   (`/_astro/*.css`, `/docs/x/index.html`) but not *directory* URLs, so
   `/docs/guides/quickstart/`, `/dashboard/` and `/docs/` all fell through to
   `index.html` — **with HTTP 200**, so even a status-code check passes.

### Proposed check

A single script, run as the last step of the deploy job, against
`https://api.utmelab.com` from the runner (not the host — the point is the
public path). Three groups:

| Group | Asserts | Catches |
|---|---|---|
| API reaches the binary | `/health` is 200, is JSON not HTML, and carries `version` / `bank_version` / `subjects` / `questions`; `/api/v1/exams` is 200 with real catalog data; `/api/v1/questions` is 401 without a key | bug 1 |
| Docs serve **distinct** pages | `/`, `/docs/`, `/docs/guides/quickstart/`, `/dashboard/` each return 200, a non-empty `<title>`, and **titles that differ from each other** | bug 2 |
| Misses and redirects | a random missing path is **404**; an extensionless docs URL is **301/308**, not a 200 | bug 2's status-blind half |

Exit non-zero on any failure, so the deploy run goes red.

### The part that matters

**Assert distinct content, not just status codes.** All four broken routes
returned **200 with the identical home page**. Any check built on status codes
passes while the site is completely broken. Deduplicate on the rendered
`<title>`, comparing as an array — titles contain spaces, and a naive
`for s in $seen` word-splits them and silently never matches.

### Why not put it in the gate

The gate is host-side, loopback-only, and root. A public check belongs in CI,
where the runner already has egress. Keep the gate as the loopback health
assertion it is; do not widen it.

### Also worth deciding separately

There is currently **no uptime check** on `/health` between deploys. The same
script runnable by hand (or on a schedule) would cover that gap. It is not
proposed here — it is a separate decision with its own failure noise trade-off.
