#!/bin/bash

set -e
set -o pipefail

log() {
  echo ""
  echo "========== $1 =========="
}

APP_NAME="rpt_viewer"
APP_DIR="/opt/$APP_NAME"
ZIP_FILE="/home/ubuntu/rpt_viewer.zip"

APP_USER="rptuser"

# Basic-auth credentials are supplied by the operator; never commit them.
BASIC_USER="${BASIC_USER:?export BASIC_USER before deploying}"
BASIC_PASS="${BASIC_PASS:?export BASIC_PASS before deploying}"

SSH_PORT=2222

log "STARTING DEPLOYMENT"

# -------------------------------
# SYSTEM UPDATE
# -------------------------------
log "Updating system"
apt update -y
apt install -y nginx apache2-utils curl unzip python3-pip openssl fail2ban ufw

# -------------------------------
# APP USER
# -------------------------------
log "Creating app user"
id -u $APP_USER &>/dev/null || adduser --disabled-password --gecos "" $APP_USER

mkdir -p $APP_DIR
chown -R $APP_USER:$APP_USER $APP_DIR

# -------------------------------
# APP SETUP
# -------------------------------
log "Deploying app"

ls -l "$ZIP_FILE" || { echo "❌ ZIP NOT FOUND"; exit 1; }

unzip -o "$ZIP_FILE" -d "$APP_DIR"

# Flatten directory if needed
INNER_DIR=$(find $APP_DIR -mindepth 1 -maxdepth 1 -type d | head -n 1)
if [ -n "$INNER_DIR" ]; then
  echo "Flattening $INNER_DIR"
  mv $INNER_DIR/* $APP_DIR/ || true
  rm -rf $INNER_DIR
fi

log "Final app files"
ls -l $APP_DIR

# -------------------------------
# 🔧 FIX NICEGUI ui.run
# -------------------------------
log "Fixing NiceGUI ui.run configuration"

TARGET_LINE="ui.run(title='Finacle RPT Pro', reload=False, port=8080, host='0.0.0.0', show=False)"

if grep -q "ui.run" "$APP_DIR/main.py"; then
  echo "Found ui.run → updating"

  cp "$APP_DIR/main.py" "$APP_DIR/main.py.bak"

  sed -i "s|ui.run(.*)|$TARGET_LINE|g" "$APP_DIR/main.py"

  echo "Updated line:"
  grep "ui.run" "$APP_DIR/main.py"
else
  echo "⚠️ ui.run not found"
fi

# -------------------------------
# START SCRIPT
# -------------------------------
log "Creating start script"

cat << 'EOF' > $APP_DIR/start.sh
#!/bin/bash

echo "=== START.SH RUNNING ==="

cd /opt/rpt_viewer || exit 1

export PATH=$PATH:/root/.local/bin:/usr/local/bin:/usr/bin

echo "Installing dependencies via uv"
uv sync

echo "Starting app"
uv run python main.py
EOF

chmod +x $APP_DIR/start.sh
chown -R $APP_USER:$APP_USER $APP_DIR

# -------------------------------
# SYSTEMD
# -------------------------------
log "Creating systemd service"

cat << EOF > /etc/systemd/system/rpt_viewer.service
[Unit]
Description=Finacle RPT Viewer
After=network.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=/bin/bash $APP_DIR/start.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reexec
systemctl daemon-reload
systemctl enable rpt_viewer
systemctl restart rpt_viewer

sleep 3
systemctl status rpt_viewer --no-pager || true

# -------------------------------
# BASIC AUTH
# -------------------------------
log "Setting Basic Auth"
htpasswd -bc /etc/nginx/.rpt_htpasswd $BASIC_USER $BASIC_PASS

# -------------------------------
# SSL
# -------------------------------
log "Generating SSL"
mkdir -p /etc/nginx/ssl

openssl req -x509 -nodes -days 365 \
-newkey rsa:2048 \
-keyout /etc/nginx/ssl/rpt_viewer.key \
-out /etc/nginx/ssl/rpt_viewer.crt \
-subj "/C=IN/ST=State/L=City/O=RPTViewer/CN=localhost"

# -------------------------------
# NGINX
# -------------------------------
log "Configuring Nginx"

cat << 'EOF' > /etc/nginx/sites-available/rpt_viewer

server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate /etc/nginx/ssl/rpt_viewer.crt;
    ssl_certificate_key /etc/nginx/ssl/rpt_viewer.key;

    location / {
        auth_basic "Restricted";
        auth_basic_user_file /etc/nginx/.rpt_htpasswd;

        proxy_pass http://127.0.0.1:8080;
    }
}
EOF

ln -sf /etc/nginx/sites-available/rpt_viewer /etc/nginx/sites-enabled/

nginx -t
systemctl restart nginx

# -------------------------------
# FINAL CHECK
# -------------------------------
log "Checking app"

ss -tulnp | grep 8080 || echo "⚠️ If not visible, check logs"

log "DONE"

echo ""
echo "======================================"
echo "✅ DEPLOYMENT COMPLETE"
echo "======================================"
echo ""
echo "🌐 Access via:"
echo "https://<TAILSCALE-IP>"
echo ""
echo "🔐 User: $BASIC_USER"
echo "🔐 Pass: $BASIC_PASS"
echo ""
echo "Debug if needed:"
echo "journalctl -u rpt_viewer -n 50"