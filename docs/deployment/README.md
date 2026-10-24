# Deploying utmelab-api — one manifest, one gate, no SSH per release

**Status: live.** `api.utmelab.com` serves this binary and its static site. The
host also runs the parent UTME-Lab app through the same framework, so the
framework itself lives in `docs/deployment/host/` — it is not API-specific.

**You do not SSH per release.** Host config is one-time. After that you publish a
GitHub Release or run the workflow manually, and it builds and ships.

## The loop (what you'll actually do)

| Action | What you type | What happens |
|---|---|---|
| **Work** | `git push` to `main` | CI runs the `quality` workflow (fmt, clippy, doc, tests, site build). **Nothing ships.** |
| **Manual release** | Actions → `deploy-api` → **Run workflow** with the Cargo version | CI verifies the version → builds API + site → ships → readiness-checks. |
| **Tagged release** | `gh release create v0.0.1 --generate-notes` | publishes the tag and triggers deployment; the release tag must exactly match `Cargo.toml`. |
| **A deploy failed** | previous release | the run goes **red**, the gate restores the previous release and checks it before returning. Nothing is pruned. Fix and run it again. |
| **Roll back** | `sudo system rollback utmelab-api` | flips to the previous release; restores the old one if the target does not come up healthy. |

Deploys are **serialized** by the workflow (`concurrency: deploy-api`). The gate
prunes release directories, so two overlapping runs could delete the release the
other one was activating.

## One service is one file

`/etc/deploy-service/<service>.env` — `0600 root:root`, read twice: by systemd as
the unit's `EnvironmentFile`, and by the gate as root. Because systemd reads it as
PID 1, the file can stay root-only and the service's own user never reads its
secrets off disk.

Every key is documented in `host/service.env.example`. `utmelab-api`'s manifest
is:

```sh
SERVICE_NAME=utmelab-api
BINARY_NAME=utmelab-api
RUNTIME_USER=utmelab-api         # the process user
DOMAIN=api.utmelab.com
IP=127.0.0.1
PORT=8081
HEALTH_ENDPOINT=/ready           # the honest signal: /health only proves it bound
HEALTH_EXPECT=200
HEALTH_TRIES=60
HEALTH_DELAY=3
ASSET_PATH=site/index.html       # the static tier Caddy serves
KEEP_RELEASES=3                  # superseded releases kept for rollback
READ_WRITE_PATHS=/var/lib/utmelab-api
TURSO_DB_URL=...
TURSO_DB_TOKEN=...               # the rw token; the readonly one fails on writes
```

Everything else on the host is **derived from that file** by `system provision`:

| Derived | From |
|---|---|
| `utmelab@utmelab-api` unit + its `User`/`Group`/`ReadWritePaths` drop-in | `RUNTIME_USER`, `READ_WRITE_PATHS` |
| `/etc/caddy/sites/utmelab-api.caddy` (written once, then yours to edit) | `DOMAIN`, `IP`, `PORT` |
| `/opt/apps/utmelab-api/releases`, `/var/lib/utmelab-api`, the runtime user | the names above |

