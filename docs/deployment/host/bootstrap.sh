#!/usr/bin/env bash
# bootstrap.sh — build this host's service framework on a fresh cloud VPS.
#
# Run it as root from this directory (a checkout or scp of docs/deployment/host):
#
#   sudo ./bootstrap.sh --admin shedrack --admin-key /root/shedrack.pub \
#        --manifests /root/manifests
#
# It installs the framework, not the services. A service is added afterwards by
# dropping its one manifest into /etc/deploy-service/ and running
# `system provision <service>`; --manifests does exactly that for a directory
# of them, so a rebuilt VPS converges in one command.
#
# Idempotent: safe to re-run after pulling a newer copy of these files. It never
# overwrites /etc/caddy/sites/*.caddy (those are per-service and yours to edit)
# and never touches a service's data.
#
#   --admin <user>        create the human admin (sudo + your public key)
#   --admin-key <file>    public key for --admin
#   --manifests <dir>     install <service>.env files from here and provision each
#   --ssh-port <n>        the port ufw must keep open (default: from sshd)
#   --no-firewall         leave ufw alone
#   --force-caddyfile     overwrite /etc/caddy/Caddyfile
#   --dry-run             print what would change, change nothing
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMIN=""; ADMIN_KEY=""; MANIFESTS=""; SSH_PORT=""; FIREWALL=1; FORCE_CADDYFILE=0; DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
  --admin) ADMIN="${2:-}"; shift 2 ;;
  --admin-key) ADMIN_KEY="${2:-}"; shift 2 ;;
  --manifests) MANIFESTS="${2:-}"; shift 2 ;;
  --ssh-port) SSH_PORT="${2:-}"; shift 2 ;;
  --no-firewall) FIREWALL=0; shift ;;
  --force-caddyfile) FORCE_CADDYFILE=1; shift ;;
  --dry-run) DRY=1; shift ;;
  -h | --help) sed -n '2,30p' "$0"; exit 0 ;;
  *) printf 'unknown option: %s\n' "$1" >&2; exit 1 ;;
  esac
done

say() { printf '[bootstrap] %s\n' "$*"; }
run() { if [ "$DRY" = 1 ]; then printf '[dry-run] %s\n' "$*"; else "$@"; fi; }

[ "$(id -u)" -eq 0 ] || { say "must run as root"; exit 1; }
for f in deploy-service system "utmelab@.service" Caddyfile service.env.example; do
  [ -f "${HERE}/${f}" ] || { say "missing ${HERE}/${f}: run me from the host/ directory of a checkout"; exit 1; }
done

