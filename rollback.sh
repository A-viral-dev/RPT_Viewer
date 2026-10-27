#!/bin/bash

set -e
set -o pipefail

log() {
  echo ""
  echo "========== $1 =========="
}

APP_NAME="rpt_viewer"
APP_DIR="/opt/$APP_NAME"
APP_USER="rptuser"

log "STARTING ROLLBACK"

# -------------------------------
# STOP & REMOVE SYSTEMD SERVICE
# -------------------------------
log "Stopping service"

systemctl stop $APP_NAME || true
systemctl disable $APP_NAME || true

log "Removing systemd service file"
rm -f /etc/systemd/system/${APP_NAME}.service

systemctl daemon-reload

# -------------------------------
# REMOVE NGINX CONFIG
# -------------------------------
log "Removing Nginx config"

rm -f /etc/nginx/sites-enabled/$APP_NAME
rm -f /etc/nginx/sites-available/$APP_NAME

# Remove auth file
rm -f /etc/nginx/.rpt_htpasswd

# Remove SSL certs
rm -rf /etc/nginx/ssl

# Restore default nginx site (optional safety)
if [ -f /etc/nginx/sites-available/default ]; then
  ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
fi

nginx -t || true
systemctl restart nginx || true

# -------------------------------
# REMOVE APPLICATION FILES
# -------------------------------
log "Removing application directory"

rm -rf $APP_DIR

# -------------------------------
# REMOVE USER
# -------------------------------
log "Removing app user"

id -u $APP_USER &>/dev/null && userdel -r $APP_USER || true

# -------------------------------
# FINAL CHECK
# -------------------------------
log "Final checks"
systemctl stop nginx
systemctl disable nginx

echo "Listening ports:"
ss -tulnp | grep -E "8080|443|80" || echo "No relevant ports open"

log "ROLLBACK COMPLETE"

echo ""
echo "======================================"
echo "✅ ROLLBACK DONE"
echo "======================================"
echo ""
echo "System packages (nginx, python, etc.) are NOT removed."
echo ""
echo "If you still see app on IP:8080:"
echo "→ check: ps aux | grep python"
echo "→ kill manually if needed"
