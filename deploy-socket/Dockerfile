# Sibling-containers image: the web service only.
#
# No Docker-in-Docker. This container talks to the Docker daemon of the machine
# it runs on (its socket is mounted in), and that daemon builds the tool images
# and runs the indexing containers as siblings of this one. Nothing is
# privileged, and the images it builds are cached by the host's Docker, so they
# survive a restart.
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/
COPY tools/ /app/seed-tools/

COPY deploy-socket/entrypoint.sh /usr/local/bin/gis-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/gis-entrypoint.sh \
 && chmod +x /usr/local/bin/gis-entrypoint.sh

ENV SEED_TOOLS_DIR=/app/seed-tools \
    DOCKER_HOST=unix:///var/run/docker.sock \
    ADMIN_PORT=8888 \
    USER_PORT=8000

EXPOSE 8000 8888

ENTRYPOINT ["/usr/local/bin/gis-entrypoint.sh"]
