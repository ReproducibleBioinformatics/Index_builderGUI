# Self-contained Docker-in-Docker image.
#
# The Docker daemon runs INSIDE this container. The host Docker socket is never
# mounted and never shared: the app talks only to the inner daemon's own local
# unix socket, which is created inside this container. Both GUIs and the inner
# daemon live here together, which is the "everything inside a docker-in-docker"
# setup you asked for. Requires the container to run privileged.
FROM docker:27-dind

# Python runtime for the web app. The aligner images are built and run by the
# inner Docker daemon, so this layer only carries the web service itself.
# The Python stack is pure Python (Flask + waitress), so pip installs from
# wheels only and never needs a compiler or Rust toolchain on Alpine.
#
# The explicit "--upgrade libexpat" is the fix for a known Alpine packaging bug
# (aports #18124): the docker:dind base ships a cached libexpat (2.7.0) while apk
# installs a newer python3 whose pyexpat.so needs a symbol added in libexpat
# 2.7.2 (XML_SetAllocTrackerActivationThreshold). python3 only declares an
# unversioned so:libexpat.so.1 dependency, so apk will not upgrade the old
# libexpat on its own, and pip itself then crashes on import. Upgrading libexpat
# explicitly pulls a version that has the symbol.
RUN apk add --no-cache --upgrade libexpat python3 py3-pip ca-certificates dnsmasq

WORKDIR /app

COPY app/requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

# Application code and the baked-in static tool Dockerfiles (seeded into the
# shared volume on first run).
COPY app/ /app/
COPY tools/ /app/seed-tools/

# Entrypoint: bring up the inner daemon, then run both GUIs. The sed strips any
# CRLF line endings so the script runs even if it was checked out on Windows.
COPY entrypoint.sh /usr/local/bin/gis-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/gis-entrypoint.sh \
    && chmod +x /usr/local/bin/gis-entrypoint.sh

ENV DATA_DIR=/data \
    SEED_TOOLS_DIR=/app/seed-tools \
    DOCKER_HOST=unix:///var/run/docker.sock \
    DOCKER_TLS_CERTDIR="" \
    ADMIN_PORT=8888 \
    USER_PORT=8000

EXPOSE 8000 8888

ENTRYPOINT ["/usr/local/bin/gis-entrypoint.sh"]