# ---------------------------------------------------------------------------
say "packages"
if [ "$DRY" = 0 ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  # caddy is Debian's own package on trixie (2.6.x); no third-party apt repo to
  # trust or keep pinned. curl is used by the gate's health check.
  apt-get install -y -qq caddy curl ca-certificates ufw sudo >/dev/null
fi

# ---------------------------------------------------------------------------
say "framework"
run install -m 0755 -o root -g root "${HERE}/deploy-service" /usr/local/bin/deploy-service
run install -m 0755 -o root -g root "${HERE}/system" /usr/local/bin/system
run install -m 0644 -o root -g root "${HERE}/utmelab@.service" /etc/systemd/system/utmelab@.service
run install -d -m 0755 -o root -g root /etc/deploy-service
run install -d -m 0755 -o root -g root /etc/caddy/sites
run systemctl daemon-reload

# ---------------------------------------------------------------------------
say "caddy"
if [ ! -f /etc/caddy/Caddyfile ] || [ "$FORCE_CADDYFILE" = 1 ]; then
  run install -m 0644 -o root -g root "${HERE}/Caddyfile" /etc/caddy/Caddyfile
  say "wrote /etc/caddy/Caddyfile (imports sites/*.caddy)"
else
  say "/etc/caddy/Caddyfile exists, left alone (--force-caddyfile to replace)"
  grep -q 'sites/\*\.caddy' /etc/caddy/Caddyfile \
    || say "WARNING: it does not import sites/*.caddy, so per-service sites will be inert"
fi
if [ "$DRY" = 0 ] && command -v caddy >/dev/null 2>&1; then
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null \
    || { say "caddy rejects the config; fix it before continuing"; exit 1; }
  systemctl enable --now caddy >/dev/null 2>&1 || true
fi

# ---------------------------------------------------------------------------
# Site files a service's own repo carries (docs/deployment/sites/*.caddy).
# Installed only when absent: once a site file exists it belongs to the
# operator, and `system provision` will not rewrite it either.
shopt -s nullglob
SITE_FILES=("${HERE}"/sites/*.caddy)
shopt -u nullglob
if [ "${#SITE_FILES[@]}" -gt 0 ]; then
  say "site files"
  for f in "${SITE_FILES[@]}"; do
    dest="/etc/caddy/sites/$(basename "$f")"
    if [ -f "$dest" ]; then
      say "  exists, left alone: $dest"
    else
      run install -m 0644 -o root -g root "$f" "$dest"
      say "  installed: $dest"
    fi
  done
  if [ "$DRY" = 0 ] && command -v caddy >/dev/null 2>&1; then
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null \
      && systemctl reload caddy >/dev/null 2>&1 || true
  fi
fi

# ---------------------------------------------------------------------------
say "admin identity"
if [ -n "$ADMIN" ]; then
  if ! id "$ADMIN" >/dev/null 2>&1; then
    run useradd --create-home --shell /bin/bash --groups sudo "$ADMIN"
    say "created $ADMIN (sudo group)"
  fi
  if [ -n "$ADMIN_KEY" ]; then
    [ -f "$ADMIN_KEY" ] || { say "no such key: $ADMIN_KEY"; exit 1; }
    if [ "$DRY" = 0 ]; then
      install -d -m 0700 -o "$ADMIN" -g "$ADMIN" "/home/${ADMIN}/.ssh"
      grep -qF "$(awk '{print $2}' "$ADMIN_KEY")" "/home/${ADMIN}/.ssh/authorized_keys" 2>/dev/null \
        || cat "$ADMIN_KEY" >>"/home/${ADMIN}/.ssh/authorized_keys"
      chmod 0600 "/home/${ADMIN}/.ssh/authorized_keys"
      chown "$ADMIN:$ADMIN" "/home/${ADMIN}/.ssh/authorized_keys"
    fi
    say "installed the admin key for $ADMIN"
  else
    say "no --admin-key: $ADMIN has sudo but no key yet"
  fi
else
  say "no --admin: skipping (root access is enough to run this)"
fi

# ---------------------------------------------------------------------------
if [ "$FIREWALL" = 1 ]; then
  say "firewall"
  [ -n "$SSH_PORT" ] || SSH_PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')"
  SSH_PORT="${SSH_PORT:-22}"
  if [ "$DRY" = 0 ]; then
    ufw --force reset >/dev/null 2>&1 || true
    ufw default deny incoming >/dev/null
    ufw default allow outgoing >/dev/null
    ufw allow "${SSH_PORT}/tcp" >/dev/null   # keep the way in open, first
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
    ufw --force enable >/dev/null
  else
    printf '[dry-run] ufw: deny incoming, allow outgoing, allow %s/80/443\n' "$SSH_PORT"
  fi
  say "ufw: incoming denied except ${SSH_PORT}, 80, 443"
else
  say "firewall: skipped (--no-firewall)"
fi

# ---------------------------------------------------------------------------
if [ -n "$MANIFESTS" ]; then
  [ -d "$MANIFESTS" ] || { say "no such directory: $MANIFESTS"; exit 1; }
  say "services from ${MANIFESTS}"
  shopt -s nullglob
  for m in "$MANIFESTS"/*.env; do
    svc="$(basename "$m" .env)"
    run install -m 0600 -o root -g root "$m" "/etc/deploy-service/${svc}.env"
    say "installed manifest: $svc"
    [ "$DRY" = 0 ] && /usr/local/bin/system provision "$svc"
  done
  shopt -u nullglob
else
  say "no --manifests: no services provisioned yet"
fi

# ---------------------------------------------------------------------------
say "done"
cat <<'NEXT'

Next, for each service:
  1. hand CI its key:   sudo system enroll <service> <it>.pub
                        then set VPS_USER=deploy-<service> and VPS_SSH_KEY in that
                        repo's GitHub secrets
  2. stage a release and activate it (its normal pipeline)
  3. confirm the contract: sudo system verify
  4. root posture:         sudo system root status

NEXT
