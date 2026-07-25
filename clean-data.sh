#!/usr/bin/env bash
# Genome Index Service - delete the data folder.
#
# Genomes and indexes are written by containers running as root, so if a run
# predates the permission fix your user may not be able to delete them. This
# removes the contents from inside a container (as root), which always works,
# then removes the empty folder.

set -u
cd "$(dirname "$0")"

echo
echo "=== Delete ./data (genomes, indexes, tools, jobs, requests) ==="
echo
read -r -p "This deletes ALL downloaded genomes and built indexes. Type YES to continue: " CONFIRM
if [ "${CONFIRM:-}" != "YES" ]; then
  echo "Aborted."
  exit 1
fi

echo
echo "Stopping the service..."
docker compose down --remove-orphans || true

if [ -d ./data ]; then
  echo
  echo "Removing contents from inside a container..."
  docker run --rm -v "$(pwd)/data:/target" alpine:3.20 \
    sh -c 'rm -rf /target/* /target/.[!.]* 2>/dev/null; exit 0'

  echo
  echo "Removing the empty folder..."
  rm -rf ./data 2>/dev/null || sudo rm -rf ./data
fi

if [ -d ./data ]; then
  echo
  echo "The folder is still there. Try: sudo rm -rf ./data"
else
  echo
  echo "Done: ./data removed."
fi
