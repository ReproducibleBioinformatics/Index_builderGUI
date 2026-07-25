#!/usr/bin/env bash
# Genome Index Service - setup.
#
# Asks which of the three modes you want and where the data should live, then
# writes a single .env that every mode reads. After this, use ./gis.sh to start,
# stop and inspect the service without having to remember which mode you chose.
#
#   ./setup.sh                 interactive
#   ./setup.sh --show          print the current configuration
#   ./setup.sh --mode socket --data /srv/gis/data --user-port 8000 --yes
#
# Modes:
#   dind    one privileged container carrying its own Docker (laptop, demo)
#   socket  a normal container using the host's Docker (recommended on a server)
#   native  a plain process on the machine, no container for the service

set -euo pipefail
cd "$(dirname "$0")"
ENV_FILE=".env"

MODE=""; DATA=""; USER_PORT=""; ADMIN_PORT=""; THREADS=""
ADMIN_BIND=""; ASSUME_YES=0; SHOW=0

while [ $# -gt 0 ]; do
    case "$1" in
        --mode) MODE="${2:-}"; shift 2 ;;
        --data) DATA="${2:-}"; shift 2 ;;
        --user-port) USER_PORT="${2:-}"; shift 2 ;;
        --admin-port) ADMIN_PORT="${2:-}"; shift 2 ;;
        --admin-bind) ADMIN_BIND="${2:-}"; shift 2 ;;
        --threads) THREADS="${2:-}"; shift 2 ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --show) SHOW=1; shift ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ "$SHOW" = "1" ]; then
    if [ -f "$ENV_FILE" ]; then
        echo "Current configuration ($ENV_FILE):"; echo
        grep -vE '^\s*(#|$)' "$ENV_FILE" | sed 's/^/  /'
    else
        echo "No $ENV_FILE yet. Run ./setup.sh to create one."
    fi
    exit 0
fi

ask() {  # ask <prompt> <default> ; echoes the answer
    local prompt="$1" default="$2" reply=""
    if [ "$ASSUME_YES" = "1" ]; then echo "$default"; return; fi
    printf "%s [%s]: " "$prompt" "$default" > /dev/tty
    read -r reply < /dev/tty || reply=""
    echo "${reply:-$default}"
}

echo "=============================================="
echo " Genome Index Service - setup"
echo "=============================================="
echo

command -v docker >/dev/null || { echo "Docker is not installed. Install it first." >&2; exit 1; }
if ! docker info >/dev/null 2>&1; then
    echo "Warning: 'docker info' failed. Is the daemon running, and can your"
    echo "         account reach it? Setup will continue, but nothing will start"
    echo "         until Docker works."
    echo
fi

# ---------------------------------------------------------------- mode --------
if [ -z "$MODE" ]; then
    cat <<'MENU'
How should the service run?

  1) dind    - one privileged container that carries its own Docker.
               Needs only Docker. Works on Windows. Tool images are rebuilt
               after a restart. Good for a laptop or a demo.

  2) socket  - a normal container that uses this machine's Docker to run the
               tool containers beside it. Not privileged, tool images stay
               cached, no nested networking. Recommended on a server.
               Note: it mounts the Docker socket, which gives that container
               root-equivalent control of Docker on this machine.

  3) native  - a plain process on this machine (no container for the service).
               Needs Python 3. No container ever receives the Docker socket.

MENU
    choice="$(ask "Choose 1, 2 or 3" "1")"
    case "$choice" in
        1|dind) MODE="dind" ;;
        2|socket) MODE="socket" ;;
        3|native) MODE="native" ;;
        *) echo "Not a valid choice: $choice" >&2; exit 1 ;;
    esac
    echo
fi

case "$MODE" in
    dind|socket|native) ;;
    *) echo "Unknown mode: $MODE (use dind, socket or native)" >&2; exit 1 ;;
esac

# --------------------------------------------------------- mode checks --------
if [ "$MODE" = "native" ]; then
    command -v python3 >/dev/null || {
        echo "Mode 'native' needs Python 3, which was not found." >&2; exit 1; }
fi