The CI identity is the one thing that is **not** derived, because it is not a
per-service fact: see [Identity model](#identity-model).

A service that needs custom routing edits **its own** site file. `provision` never
rewrites it, and the host-wide `Caddyfile` only imports `sites/*.caddy`.

## The host gate

The one privileged step is `/usr/local/bin/deploy-service`, shared by every
service on the host and called by the deploy job as:

```bash
sudo /usr/local/bin/deploy-service utmelab-api v0.0.1
```

It is host tooling, not shipped by this repo's release; its source is
`docs/deployment/host/deploy-service`. By the time it runs, CI has extracted the
tarball at `/opt/apps/utmelab-api/releases/<v>`. The gate then owns the rest:
validate the name and version, re-point `current`, restart `utmelab@utmelab-api`,
wait for the health contract, restore the previous release if the new one fails,
and prune only after success.

The service currently runs as one systemd process on one port, so activation still
has a brief restart window. The gate protects availability by automatic rollback,
but it is not true zero-downtime deployment. That requires a second process or a
proxy/socket handoff and is a separate infrastructure change.

Three properties are load-bearing:

1. **The release has to look like a release.** A known service, a valid version,
   a staged directory that ships the binary and the asset, and a release tree
   writable by CI. A tarball that is missing `site/index.html` is rejected before
   anything moves.
2. **Activation means `HEALTH_ENDPOINT` answered exactly `HEALTH_EXPECT`.** For
   this service that is `/ready`, which stays 503 until the Turso replica is
   open. A process that binds 8081 and never syncs is never called live.
3. **Pruning is by mtime, newest first**, and never runs on a failed activation.
   Stable release versions sort predictably, and the workflow refuses a release
   tag that does not match `Cargo.toml`.

Exit codes: `1` usage, `2` bad version, `3` unknown service, `4` release not
staged, `5` unusable release, `6` unit did not come up, `7` unhealthy.

## `system` — provision, enroll, verify

```bash
sudo system provision utmelab-api    # create/repair everything the manifest implies
sudo system enroll key.pub           # register a CI key (once per host, not per service)
sudo system verify                   # does the host still match the manifests?
sudo system report                   # resources + service health
sudo system deploy preview           # what a deploy would do (read-only)
```

`verify` is the one to run before trusting anything, and after any host change. It
checks the manifest's mode, the unit's enable/active state, that the process runs
as the manifest's `RUNTIME_USER`, that the release tree is writable by the CI
identity, that the Caddy port matches `PORT`, that the health contract holds
locally and publicly, and then the host-level traps: legacy per-app units, legacy
gates, and sudoers files pointing at commands that no longer exist. Exit is
non-zero if any contract is broken.

## Identity model

| Identity | Job | Reach |
|---|---|---|
| `deploy` (one for the host) | CI, over SSH key | stage any release tree, run `/usr/local/bin/deploy-service` |
| the gate (root) | privileged file moves, restart | `/opt/apps`, systemd |
| `<service>` (per service, nologin) | runs the process | its own `READ_WRITE_PATHS` |
| `caddy` (nologin) | TLS + proxy | loopback targets |
| `shedrack` | human admin | full sudo |

**One CI identity, deliberately.** An earlier revision gave each service its own
`deploy-<service>` account and key, which is the only way to stop a stolen key
from activating a neighbouring service, since no sudoers rule can tell two keys
of one account apart. It was reverted: per service that bought containment at the
cost of a login account, a home, an authorized key, a sudoers rule, a GitHub
secret pair and a key rotation, for two services on one host. Simplicity won.

What that means in plain terms: **a stolen CI key can activate any service's
already-staged release.** The gate still refuses an unknown service, a malformed
version, a release missing its binary or asset, and any activation that fails the
health contract, and it never prunes on a failed run. Treat `VPS_SSH_KEY` as a
host-level credential, not a per-service one.

The five secrets a repo needs (`VPS_HOST`, `VPS_PORT`, `VPS_USER`, `VPS_SSH_KEY`,
`VPS_KNOWN_HOSTS`) are now identical everywhere, because they describe the host,
not the service. GitHub shares secrets across repositories only through an
organisation, and this account is a personal one, so the same five values are set
in each repo (`utmelab-api`, `UTME-Lab`, and any repo added later). They change
only when the host or the CI key does, never when a service is added — which is
what makes "add a service" mean exactly one manifest and no CI change.

If containment is ever wanted back without per-service Unix users, the thin form
is per-key `command=` pinning in `deploy`'s `authorized_keys`: one entry per repo,
each locked to its own service. One account, N pinned keys.

## Rebuilding a VPS

`host/bootstrap.sh` installs the framework on a fresh cloud box and converges it to
the manifests you hand it:

```bash
sudo ./bootstrap.sh --admin shedrack --admin-key /root/shedrack.pub --manifests /root/manifests
```

It installs Caddy/curl/ufw, the gate, `system`, the template unit, the host
`Caddyfile`, any site file this repo carries (`sites/*.caddy`, installed only
when absent), the firewall rules, the admin identity, then provisions each
`<service>.env` it finds. It is idempotent and never overwrites a per-service
site file or any service data. Secrets are the only thing it cannot conjure —
they come from the manifests you copy in.

## Config: what lives where, and why a repo edit is not enough

Host config is **installed copies**, never re-read from the repo:

| On the host | Repo source | Effect of not updating it |
|---|---|---|
| `/etc/deploy-service/utmelab-api.env` | the manifest (secrets included, so it is not in git) | the service boots with the old values |
| `/usr/local/bin/deploy-service`, `/usr/local/bin/system` | `docs/deployment/host/` | the gate or tooling is stale |
| `/etc/systemd/system/utmelab@.service` | `docs/deployment/host/utmelab@.service` | unit hardening/ExecStart drifts |
| `/etc/caddy/Caddyfile` | `docs/deployment/host/Caddyfile` | per-service sites stop being imported |

After changing any of them: `sudo system verify`, then `caddy validate --config
/etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy`.

## First run, in this order

1. **DNS first** — A record `api.utmelab.com` → `209.74.85.163`, then wait for it
   to resolve (`getent hosts api.utmelab.com`). Nothing TLS works until it does,
   and it is the only step with real lead time.
2. **Host** — the framework is installed and the manifest is in place
   (`sudo system verify` says so).
3. **Repo secrets** — `VPS_HOST`, `VPS_PORT`, `VPS_USER`, `VPS_SSH_KEY`,
   `VPS_KNOWN_HOSTS`. The same five values in every repo, and the same for every
   service. This account is a personal one, so there is no organisation store to
   inherit from: set them per repo. They are written once per repo, not once per
   service.
4. **CI key** — `sudo system enroll <key>.pub` once per host, and put the private
   half in `VPS_SSH_KEY`. Adding another service does not repeat this.
5. **Trigger a deploy** — Actions → `deploy-api` → **Run workflow**.
6. **Confirm from outside** — see the next section. Step 6 is not optional.

## Verify from outside, not just from the box

**The gate readiness-checks `127.0.0.1:8081`. It cannot see Caddy.** A green deploy
proves the binary starts, binds and trusts its schema; it says nothing about the
edge. The first release of the previous service deployed green and served HTML for
`/health`, because Caddy's `file_server` outranks `reverse_proxy` in the default
directive order. Loopback was perfect the whole time.

The deploy job's last step runs `site/scripts/smoke.mjs` against the public origin
and fails the run on any mismatch. To check by hand:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://api.utmelab.com/ready          # 200
curl -s https://api.utmelab.com/health                                          # "ok" (text, not HTML)
curl -s -o /dev/null -w '%{http_code}\n' https://api.utmelab.com/api/v1/exams   # 401 (keyed)
curl -s https://api.utmelab.com/openapi.json | head -c 40                       # {"openapi":...
curl -s -o /dev/null -w '%{http_code}\n' https://api.utmelab.com/               # 200 (landing)
```

Use `handle` blocks for both tiers. A bare matcher plus `reverse_proxy` will lose to
`file_server` every time.

## Files in this folder

| File | Role |
|---|---|
| `host/service.env.example` | the manifest contract: one file per service, every key documented |
| `host/deploy-service` | the shared gate (validate → activate → health → prune) |
| `host/system` | provision / enroll / verify / report / preview / rollback / root |
| `host/utmelab@.service` | the one systemd template every service instantiates |
| `host/Caddyfile` | host entry point; imports per-service `sites/*.caddy` |
| `host/bootstrap.sh` | fresh-VPS install, then converge the manifests |
| `sites/utmelab-api.caddy` | this service's edge routing (static tier + named proxies); the repo copy is canonical |
| `../../.github/workflows/deploy.yml` | build (Rust + site) → SCP → gate → smoke |

## Notes / watch-items

- Port **8081** (the parent uses 8080). Keep 8081 out of UFW — only Caddy exposes it.
- `ProtectSystem=strict` makes the root fs read-only for the service. The only
  writable path is `/var/lib/utmelab-api`, so `REPLICA_PATH` **must** point inside
  it. The default `db/sync.db` resolves under the read-only release dir and boot
  fails.
- The replica is the only thing written at runtime: libsql keeps `<db>-wal`,
  `<db>-log` and `<db>-changes` beside the file. Everything else is read from
  Turso or served from memory.
- Caddy obtains a real Let's Encrypt cert for `api.utmelab.com` automatically — no
  `tls internal`. Nothing TLS works until DNS resolves.
- `TURSO_*` env names: the local `.env` also carries `TURSO_DB_TOKEN_READONLY` /
  `TURSO_API_KEY`; the service needs only `TURSO_DB_URL` + `TURSO_DB_TOKEN`, and
  it must be the **rw** token. The parent's `.env` points at a **different**
  database (`utmelab-…`, not `utmelab-api-…`) — separate products, do not mix the
  tokens up.
- This binary reads no `JWT_SECRET`. A manifest that carries one is carrying dead
  config.
- There is no `data/` in this repo and nothing JSON is embedded: the release is
  exactly `binary + site/`. `/openapi.json` is a committed file copied into the
  build output by `site/scripts/merge.mjs`; the binary serves no document route.
- The admin surfaces (`/api/internal/admin/*`, `/mcp/admin`) need a dashboard user.
  Until one exists the key lifecycle is unoperable: run
  `cargo run -- seed-admin <username>` against the cloud database once, setting the
  password it prompts for.

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

**Assert distinct content, not just status codes.** That is the whole point of the
script: a status-only check passes while the site is completely broken.

### Scheduled uptime

`uptime.yml` runs the same script against the public origin once a day, with
`SMOKE_READY_TRIES=1` so it reports an outage immediately instead of waiting out a
boot. Alerting is GitHub's own notification to the repo owner, not a pager.
