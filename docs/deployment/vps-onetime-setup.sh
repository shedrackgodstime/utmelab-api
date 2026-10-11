#!/usr/bin/env bash
# One-time VPS setup for utmelab-api. IDEMPOTENT — safe to re-run.
# Run as a sudoer (e.g. shedrack) from the repo root:  bash docs/deployment/vps-onetime-setup.sh
#
# Does NOT start the service — the first `git push` (deploy workflow) does that,
# because there is no release until then. After this: push, done.
#
# Prereqs (already true on this host from the parent UTME-Lab deploy):
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
ss -lntp | grep -q ":${PORT} " && { echo "  port ${PORT} already in use — pick another"; exit 1; } || echo "  port ${PORT}: free"

say "1. Directories (parent layout under /opt/apps/${APP})"
# /opt/apps/<app>         root:deploy 0755  — parents traversable by all (o+rx)
install -d -o root   -g deploy -m 0755 "/opt/apps/${APP}"
# releases/               deploy:deploy 0775 — CI (as deploy) writes here
install -d -o deploy -g deploy -m 0775 "/opt/apps/${APP}/releases"
# /var/lib/<app>          utmelab:utmelab 0750 — the ONLY writable path for the service
install -d -o utmelab -g utmelab -m 0750 "/var/lib/${APP}"
echo "  /opt/apps/${APP}{,/releases}  /var/lib/${APP} ready"

say "2. Secrets — /etc/${APP}/environment (root:utmelab 0640)"
# Never put the token in this script or the repo. Placeholder; you fill it once.
if [ ! -f "/etc/${APP}/environment" ]; then
  cat > "/etc/${APP}/environment" <<EOF
UTMELAB_API_BIND=127.0.0.1:${PORT}
UTMELAB_API_DATA_DIR=/opt/apps/${APP}/current/data
UTMELAB_API_KEYS_FILE=/var/lib/${APP}/api_keys.json
UTMELAB_API_REPORTS_FILE=/var/lib/${APP}/reports.json
TURSO_DB_URL=turso://utmelab-api-ultimatekristency.aws-eu-west-1.turso.io
TURSO_DB_TOKEN=REPLACE_WITH_WRITE_TOKEN
KEY_CACHE_TTL_SECS=30
EOF
fi
chown root:utmelab "/etc/${APP}/environment"
chmod 0640 "/etc/${APP}/environment"
echo "  edit /etc/${APP}/environment and set TURSO_DB_TOKEN (rw token — server only)"

say "3. Deploy gate — /usr/local/bin/${APP}-deploy (root:root 0755)"
install -o root -g root -m 0755 "${REPO}/utmelab-api-deploy" "/usr/local/bin/${APP}-deploy"
echo "  installed (the only privileged code; validates + symlinks + health-checks)"

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
caddy validate && systemctl reload caddy
echo "  api.utmelab.com -> proxies /api/*,/health,/openapi.json to 127.0.0.1:${PORT}; serves static docs"

say "DONE — now: git push (workflow builds+ships+activates), then:"
cat <<EOF
  systemctl status ${APP}
  journalctl -u ${APP} -n 50
  curl -s http://127.0.0.1:${PORT}/health
  curl -sI https://api.utmelab.com/health      # after DNS propagates + cert issues
  systemd-analyze security ${APP} | grep Overall
EOF
