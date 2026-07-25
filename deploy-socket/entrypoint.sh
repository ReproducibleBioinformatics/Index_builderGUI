#!/bin/sh
# Sibling-containers entrypoint: just the two web interfaces.
# No inner Docker daemon and no DNS forwarder: the host's Docker already has
# working networking, and it caches the images it builds.
set -eu

# Tool containers run as root, so keep what they write under the data directory
# deletable from the host.
umask 000

ADMIN_PORT="${ADMIN_PORT:-8888}"
USER_PORT="${USER_PORT:-8000}"
DATA_DIR="${DATA_DIR:?DATA_DIR must be set}"
DATA_HOST_BIND="${DATA_HOST_BIND:-$DATA_DIR}"

if [ ! -S /var/run/docker.sock ]; then
    echo "[gis] ERROR: /var/run/docker.sock is not present."
    echo "[gis] This deployment needs the host Docker socket mounted in."
    exit 1
fi

# DATA_DIR is this container's own view of the data directory (a normal bind,
# always /workspace/data). DATA_HOST_BIND is the path the daemon - which lives
# OUTSIDE this container - needs in order to bind that same directory into a
# tool container it spawns on the service's behalf; app/docker_ops.py passes it
# as the mount source. The two only need to be equal when the daemon happens to
# share this container's filesystem view (Linux/macOS "same absolute path"
# convention); on Docker Desktop for Windows, DATA_HOST_BIND is the //<drive>/...
# form instead. See deploy-socket/README.md.
if [ ! -d "$DATA_DIR" ]; then
    echo "[gis] ERROR: DATA_DIR ($DATA_DIR) does not exist inside the container."
    echo "[gis] Check the data-directory bind mount in the compose file."
    exit 1
fi

cd /app

echo "[gis] admin GUI on :$ADMIN_PORT, user GUI on :$USER_PORT"
echo "[gis] docker host: ${DOCKER_HOST:-unix:///var/run/docker.sock} (host daemon, siblings)"
echo "[gis] data dir:    $DATA_DIR  (sibling-container mount source: $DATA_HOST_BIND)"

APP_ROLE=admin APP_PORT="$ADMIN_PORT" \
    waitress-serve --host=0.0.0.0 --port="$ADMIN_PORT" --threads=8 main:app &
ADMIN_PID=$!

APP_ROLE=user APP_PORT="$USER_PORT" \
    waitress-serve --host=0.0.0.0 --port="$USER_PORT" --threads=8 main:app &
USER_PID=$!

while kill -0 "$ADMIN_PID" 2>/dev/null && kill -0 "$USER_PID" 2>/dev/null; do
    sleep 3
done

echo "[gis] a web process exited; shutting the container down."
kill "$ADMIN_PID" "$USER_PID" 2>/dev/null || true
exit 1
