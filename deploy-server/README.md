# Native: the service as a plain process

One of the three ways to run this (see the main README). Here the service runs as
an ordinary process on the machine and uses that machine's own Docker to build the
tool images and run the indexing containers.

Choose this over the sibling-containers mode in `deploy-socket/` when you would
rather not mount the Docker socket into a container: here no container ever
receives it, only a local account in the `docker` group uses it.

Nothing under `app/` changes: the service talks to whatever Docker daemon
`DOCKER_HOST` points at, so the only difference is how it is started.

**Requirements:** Docker installed and running (and usable by your account), plus
Python 3. Option 2 additionally needs systemd and root.

Two ways in, below: run it straight away without installing anything, or install
it as a service that starts at boot.

---

## Option 1: run it now, installing nothing

```bash
./deploy-server/run-local.sh
```

Creates a virtualenv in `.venv-server`, uses `./data` in the project folder for
the data, and starts both interfaces in the foreground. Ctrl-C stops them. No
root, no systemd, nothing installed system-wide — handy for trying this mode or
for a one-off session.

Override the defaults with environment variables:

```bash
DATA_DIR=/data/gis USER_PORT=9000 ./deploy-server/run-local.sh
```

It also sets `HOST_UID`/`HOST_GID` to your own account, so the genomes and
indexes it writes belong to you rather than to root.

## Option 2: install it as a service

Run from the **project root** (the folder containing `app/` and `tools/`):

```bash
sudo ./deploy-server/install-native.sh
```

It creates a `gis` system user in the `docker` group, installs the code under
`/opt/genome-index-service` with its own virtualenv, creates the data directory
at `/srv/genome-index-service/data`, and starts two systemd units.

- user interface: `http://<server>:8000`
- admin interface: `http://127.0.0.1:8888` — bound to localhost on purpose

There is no login, so the admin interface is not exposed. Reach it over an SSH
tunnel:

```bash
ssh -L 8888:127.0.0.1:8888 <server>
# then open http://localhost:8888
```

Change the defaults by setting variables before running the installer:

```bash
sudo PREFIX=/opt/gis DATA_DIR=/data/gis USER_PORT=9000 ./deploy-server/install-native.sh
```

## Day to day

```bash
systemctl status genome-index-user genome-index-admin
systemctl restart genome-index-user genome-index-admin
journalctl -u genome-index-user -f
```

## Uninstall

```bash
sudo ./deploy-server/uninstall-native.sh
```

The data directory is left in place; delete it yourself if you want it gone.

---

## Configuration

The systemd units set these; edit the unit files (or re-run the installer with
different values) to change them.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATA_DIR` | `/srv/genome-index-service/data` | Genomes, indexes, tools, jobs |
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | The daemon to use |
| `APP_PORT` | `8888` admin, `8000` user | Port for that unit |
| `INDEX_THREADS` | `4` | Fallback thread count |
| `DNA_PREFERENCE` | `primary_assembly,toplevel` | FASTA flavour order |
| `HOST_UID` / `HOST_GID` | unset | Own the data files as this user |

`HOST_UID`/`HOST_GID` are worth setting here: on a server, pointing them at the
account that manages the data (`id -u`, `id -g`) means the downloaded genomes and
built indexes belong to that user instead of root. Permissions are relaxed
either way, so the files are always deletable.

---

## Differences from the bundled version

| | Bundled (Docker-in-Docker) | Plain service |
| --- | --- | --- |
| Privileged container | yes, required | none |
| Needs Python on the machine | no | yes (a venv is created) |
| Tool images survive a restart | no, rebuilt | yes, cached by the server's Docker |
| Nested DNS workaround | needed | not needed, the server's Docker is fine |
| Data location | `./data` next to the compose file | `DATA_DIR`, `/srv/...` by default |

## After starting it

Open the admin interface and press **Run check** in the Jobs tab: it verifies the
Docker daemon, name resolution and outbound network from inside a container,
Ensembl, and the data directory. Quickest way to confirm the server can do the
work before a student tries it.

## What the students see

Nothing changes for them: same interfaces, same tabs, same behaviour. Only the
plumbing underneath is different.
