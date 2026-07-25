#!/bin/sh
# Bring up the inner Docker daemon (true docker-in-docker, no host socket), then
# run both GUIs: admin and user. Everything lives in this one container.
set -eu

# Containers here run as root. Without a permissive umask, everything written
# under the bind-mounted ./data would be created with restrictive permissions
# and the host user could not delete it. 000 means new files are 666 and new
# directories 777.
umask 000

ADMIN_PORT="${ADMIN_PORT:-8888}"
USER_PORT="${USER_PORT:-8000}"

# --- DNS for the nested containers ------------------------------------------
# Containers created by the inner daemon (image builds, indexing) sit on a
# bridge inside this container and need a resolver they can actually reach.
#
# Pointing them at public DNS is not enough: many networks block outbound
# UDP/53, which is why apt failed with "Could not resolve deb.debian.org" while
# the app itself downloaded from Ensembl happily. The reliable resolver is the
# one THIS container already uses, but under Docker Desktop that is Docker's
# embedded server on a loopback address (127.0.0.11), which nested containers
# cannot reach.
#
# So: if this container has a routable resolver, hand it straight to the inner
# daemon. If it only has loopback resolvers, run a tiny dnsmasq forwarder bound
# to the nested bridge and point the daemon at that instead. Either way the
# nested containers resolve through a path that is known to work here.
BRIDGE_IP="172.29.0.1"
BRIDGE_CIDR="172.29.0.1/16"

UPSTREAM="$(awk '/^nameserver/ {print $2}' /etc/resolv.conf 2>/dev/null | tr '\n' ' ')"
ROUTABLE_ARGS=""
for ns in $UPSTREAM; do
    case "$ns" in
        127.*|::1|localhost) ;;                       # unreachable from nested
        *) ROUTABLE_ARGS="$ROUTABLE_ARGS --dns $ns" ;;
    esac
done

if [ -n "$ROUTABLE_ARGS" ]; then
    DNS_ARGS="$ROUTABLE_ARGS"
    NEED_FORWARDER=0
    echo "[gis] nested DNS: using this container's resolvers ($DNS_ARGS)"
elif [ -n "$UPSTREAM" ]; then
    DNS_ARGS="--dns $BRIDGE_IP"
    NEED_FORWARDER=1
    echo "[gis] nested DNS: resolvers are loopback ($UPSTREAM);"
    echo "[gis]             starting a forwarder on $BRIDGE_IP"
else
    DNS_ARGS="--dns 8.8.8.8 --dns 1.1.1.1"
    NEED_FORWARDER=0
    echo "[gis] nested DNS: no resolver found in /etc/resolv.conf, falling back"
    echo "[gis]             to public DNS ($DNS_ARGS)"
fi

echo "[gis] starting inner Docker daemon (docker-in-docker)..."
# Uses the official dind setup, backgrounded. This daemon exposes only its local
# unix socket at /var/run/docker.sock, created inside this container. The host
# daemon and its socket are never touched. --bip fixes the nested bridge address
# so the DNS forwarder above has a known address to bind to.
dockerd-entrypoint.sh dockerd \
    --host=unix:///var/run/docker.sock \
    --bip="$BRIDGE_CIDR" \
    $DNS_ARGS \
    >/var/log/dockerd.log 2>&1 &

echo "[gis] waiting for the inner daemon to become ready..."
tries=0
until docker info >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -gt 90 ]; then
        echo "[gis] inner Docker daemon failed to start. Last log lines:"
        tail -n 60 /var/log/dockerd.log 2>/dev/null || true
        exit 1
    fi
    sleep 1
done
echo "[gis] inner Docker daemon is up."

if [ "$NEED_FORWARDER" = "1" ]; then
    SERVERS=""
    for ns in $UPSTREAM; do
        SERVERS="$SERVERS --server=$ns"
    done
    # Bound to the bridge address only, so it never clashes with Docker's own
    # resolver on 127.0.0.11, which is exactly what it forwards to.
    if dnsmasq --listen-address="$BRIDGE_IP" --bind-interfaces --no-resolv \
               --no-hosts --user=root $SERVERS 2>/var/log/dnsmasq.log; then
        echo "[gis] DNS forwarder running on $BRIDGE_IP ->$SERVERS"
    else
        echo "[gis] WARNING: could not start the DNS forwarder. Image builds that"
        echo "[gis]          download packages may fail to resolve host names."
        tail -n 5 /var/log/dnsmasq.log 2>/dev/null || true
    fi
fi

cd /app

echo "[gis] admin GUI on :$ADMIN_PORT, user GUI on :$USER_PORT"
# Two GUIs, one per role, served by waitress (pure-Python WSGI server). Each
# process reads its role from APP_ROLE at import time.
APP_ROLE=admin APP_PORT="$ADMIN_PORT" \
    waitress-serve --host=0.0.0.0 --port="$ADMIN_PORT" --threads=8 main:app &
ADMIN_PID=$!

APP_ROLE=user APP_PORT="$USER_PORT" \
    waitress-serve --host=0.0.0.0 --port="$USER_PORT" --threads=8 main:app &
USER_PID=$!

# If either web process stops, bring the whole container down so it restarts.
while kill -0 "$ADMIN_PID" 2>/dev/null && kill -0 "$USER_PID" 2>/dev/null; do
    sleep 3
done

echo "[gis] a web process exited; shutting the container down."
kill "$ADMIN_PID" "$USER_PID" 2>/dev/null || true
exit 1
