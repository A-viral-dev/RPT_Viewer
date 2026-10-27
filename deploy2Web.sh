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
apt install -y nginx apache2-utils curl unzip python3-pip fail2ban ufw iptables wget

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

INNER_DIR=$(find $APP_DIR -mindepth 1 -maxdepth 1 -type d | head -n 1)
if [ -n "$INNER_DIR" ]; then
  mv $INNER_DIR/* $APP_DIR/ || true
  rm -rf $INNER_DIR
fi

# -------------------------------
# FIX NICEGUI
# -------------------------------
log "Fixing NiceGUI"

TARGET_LINE="ui.run(title='Finacle RPT Pro', reload=False, port=8080, host='127.0.0.1', show=False)"

if grep -q "ui.run" "$APP_DIR/main.py"; then
  cp "$APP_DIR/main.py" "$APP_DIR/main.py.bak"
  sed -i "s|ui.run(.*)|$TARGET_LINE|g" "$APP_DIR/main.py"
fi

# -------------------------------
# START SCRIPT
# -------------------------------
log "Creating start script"

cat << 'EOF' > $APP_DIR/start.sh
#!/bin/bash
cd /opt/rpt_viewer || exit 1
export PATH=$PATH:/root/.local/bin:/usr/local/bin:/usr/bin
uv sync
uv run python main.py
EOF

chmod +x $APP_DIR/start.sh
chown -R $APP_USER:$APP_USER $APP_DIR

# -------------------------------
# SYSTEMD SERVICE
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

# -------------------------------
# BASIC AUTH (NGINX)
# -------------------------------
log "Setting Basic Auth"
htpasswd -bc /etc/nginx/.rpt_htpasswd $BASIC_USER $BASIC_PASS

# -------------------------------
# NGINX (LOCAL ONLY)
# -------------------------------
log "Configuring Nginx (local auth layer)"

cat << 'EOF' > /etc/nginx/sites-available/rpt_viewer
server {
    listen 80;
    server_name _;

    location / {
        auth_basic "Restricted";
        auth_basic_user_file /etc/nginx/.rpt_htpasswd;

        proxy_pass http://127.0.0.1:8080;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/rpt_viewer /etc/nginx/sites-enabled/

nginx -t
systemctl restart nginx

# -------------------------------
# CLOUDFLARE TUNNEL
# -------------------------------
log "Installing Cloudflare Tunnel"

ARCH=$(uname -m)

if [ "$ARCH" = "x86_64" ]; then
  FILE="cloudflared-linux-amd64.deb"
elif [ "$ARCH" = "aarch64" ]; then
  FILE="cloudflared-linux-arm64.deb"
else
  echo "❌ Unsupported architecture: $ARCH"
  exit 1
fi

wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/$FILE
dpkg -i $FILE

log "Creating Cloudflare tunnel service"

cat << 'EOF' > /etc/systemd/system/cloudflared.service
[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
ExecStart=/usr/bin/cloudflared tunnel --url http://127.0.0.1
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cloudflared
systemctl start cloudflared

# -------------------------------
# FAIL2BAN
# -------------------------------
log "Configuring Fail2ban"

systemctl enable fail2ban
systemctl start fail2ban

# -------------------------------
# FIREWALL
# -------------------------------
log "Configuring firewall"

ufw --force reset || true

update-alternatives --set iptables /usr/sbin/iptables-legacy || true
update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy || true

ufw default deny incoming || true
ufw default allow outgoing || true

ufw allow 22/tcp || true
ufw allow $SSH_PORT/tcp || true

# DO NOT expose app ports
ufw deny 8080/tcp || true

ufw --force enable || true

# -------------------------------
# FALLBACK BLOCK
# -------------------------------
log "Applying iptables fallback"

iptables -C INPUT -p tcp --dport 8080 -j DROP 2>/dev/null || \
iptables -A INPUT -p tcp --dport 8080 -j DROP

# -------------------------------
# FINAL CHECK
# -------------------------------
log "Checking services"

systemctl status rpt_viewer --no-pager || true
systemctl status cloudflared --no-pager || true

log "FETCHING PUBLIC URL"

sleep 5
journalctl -u cloudflared -n 20 --no-pager | grep -o 'https://.*trycloudflare.com' || true

echo ""
echo "======================================"
echo "✅ DEPLOYMENT COMPLETE (CLOUDFLARE)"
echo "======================================"
echo ""
echo "🌐 Public URL:"
echo "Check above (trycloudflare.com link)"
echo ""
echo "🔐 Basic Auth:"
echo "User: $BASIC_USER"
echo "Pass: $BASIC_PASS"
echo ""
echo "🔒 Security:"
echo "- No open ports (except SSH)"
echo "- App bound to localhost"
echo "- Cloudflare HTTPS"
echo "- Nginx auth layer"
echo "- Fail2ban active"
echo ""
echo "Debug:"
echo "journalctl -u cloudflared -n 50"
