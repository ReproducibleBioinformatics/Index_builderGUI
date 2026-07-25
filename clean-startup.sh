#!/usr/bin/env bash
# Genome Index Service - clean startup (Linux / macOS)
# Removes anything from previous runs, then rebuilds and starts the service.
# Data in ./data is NOT touched; delete that folder yourself to wipe genomes,
# indexes and tools.

set -u

cd "$(dirname "$0")"

echo
echo "=== Genome Index Service: clean startup ==="
echo

echo "[1/5] Stopping the project (containers, network, orphans)..."
docker compose down --remove-orphans || true

echo
echo "[2/5] Removing leftover containers from older versions..."
docker rm -f genome-index-service gis-dind gis-app-admin gis-app-user 2>/dev/null || true

echo
echo "[3/5] Removing old persistent volumes (pre bind-mount versions)..."
docker volume rm genome-index-service_gis_data \
                 genome-index-service_gis_docker_storage \
                 genome-index-service_gis_dind_storage 2>/dev/null || true

echo
echo "[4/5] Removing old application images so they rebuild from scratch..."
docker rmi gis:latest gis-app:latest 2>/dev/null || true

echo
echo 'Note: "No such container/volume/image" above is normal - it just means'
echo "there was nothing left to clean."
echo
echo "[5/5] Building and starting..."
echo "    admin GUI: http://localhost:8888"
echo "    user  GUI: http://localhost:8000"
echo
exec docker compose up --build
