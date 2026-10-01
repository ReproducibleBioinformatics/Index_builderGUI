"""Central configuration.

Every path and credential is read from the environment so the same image can
run as the admin instance (port 8888) and the user instance (port 8000)
against the same shared data volume. There is no database anywhere in this
project: the folder tree under DATA_DIR is the single source of truth.
"""

import os
from pathlib import Path


def _clean_list(raw: str):
    return [item.strip() for item in raw.split(",") if item.strip()]


# --- Storage layout: no database, only folders. -----------------------------
# Everything the service produces lives under DATA_DIR. In the bundled packaging
# the project folder is bind-mounted at /workspace, so this resolves to ./data
# next to the compose file; on a plain server, point it wherever you like.
DATA_DIR = Path(os.environ.get("DATA_DIR", "/workspace/data"))
SEED_TOOLS_DIR = Path(os.environ.get("SEED_TOOLS_DIR", "/app/seed-tools"))

TOOLS_DIR = DATA_DIR / "tools"          # tools/<tool>/<version>/Dockerfile
GENOMES_DIR = DATA_DIR / "genomes"      # genomes/<species>/<release>/*.fa|*.gtf
INDEXES_DIR = DATA_DIR / "indexes"      # indexes/<tool>/<version>/<species>/<release>/
REQUESTS_DIR = DATA_DIR / "requests"    # requests/*.json  (+ fulfilled/)
JOBS_DIR = DATA_DIR / "jobs"            # jobs/*.json  (persisted job records)

# In socket mode the daemon lives OUTSIDE this container, so when the service
# asks it to bind the data directory into a freshly spawned tool container, the
# source path has to be one the daemon itself can resolve - not necessarily
# this container's own view of DATA_DIR. DATA_HOST_BIND is that daemon-facing
# path. It defaults to DATA_DIR itself, which is correct whenever the daemon
# shares this container's filesystem (dind) or the plain Linux/macOS "same
# absolute path" convention (socket mode there). On Docker Desktop for Windows
# it is instead the //<drive>/... form Docker Desktop expects for sibling-
# container binds, e.g. //c/Users/you/genome-index-service/data - setup.cmd
# computes that value for you.
DATA_HOST_BIND = os.environ.get("DATA_HOST_BIND", "").strip() or str(DATA_DIR)

# --- This instance's identity -----------------------------------------------
# There is no login: the running instance's role is fixed here. Run one
# instance as admin (port 8888) and one as user (port 8000). Put your own
# access control (reverse proxy, firewall, VPN) in front of the ports.
APP_ROLE = os.environ.get("APP_ROLE", "admin")   # "admin" | "user"
APP_PORT = int(os.environ.get("APP_PORT", "8000"))


def is_admin_instance():
    return APP_ROLE == "admin"


# --- Running inside JupyDo (APP_ROLE=hub) -----------------------------------
# One instance serves everyone: login goes through JupyterHub OAuth and the
# role comes from the hub (hub admins get the admin interface). Indexing
# containers are submitted to the JupyDo job queue instead of being run here.
HUB_MODE = APP_ROLE == "hub"
JOBQUEUE_URL = os.environ.get("JOBQUEUE_URL", "").rstrip("/")
JOBQUEUE_TOKEN = os.environ.get("JOBQUEUE_TOKEN", "")
INDEX_MEM_GB = float(os.environ.get("INDEX_MEM_GB", "32"))
INDEX_WALLTIME_MIN = int(os.environ.get("INDEX_WALLTIME_MIN", "1440"))
JOB_WORKERS = int(os.environ.get("JOB_WORKERS", "2"))

# --- Docker -----------------------------------------------------------------
# The daemon the service talks to. In the Docker-in-Docker packaging this is the
# nested daemon's own socket, created inside the container (never the host's).
# On a plain server it is simply that machine's Docker socket.
DOCKER_HOST = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
TOOL_IMAGE_PREFIX = os.environ.get("TOOL_IMAGE_PREFIX", "gis-tool")

# --- Indexing knobs ---------------------------------------------------------
INDEX_THREADS = int(os.environ.get("INDEX_THREADS", "4"))
STAR_SJDB_OVERHANG = int(os.environ.get("STAR_SJDB_OVERHANG", "100"))


# --- Host file ownership ----------------------------------------------------
# Containers run as root, so everything written under ./data would be owned by
# root on the host. Permissions are always relaxed to 0777/0666 so the host can
# delete them. Optionally, set HOST_UID/HOST_GID (Linux and macOS) to also hand
# ownership to your user; leave unset on Windows, where it is not needed.
def _opt_int(name):
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


HOST_UID = _opt_int("HOST_UID")
HOST_GID = _opt_int("HOST_GID")

# --- Ensembl -----------------------------------------------------------------
ENSEMBL_REST = os.environ.get("ENSEMBL_REST", "https://rest.ensembl.org")
ENSEMBL_FTP = os.environ.get("ENSEMBL_FTP", "https://ftp.ensembl.org")

# Preference order for the DNA FASTA flavour. primary_assembly is the flavour
# recommended by the STAR manual and nf-core when it exists (it drops haplotype
# and patch scaffolds); toplevel is the universal fallback for small genomes
# that have no primary_assembly file.
DNA_PREFERENCE = _clean_list(
    os.environ.get("DNA_PREFERENCE", "primary_assembly,toplevel")
)



def ensure_dirs():
    for d in (TOOLS_DIR, GENOMES_DIR, INDEXES_DIR, REQUESTS_DIR,
              REQUESTS_DIR / "fulfilled", JOBS_DIR):
        d.mkdir(parents=True, exist_ok=True)