if [ "$MODE" = "socket" ] && [ "$ASSUME_YES" != "1" ]; then
    echo "Mode 'socket' mounts /var/run/docker.sock into the service container."
    echo "That gives it control of Docker on this machine, which is effectively"
    echo "root here. Use mode 3 (native) if that is not acceptable."
    confirm="$(ask "Continue with socket mode? (yes/no)" "yes")"
    case "$confirm" in
        y|yes|Y|YES) ;;
        *) echo "Aborted."; exit 1 ;;
    esac
    echo
fi

# --------------------------------------------------------------- paths --------
case "$MODE" in
    dind)   DEFAULT_DATA="./data" ;;
    socket) DEFAULT_DATA="/srv/genome-index-service/data" ;;
    native) DEFAULT_DATA="$(pwd)/data" ;;
esac
[ -n "$DATA" ] || DATA="$(ask "Where should genomes and indexes be stored?" "$DEFAULT_DATA")"

# socket mode needs an absolute path: the host daemon resolves it directly
case "$MODE:$DATA" in
    socket:/*) ;;
    socket:*) echo "In socket mode the data path must be absolute (got '$DATA')." >&2; exit 1 ;;
esac

[ -n "$USER_PORT" ]  || USER_PORT="$(ask "Port for the user interface" "8000")"
[ -n "$ADMIN_PORT" ] || ADMIN_PORT="$(ask "Port for the admin interface" "8888")"
[ -n "$ADMIN_BIND" ] || ADMIN_BIND="$(ask "Address for the admin interface (127.0.0.1 keeps it local)" "127.0.0.1")"
[ -n "$THREADS" ]    || THREADS="$(ask "Default CPU threads for indexing" "4")"

for p in "$USER_PORT" "$ADMIN_PORT"; do
    case "$p" in (*[!0-9]*|"") echo "Not a port number: $p" >&2; exit 1 ;; esac
done
[ "$USER_PORT" != "$ADMIN_PORT" ] || { echo "The two ports must differ." >&2; exit 1; }

# ------------------------------------------------------------ ownership -------
OWN_UID=""; OWN_GID=""
if [ "$(uname -s)" != "Darwin" ] && [ "$MODE" != "dind" ]; then
    OWN_UID="$(id -u)"; OWN_GID="$(id -g)"
fi

# ---------------------------------------------------------------- write -------
if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$ENV_FILE.bak"
    echo "(kept a copy of the previous configuration in $ENV_FILE.bak)"
fi

cat > "$ENV_FILE" <<EOF
# Genome Index Service configuration - written by ./setup.sh
# Every mode reads this file. Re-run ./setup.sh to change it, or edit by hand.

# dind | socket | native   (see ./setup.sh --help)
GIS_MODE=$MODE

# Where genomes, indexes, tools, requests and job logs are stored.
GIS_DATA_DIR=$DATA

# Interfaces. The admin one has no login, so it is bound locally by default.
GIS_USER_PORT=$USER_PORT
GIS_ADMIN_PORT=$ADMIN_PORT
GIS_ADMIN_BIND=$ADMIN_BIND
GIS_USER_BIND=0.0.0.0

# Fallback thread count when a tool declares no "threads" parameter.
INDEX_THREADS=$THREADS

# Preferred DNA FASTA flavour, in order.
DNA_PREFERENCE=primary_assembly,toplevel

# Own the data files as this user instead of root (Linux; leave empty to skip).
HOST_UID=$OWN_UID
HOST_GID=$OWN_GID
EOF

mkdir -p "$DATA" 2>/dev/null || {
    echo
    echo "Could not create $DATA. Create it yourself, for example:"
    echo "    sudo mkdir -p '$DATA' && sudo chown $(id -un) '$DATA'"
}

echo
echo "=============================================="
echo " Configured: mode '$MODE'"
echo "=============================================="
echo "  data directory : $DATA"
echo "  user interface : http://localhost:$USER_PORT"
echo "  admin interface: http://$ADMIN_BIND:$ADMIN_PORT"
echo "  written to     : $ENV_FILE"
echo
echo "Next:"
echo "    ./gis.sh start        # build if needed, then start"
echo "    ./gis.sh status"
echo "    ./gis.sh logs"
echo "    ./gis.sh stop"
echo
if [ "$ADMIN_BIND" = "127.0.0.1" ] && [ "$MODE" != "dind" ]; then
    echo "The admin interface is local only. From your workstation:"
    echo "    ssh -L $ADMIN_PORT:127.0.0.1:$ADMIN_PORT <this-server>"
    echo
fi
