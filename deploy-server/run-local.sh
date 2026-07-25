#!/usr/bin/env bash
# Run the service WITHOUT Docker-in-Docker, right here, without installing
# anything system-wide. No root, no systemd, no containers for the web service
# itself: it uses this machine's Docker to build the tool images and run the
# indexing containers.
#
#   ./deploy-server/run-local.sh
#
# Both interfaces start in the foreground; press Ctrl-C to stop them.
# Use install-native.sh instead when you want it to run as a proper service.
#
# Requirements: Docker running and usable by your account, plus Python 3.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# Pick up the configuration written by ./setup.sh, so the mode, folders and ports
# are defined in exactly one place. Anything already in the environment wins.
if [ -f "$ROOT/.env" ]; then
    # shellcheck disable=SC1091
    set -a; . "$ROOT/.env"; set +a
fi
DATA_DIR="${DATA_DIR:-${GIS_DATA_DIR:-$ROOT/data}}"
ADMIN_PORT="${ADMIN_PORT:-${GIS_ADMIN_PORT:-8888}}"
USER_PORT="${USER_PORT:-${GIS_USER_PORT:-8000}}"
ADMIN_BIND="${ADMIN_BIND:-${GIS_ADMIN_BIND:-127.0.0.1}}"
USER_BIND="${USER_BIND:-${GIS_USER_BIND:-0.0.0.0}}"
VENV="${VENV:-$ROOT/.venv-server}"

echo "=== Genome Index Service (plain, no Docker-in-Docker) ==="
echo

command -v python3 >/dev/null || { echo "python3 is not installed." >&2; exit 1; }
command -v docker  >/dev/null || { echo "Docker is not installed." >&2; exit 1; }

if ! docker info >/dev/null 2>&1; then
    echo "Cannot talk to Docker as $(id -un)." >&2
    echo "Is the daemon running, and is your account in the 'docker' group?" >&2
    echo "  sudo usermod -aG docker $(id -un)   # then log out and back in" >&2
    exit 1
fi

if [ ! -d "$VENV" ]; then
    echo "--> Creating a virtualenv in $VENV"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$ROOT/app/requirements.txt"
else
    echo "--> Reusing the virtualenv in $VENV"
fi

mkdir -p "$DATA_DIR"

# Tool containers run as root, so keep what they write under the data directory
# deletable by this account.
umask 000

export DATA_DIR
export SEED_TOOLS_DIR="${SEED_TOOLS_DIR:-$ROOT/tools}"
export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"
export HOST_UID="${HOST_UID:-$(id -u)}"
export HOST_GID="${HOST_GID:-$(id -g)}"

echo "--> data:   $DATA_DIR"
echo "--> docker: $DOCKER_HOST"
echo
echo "    user interface : http://localhost:$USER_PORT"
echo "    admin interface: http://$ADMIN_BIND:$ADMIN_PORT"
echo
echo "    Ctrl-C to stop."
echo

cd "$ROOT/app"

cleanup() {
    echo
    echo "--> Stopping."
    kill "${ADMIN_PID:-}" "${USER_PID:-}" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup INT TERM

APP_ROLE=admin APP_PORT="$ADMIN_PORT" \
    "$VENV/bin/waitress-serve" --host="$ADMIN_BIND" --port="$ADMIN_PORT" --threads=8 main:app &
ADMIN_PID=$!

APP_ROLE=user APP_PORT="$USER_PORT" \
    "$VENV/bin/waitress-serve" --host="$USER_BIND" --port="$USER_PORT" --threads=8 main:app &
USER_PID=$!

wait -n "$ADMIN_PID" "$USER_PID" 2>/dev/null || wait "$ADMIN_PID" "$USER_PID" 2>/dev/null || true
cleanup
