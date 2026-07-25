#!/usr/bin/env bash
# Remove the native install. The data directory is left alone.
set -euo pipefail
PREFIX="${PREFIX:-/opt/genome-index-service}"
if [ "$(id -u)" -ne 0 ]; then echo "Run this with sudo." >&2; exit 1; fi
systemctl disable --now genome-index-admin.service genome-index-user.service 2>/dev/null || true
rm -f /etc/systemd/system/genome-index-admin.service /etc/systemd/system/genome-index-user.service
systemctl daemon-reload
rm -rf "$PREFIX"
echo "Removed. The data directory was left in place."
