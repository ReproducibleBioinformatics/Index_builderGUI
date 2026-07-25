# Sibling containers (Docker outside of Docker)

The service runs in a container and uses the **host's** Docker to build the tool
images and run the indexing containers, as siblings of itself rather than nested
inside it. This is the usual production pattern for a service whose job is to run
containers, and for a lab server it is arguably the best of the three modes.

Nothing under `app/` differs from the other modes: the service talks to whatever
daemon `DOCKER_HOST` points at.

**Requirements:** Docker on the machine. Nothing else — no Python needed on the
host, since the service itself is containerised.

---

## Why this mode

Compared with the bundled Docker-in-Docker packaging:

| | Docker-in-Docker | **Sibling containers** |
| --- | --- | --- |
| Privileged container | required | **not needed** |
| Tool images after a restart | rebuilt from scratch | **cached by the host's Docker** |
| Nested networking / DNS workaround | needed | **not needed** |
| Storage | nested storage driver on top of the host's | the host's, directly |
| Host Docker socket | never touched | **mounted into the container** |

The first four rows are why this mode is attractive; the last row is the price.

### The security trade-off, plainly

Mounting `/var/run/docker.sock` gives this container control of the host's Docker,
which in practice is equivalent to root on the host. That is inherent to the
design: the whole point is to build and run containers. It is fine on a machine
you administer, and it is what CI runners and similar tools do. If it is not
acceptable in your environment, use one of the other two modes:

- **Docker-in-Docker** (project root): privileged, but the host socket is never
  shared.
- **Native install** (`deploy-server/`): no container for the service at all, the
  socket is used by a local service account in the `docker` group.

---

## Start it

Run from the **project root** (the build context needs `app/` and `tools/`):

```bash
export GIS_DATA_DIR=/srv/genome-index-service/data
sudo mkdir -p "$GIS_DATA_DIR"
docker compose -f deploy-socket/docker-compose.yml up --build -d
```

- user interface: `http://<server>:8000`
- admin interface: `http://127.0.0.1:8888` — bound to localhost, since there is
  no login

Reach the admin interface over an SSH tunnel:

```bash
ssh -L 8888:127.0.0.1:8888 <server>
# then open http://localhost:8888
```

Day to day:

```bash
docker compose -f deploy-socket/docker-compose.yml logs -f
docker compose -f deploy-socket/docker-compose.yml restart
docker compose -f deploy-socket/docker-compose.yml down
```

---

## The one thing to get right: the data path

The daemon is **outside** this container, so when the service asks it to run an
indexing container with a bind mount, that path is resolved **on the daemon's
side**, not against this container's own filesystem.

The data directory is mounted into this container at a fixed path
(`/workspace/data`, same as every other mode) — that part is a normal bind and
needs nothing special. Separately, `DATA_HOST_BIND` is the path the *daemon*
needs in order to resolve that same directory when the service asks it to bind
it into a tool container (bowtie2, STAR, ...):

- **Linux/macOS:** the same absolute host path as `GIS_DATA_DIR` (the default —
  nothing to configure).
- **Docker Desktop for Windows:** the `//<drive>/...` form Docker Desktop
  expects for this kind of sibling-container bind, e.g.
  `//c/Users/you/genome-index-service/data`. `setup.cmd` computes this
  automatically from the Windows path you give it and writes it as
  `GIS_DATA_HOST_BIND`.

If you change `GIS_DATA_DIR` on Linux/macOS, that is all you need to change:

```bash
export GIS_DATA_DIR=/data/genome-index
sudo mkdir -p "$GIS_DATA_DIR"
docker compose -f deploy-socket/docker-compose.yml up --build -d
```

On Windows, re-run `setup.cmd` instead so the `//<drive>/...` translation stays
in sync with the path you pick.

---

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `GIS_DATA_DIR` | `/srv/genome-index-service/data` | Data directory, bind source on the compose side |
| `GIS_DATA_HOST_BIND` | same as `GIS_DATA_DIR` | What the daemon uses to resolve that directory for sibling-container mounts (only needs to differ from `GIS_DATA_DIR` on Docker Desktop for Windows) |
| `INDEX_THREADS` | `4` | Fallback thread count when a tool has no `threads` parameter |
| `DNA_PREFERENCE` | `primary_assembly,toplevel` | FASTA flavour order |
| `HOST_UID` / `HOST_GID` | unset | Own the data files as this user (`id -u`, `id -g`) |

Permissions are relaxed regardless, so the data directory is always deletable
from the host; setting `HOST_UID`/`HOST_GID` additionally makes the files belong
to your account instead of root.

---

## After starting it

Open the admin interface and press **Run check** in the Jobs tab. It verifies the
daemon, name resolution and outbound network from inside a container, Ensembl, and
the data directory — the quickest confirmation that the server can do the work.

Name resolution should simply pass here: containers get their network from the
host's Docker, so the nested-DNS problem of dind mode does not arise.

## What the students see

Nothing changes for them: same interfaces, same tabs, same behaviour.
