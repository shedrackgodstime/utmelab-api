# Deploy note: get the API reachable at the edge

**Temporary. Delete this file once step 3 passes.**

Written 2026-10-18. Read it on any device, run the commands on the VPS, and the
API should serve. No repo checkout is required on the host for the install
commands in step 2.

## Objective

Bring `https://api.utmelab.com` fully live. The static site already works, the
API does not, and the fix is host config plus one env file. Then re-run the
deploy so the new gate proves itself.

## Where things stand

The deploy ran and the build was green. Release `v0.0.0-pre.41be2d2` is
activated on the host. The site is live, the API is unreachable:

| Live check | Now | Should be |
|---|---|---|
| `GET /` | 200 | 200 |
| `GET /health` | **502** | 200, body `ok` |
| `GET /ready` | **404** | 200 |
| `GET /api/v1/exams` | **502** | 401 (keyless) |
| `GET /openapi.json` | **502** | 200 JSON |

## Why it is broken

The host still runs the previous service's config.

1. `/etc/utmelab-api/environment` sets `UTMELAB_API_BIND=127.0.0.1:8081`. This
   binary does not read that name. It reads `PORT`, which is unset, so it
   defaults to **3100**. Caddy proxies `127.0.0.1:8081`, finds nothing, answers
   502. `systemctl is-active` says `active` because the process is up, just on
   the wrong port.
2. `REPLICA_PATH` is unset too, so the replica would resolve to `db/sync.db`
   inside the read-only release dir and could never be written.
3. `/etc/caddy/Caddyfile.api` is the old one: no `/ready` route (hence 404), and
   it proxies `/openapi.json` to the API instead of serving the committed file
   statically (hence 502).
4. `/usr/local/bin/utmelab-api-deploy` is the old gate. It polls `/health`, and
   its check is buggy: a failed curl prints `000` twice (`-w` plus `|| echo
   000`), and `!= "000"` read `000000` as healthy. The run log says
   `health OK (HTTP 000000)` while the API was down. It then pruned the previous
   release, so there is no rollback. Nothing was serving before, so nothing was
   lost.

## Step 1 - the env file (the actual fix)

Carry the two `TURSO_*` values over from the current file. Back it up first.

```bash
sudo cp /etc/utmelab-api/environment /etc/utmelab-api/environment.bak
sudo tee /etc/utmelab-api/environment >/dev/null <<'EOF'
PORT=8081
WORKER_THREADS=2
REPLICA_PATH=/var/lib/utmelab-api/sync.db
SYNC_SECS=10
RATE_LIMIT_PER_MIN=60
COOKIE_SECURE=1
TURSO_DB_URL=<existing value>
TURSO_DB_TOKEN=<existing value>
EOF
sudo chown root:utmelab /etc/utmelab-api/environment
sudo chmod 0640 /etc/utmelab-api/environment
```

## Step 2 - install the three rewritten files

Get them onto the host from this repo (`docs/deployment/`):

```bash
# from your machine, in the repo root
scp -P <ssh-port> -i <your-key> \
  docs/deployment/utmelab-api-deploy \
  docs/deployment/utmelab-api.service \
  docs/deployment/Caddyfile.api \
  <user>@<host>:/tmp/
```

```bash
# on the host
sudo install -o root -g root -m 0755 /tmp/utmelab-api-deploy  /usr/local/bin/utmelab-api-deploy
sudo install -o root -g root -m 0644 /tmp/utmelab-api.service /etc/systemd/system/utmelab-api.service
sudo install -o root -g root -m 0644 /tmp/Caddyfile.api       /etc/caddy/Caddyfile.api

sudo systemctl daemon-reload
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy
sudo systemctl restart utmelab-api
```

If the host has a checkout of this repo instead:

```bash
sudo bash docs/deployment/vps-onetime-setup.sh
```

That also re-installs the sudoers rule. Step 1 is still needed by hand either
way, because the script does not overwrite an existing env file.

## Step 3 - verify

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://api.utmelab.com/ready          # 200
curl -s https://api.utmelab.com/health                                          # ok
curl -s -o /dev/null -w '%{http_code}\n' https://api.utmelab.com/api/v1/exams   # 401
curl -s https://api.utmelab.com/openapi.json | head -c 40                        # {"openapi":...
```

If `/ready` stays 503 for more than a minute, the first full sync may not have
finished. Watch it settle:

```bash
curl -s http://127.0.0.1:8081/ready
journalctl -u utmelab-api -n 50
```

## Step 4 - re-run the deploy (proves the gate)

Actions -> deploy-api -> Run workflow. The new gate polls `/ready` and requires
an exact 200, and the smoke step checks the full public path. Expect green.

## Watch-item

The first boot has no replica: `/var/lib/utmelab-api/sync.db` does not exist, so
`/ready` stays 503 until the first pull brings the schema. Against an existing
replica that took about 2 s locally; this is a fresh full sync. If it exceeds the
gate's 30x1 s window the gate fails even though the service is fine, and simply
re-running the deploy passes.

## Still outstanding, not blocking the API

- No dashboard user exists, so `/api/internal/admin/*` and `/mcp/admin` are
  unreachable and keys cannot be managed. Once the API is up:
  `cargo run -- seed-admin <username>` against the cloud database.
- API key expiry is deferred pending billing, which also blocks a rotation grace
  period.
- No uptime check on `/ready` between deploys. `site/scripts/smoke.mjs` is
  runnable by hand or on a schedule.

## Files referenced

- `docs/deployment/utmelab-api-deploy` - the gate, now polling `/ready`
- `docs/deployment/utmelab-api.service` - the unit (bare binary, no `serve` arg)
- `docs/deployment/Caddyfile.api` - adds `/ready`, serves `/openapi.json` statically
- `docs/deployment/vps-onetime-setup.sh` - idempotent, installs all of the above
- `.env.example` - the full list of names the binary reads
