#!/usr/bin/env bash
# Native install on a Linux server: the service runs as an ordinary systemd
# service and uses the machine's own Docker. Nothing is containerised, so the
# Docker socket is never mounted into anything.
#
# Run from the project root:   sudo ./deploy-server/install-native.sh
#
# What it does:
#   * creates a service user (gis) and adds it to the docker group
#   * installs the code under /opt/genome-index-service
#   * creates a virtualenv and installs the Python dependencies
#   * creates the data directory
#   * installs and starts two systemd services (admin 8888, user 8000)

set -euo pipefail

HERE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Pick up ./setup.sh's configuration if it exists, so the folders and ports are
# defined in one place. Explicit environment variables still win.
if [ -f "$HERE_ROOT/.env" ]; then
    # shellcheck disable=SC1091
    set -a; . "$HERE_ROOT/.env"; set +a
fi

PREFIX="${PREFIX:-/opt/genome-index-service}"
DATA_DIR="${DATA_DIR:-${GIS_DATA_DIR:-/srv/genome-index-service/data}}"
SERVICE_USER="${SERVICE_USER:-gis}"
ADMIN_PORT="${ADMIN_PORT:-${GIS_ADMIN_PORT:-8888}}"
USER_PORT="${USER_PORT:-${GIS_USER_PORT:-8000}}"
ADMIN_BIND_CFG="${GIS_ADMIN_BIND:-127.0.0.1}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with sudo." >&2
  exit 1
fi

HERE="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -d "$HERE/app" ]; then
  echo "Run this from the project root (app/ was not found next to $HERE)." >&2
  exit 1
fi

echo "==> Checking prerequisites"
command -v docker >/dev/null || { echo "Docker is not installed." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is not installed." >&2; exit 1; }
docker info >/dev/null 2>&1 || echo "    Warning: 'docker info' failed; is the daemon running?"

echo "==> Service user: $SERVICE_USER"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
if getent group docker >/dev/null; then
  usermod -aG docker "$SERVICE_USER"
else
  echo "    Warning: no 'docker' group; $SERVICE_USER may not reach the daemon."
fi

echo "==> Installing code into $PREFIX"
mkdir -p "$PREFIX"
cp -r "$HERE/app" "$PREFIX/"
rm -rf "$PREFIX/app/__pycache__"
cp -r "$HERE/tools" "$PREFIX/seed-tools"

echo "==> Python virtualenv"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
"$PREFIX/venv/bin/pip" install --quiet -r "$PREFIX/app/requirements.txt"

echo "==> Data directory: $DATA_DIR"
mkdir -p "$DATA_DIR"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR" "$PREFIX"

echo "==> systemd units"
for role in admin user; do
  if [ "$role" = "admin" ]; then port="$ADMIN_PORT"; bind="$ADMIN_BIND_CFG";
  else port="$USER_PORT"; bind="0.0.0.0"; fi
  cat > "/etc/systemd/system/genome-index-$role.service" <<UNIT
[Unit]
Description=Genome Index Service ($role interface)
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
SupplementaryGroups=docker
WorkingDirectory=$PREFIX/app
Environment=APP_ROLE=$role
Environment=APP_PORT=$port
Environment=DATA_DIR=$DATA_DIR
Environment=SEED_TOOLS_DIR=$PREFIX/seed-tools
Environment=DOCKER_HOST=unix:///var/run/docker.sock
# Tool containers run as root; keep what they write group/other writable so the
# data directory stays manageable from a normal account.
UMask=0000
ExecStart=$PREFIX/venv/bin/waitress-serve --host=$bind --port=$port --threads=8 main:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
done

systemctl daemon-reload
systemctl enable --now genome-index-admin.service genome-index-user.service

echo
echo "==> Done."
echo "    user interface : http://<server>:$USER_PORT"
echo "    admin interface: http://127.0.0.1:$ADMIN_PORT  (localhost only)"
echo
echo "    status : systemctl status genome-index-user genome-index-admin"
echo "    logs   : journalctl -u genome-index-user -f"
echo "    data   : $DATA_DIR"
echo
echo "    The admin interface is bound to localhost on purpose. Reach it with"
echo "    an SSH tunnel:  ssh -L $ADMIN_PORT:127.0.0.1:$ADMIN_PORT <server>"
