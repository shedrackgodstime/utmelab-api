#!/usr/bin/env bash
# One-time VPS setup for utmelab-api. IDEMPOTENT - safe to re-run.
# Run as a sudoer (e.g. shedrack) from the repo root:
#   bash docs/deployment/vps-onetime-setup.sh
#
# Does NOT start the service - the first deploy (Actions -> deploy-api ->
# Run workflow) does that, because there is no release until then.
#
# Re-run this after pulling a change to any of the three installed copies:
#   /usr/local/bin/utmelab-api-deploy
#   /etc/systemd/system/utmelab-api.service
#   /etc/caddy/Caddyfile.api
# A repo edit does not touch the host until you re-run it. This matters here
# because the host was provisioned for the previous service, whose environment
# file uses variable names this binary does not read (UTMELAB_API_BIND and
# friends); the unit, gate and Caddy site all had to change with it.
#
# Prereqs:
#   - Caddy installed, running
#   - users `deploy` (SSH key, gate-only sudo) and `utmelab` (system, nologin) exist
#   - UFW allows 22022/80/443, denies 8081 (only Caddy proxies it)
#   - DNS api.utmelab.com -> this host  (A record; set in your DNS provider)
set -euo pipefail

APP=utmelab-api
REPO=docs/deployment
PORT=8081

say() { printf '\n=== %s ===\n' "$*"; }

say "0. Verify prerequisites"
id deploy   >/dev/null && echo "  user deploy: ok"   || { echo "  MISSING deploy user"; exit 1; }
id utmelab  >/dev/null && echo "  user utmelab: ok"  || { echo "  MISSING utmelab user"; exit 1; }
systemctl is-active --quiet caddy && echo "  caddy: active" || { echo "  caddy not active"; exit 1; }
if ss -lntp 2>/dev/null | grep -q ":${PORT} "; then
  echo "  WARNING port ${PORT} is already listening. Fine if it is a running ${APP}"
  echo "          (this script is safe to re-run on a live host); a problem otherwise."
else
  echo "  port ${PORT}: free"
fi

# DNS gates the TLS half of step 6. Caddy will not reload a site it cannot issue
# a certificate for, so check now rather than after step 6 has half-applied.
if getent hosts api.utmelab.com >/dev/null 2>&1; then
  echo "  api.utmelab.com: resolves ($(getent hosts api.utmelab.com | head -1 | awk '{print $1}'))"
else
  echo "  WARNING api.utmelab.com does NOT resolve. Add the A record -> this host"
  echo "          before step 6, or Caddy cannot obtain a certificate."
fi

say "1. Directories (parent layout under /opt/apps/${APP})"
# /opt/apps/<app>         root:deploy 0755  — parents traversable by all (o+rx)
install -d -o root   -g deploy -m 0755 "/opt/apps/${APP}"
# releases/               deploy:deploy 0775 — CI (as deploy) writes here
install -d -o deploy -g deploy -m 0775 "/opt/apps/${APP}/releases"
# /var/lib/<app>          utmelab:utmelab 0750 — the ONLY writable path for the
# service, and where REPLICA_PATH must point
install -d -o utmelab -g utmelab -m 0750 "/var/lib/${APP}"
echo "  /opt/apps/${APP}{,/releases}  /var/lib/${APP} ready"

say "2. Secrets — /etc/${APP}/environment (root:utmelab 0640)"
install -d -o root -g utmelab -m 0750 "/etc/${APP}"
# Never put the token in this script or the repo. Placeholder; you fill it once.
if [ ! -f "/etc/${APP}/environment" ]; then
  cat > "/etc/${APP}/environment" <<EOF
PORT=${PORT}
WORKER_THREADS=2
# Turso is the only source; nothing is embedded and no JSON ships. The replica
# is the one thing written at runtime, and it must sit on the one writable
# path: ProtectSystem=strict makes the release dir read-only, so the default
# db/sync.db can never be written and the boot would fail.
REPLICA_PATH=/var/lib/${APP}/sync.db
SYNC_SECS=10
RATE_LIMIT_PER_MIN=60
COOKIE_SECURE=1
TURSO_DB_URL=turso://utmelab-api-ultimatekristency.aws-eu-west-1.turso.io
TURSO_DB_TOKEN=REPLACE_WITH_WRITE_TOKEN
EOF
fi
chown root:utmelab "/etc/${APP}/environment"
chmod 0640 "/etc/${APP}/environment"
echo "  edit /etc/${APP}/environment and set TURSO_DB_TOKEN (rw token — server only)"

say "3. Deploy gate — /usr/local/bin/${APP}-deploy (root:root 0755)"
install -o root -g root -m 0755 "${REPO}/utmelab-api-deploy" "/usr/local/bin/${APP}-deploy"
echo "  installed (the only privileged code; validates + symlinks + readiness-checks)"

say "4. Restricted sudo — deploy may run ONLY the gate"
SUDOERS="/etc/sudoers.d/${APP}-deploy"
if [ ! -f "$SUDOERS" ] || ! grep -q "${APP}-deploy" "$SUDOERS"; then
  echo "deploy ALL=(root) NOPASSWD: /usr/local/bin/${APP}-deploy" > "$SUDOERS"
fi
chown root:root "$SUDOERS"; chmod 0440 "$SUDOERS"
visudo -c | tail -n1
echo "  verify: sudo -l -U deploy   (should list only the gate)"

say "5. systemd service — /etc/systemd/system/${APP}.service (root:root 0644)"
install -o root -g root -m 0644 "${REPO}/utmelab-api.service" "/etc/systemd/system/${APP}.service"
systemctl daemon-reload
systemctl enable "${APP}"    # enabled, NOT started — first deploy starts it
echo "  enabled (inactive until the first release lands)"

say "6. Caddy site — api.utmelab.com"
install -o root -g root -m 0644 "${REPO}/Caddyfile.api" "/etc/caddy/Caddyfile.api"
if ! grep -q "Caddyfile.api" /etc/caddy/Caddyfile; then
  printf '\nimport /etc/caddy/Caddyfile.api\n' >> /etc/caddy/Caddyfile
fi
# --adapter caddyfile is required: a bare `caddy validate` parses the main file
# as JSON and aborts the reload with "unexpected end of JSON input".
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && systemctl reload caddy
echo "  api.utmelab.com -> proxies /api/*,/health,/ready to 127.0.0.1:${PORT};"
echo "                     serves the static site + /openapi.json from current/site"

say "DONE — nothing is live yet. Set the real TURSO_DB_TOKEN above, then trigger"
say "     a deploy: Actions -> deploy-api -> Run workflow. It builds, ships and"
say "     readiness-checks; then:"
cat <<EOF
  systemctl status ${APP}
  journalctl -u ${APP} -n 50
  curl -s http://127.0.0.1:${PORT}/ready
  curl -s https://api.utmelab.com/ready        # after DNS propagates + cert issues
  curl -s https://api.utmelab.com/openapi.json | head -c 200
  systemd-analyze security ${APP} | grep Overall
EOF
