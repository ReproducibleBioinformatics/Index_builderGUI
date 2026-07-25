#!/usr/bin/env bash
# Genome Index Service - one launcher for all three modes.
#
# Reads .env (written by ./setup.sh) and does the right thing for the mode you
# chose, so you never have to remember which compose file or script applies.
#
#   ./gis.sh start      build if needed, then start
#   ./gis.sh stop
#   ./gis.sh restart
#   ./gis.sh status
#   ./gis.sh logs       follow the logs
#   ./gis.sh rebuild    force a rebuild, then start
#   ./gis.sh urls       print the interface addresses
#   ./gis.sh config     show the current configuration

set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "No .env found. Run ./setup.sh first." >&2
    exit 1
fi

# shellcheck disable=SC1091
set -a; . ./.env; set +a

MODE="${GIS_MODE:-dind}"
DATA="${GIS_DATA_DIR:-./data}"
USER_PORT="${GIS_USER_PORT:-8000}"
ADMIN_PORT="${GIS_ADMIN_PORT:-8888}"
ADMIN_BIND="${GIS_ADMIN_BIND:-127.0.0.1}"
CMD="${1:-}"

compose_file() {
    case "$MODE" in
        dind)   echo "docker-compose.yml" ;;
        socket) echo "deploy-socket/docker-compose.yml" ;;
        *)      echo "" ;;
    esac
}

urls() {
    echo "  user interface : http://localhost:$USER_PORT"
    echo "  admin interface: http://$ADMIN_BIND:$ADMIN_PORT"
}

native_units_installed() {
    [ -f /etc/systemd/system/genome-index-user.service ]
}

case "$CMD" in
start|rebuild)
    BUILD="--build"
    [ "$CMD" = "rebuild" ] && BUILD="--build --force-recreate"
    case "$MODE" in
        dind|socket)
            echo "--> Starting in '$MODE' mode (data: $DATA)"
            mkdir -p "$DATA" 2>/dev/null || true
            # shellcheck disable=SC2086
            docker compose -f "$(compose_file)" up $BUILD -d
            echo
            urls
            echo
            echo "Logs: ./gis.sh logs      Stop: ./gis.sh stop"
            ;;
        native)
            if native_units_installed; then
                echo "--> Starting the installed systemd services"
                sudo systemctl start genome-index-admin genome-index-user
                urls
            else
                echo "--> Running in the foreground (nothing is installed)."
                echo "    For a service that starts at boot, run:"
                echo "        sudo ./deploy-server/install-native.sh"
                echo
                exec ./deploy-server/run-local.sh
            fi
            ;;
    esac
    ;;

stop)
    case "$MODE" in
        dind|socket) docker compose -f "$(compose_file)" down ;;
        native)
            if native_units_installed; then
                sudo systemctl stop genome-index-admin genome-index-user
                echo "Stopped."
            else
                echo "Nothing installed; if it is running in the foreground, press Ctrl-C there."
            fi
            ;;
    esac
    ;;

restart)
    "$0" stop || true
    "$0" start
    ;;

status)
    echo "mode: $MODE"
    echo "data: $DATA"
    urls
    echo
    case "$MODE" in
        dind|socket)
            docker compose -f "$(compose_file)" ps
            ;;
        native)
            if native_units_installed; then
                systemctl --no-pager --lines=0 status genome-index-admin genome-index-user || true
            else
                pgrep -af "waitress-serve.*main:app" || echo "not running"
            fi
            ;;
    esac
    ;;

logs)
    case "$MODE" in
        dind|socket) docker compose -f "$(compose_file)" logs -f ;;
        native)
            if native_units_installed; then
                journalctl -u genome-index-user -u genome-index-admin -f
            else
                echo "Running in the foreground: the logs are in that terminal." >&2
                exit 1
            fi
            ;;
    esac
    ;;

urls)
    urls
    ;;

config)
    exec ./setup.sh --show
    ;;

""|-h|--help)
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    echo
    echo "Current mode: $MODE"
    ;;

*)
    echo "Unknown command: $CMD (try ./gis.sh --help)" >&2
    exit 1
    ;;
esac
