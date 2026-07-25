# Genome Index Service

A self-hosted service to build aligner genome indexes on request, with two web
interfaces sharing the same storage: one for users, one for administrators.
Genomes and annotations are fetched from Ensembl automatically, aligners run in
containers built on the fly, and every result lands in a plain folder next to
the compose file.

Ships with **STAR**, **BWA**, **Bowtie2** and **HISAT2** (two pinned versions
each), and any other tool can be added from the admin interface.

---

## Quick start

Run the setup once. It asks which of the three modes you want and where the data
should live, then writes a single `.env`:

```bash
./setup.sh
```

It asks four things: the mode, where to keep the data, the two ports, and the
default thread count. Every answer has a sensible default, so pressing Enter
through it is fine. Choosing the socket mode additionally asks you to confirm,
because that one hands the Docker socket to the service container.

Then start it, whatever mode you chose:

```bash
./gis.sh start
```

That is it. The launcher reads `.env` and does the right thing, so you never have
to remember which compose file or script applies to your mode.

**On Windows** use `setup.cmd` and `gis.cmd`. In PowerShell you must prefix them
with `.\`, which is PowerShell refusing to run commands from the current folder
without it:

```powershell
.\setup.cmd
.\gis.cmd start
.\gis.cmd status
```

The first `start` builds the image, which takes a few minutes; after that it is
quick.

| Command | What it does |
| --- | --- |
| `./gis.sh start` | Build if needed, then start |
| `./gis.sh stop` | Stop |
| `./gis.sh restart` | Stop and start |
| `./gis.sh status` | Mode, folders, addresses, and whether it is running |
| `./gis.sh logs` | Follow the logs |
| `./gis.sh rebuild` | Force a rebuild, then start |
| `./gis.sh urls` | Print the interface addresses |
| `./gis.sh config` | Show the current configuration |

Prefer to configure by hand? Copy `.env.example` to `.env` and edit it; the same
launcher will use it. To change anything later, re-run the setup (it keeps a
backup of the previous configuration in `.env.bak`).

### Your first index

1. Open the **admin** interface (`./gis.sh urls` prints the address).
2. Go to **Jobs** and press **Run check**. Everything should be green or, at
   worst, a warning. If name resolution fails, fix that first: nothing that
   downloads will work otherwise.
3. Go to **Available tools** and press **Build** next to one of the tools, for
   example `star 2.7.11b`. Watch it in **Jobs**. STAR is quick (a static binary);
   BWA and HISAT2 compile from source and take a couple of minutes.
4. Go to **Generate index**, pick the tool and version, type an organism (try
   `drosophila` — a small genome, so this finishes fast) and pick a release.
5. Press **Check sources**. It confirms what will be downloaded and enables the
   **Generate index** button.
6. Press **Generate index** and follow it in **Jobs**. When it finishes, the
   result is under `<data directory>/indexes/star/2.7.11b/drosophila_melanogaster/<release>/`
   and shows up in the **Existing indexes** tab.

Students use the **user** interface, which is the same minus the admin tabs: they
generate indexes and request tools, and you fulfil the requests.

---

## The three modes

The service is identical in all three: same interfaces, same behaviour, same files
under `app/`. Only how Docker is provided differs.

| | **dind** | **socket** | **native** |
| --- | --- | --- | --- |
| Where it lives | one privileged container | one normal container | directly on the machine |
| Needs on the machine | Docker only | Docker only | Docker + Python 3 |
| Privileged container | **yes, required** | no | no |
| Host Docker socket | never touched | **mounted in** | used by a local account |
| Tool images after a restart | rebuilt | kept (host cache) | kept (host cache) |
| Nested DNS workaround | needed | not needed | not needed |
| Works on Windows | yes (Docker Desktop) | yes | Linux / macOS |
| Best for | a laptop, a demo, a self-contained install | **a lab server** | a server where you would rather not mount the socket |

**Which to pick.** On a laptop or for a demo, take **dind**: it is one thing to
start and stop and needs nothing but Docker. On a server, take **socket**: no
privileged container, the tool images stay cached, and none of the nested
networking complications apply — the trade-off is that mounting the Docker socket
gives that container root-equivalent control of Docker on the machine. If that is
not acceptable, take **native**, where no container ever receives the socket.

The setup script explains the same trade-off when you choose, and asks you to
confirm before selecting socket mode.

### Mode specifics

- **dind** — this README. Data goes wherever `GIS_DATA_DIR` points, `./data` by
  default. Two extra helpers live in the project root:

  | Script (Windows / Unix) | What it does |
  | --- | --- |
  | `clean-startup.cmd` / `./clean-startup.sh` | Removes containers, old volumes and old images from previous runs, then rebuilds and starts. Leaves the data alone |
  | `clean-data.cmd` / `./clean-data.sh` | Deletes the data directory, asking for confirmation first |

- **socket** — [`deploy-socket/README.md`](deploy-socket/README.md). Explains the
  security trade-off and why the data path is mounted identically inside and out.

- **native** — [`deploy-server/README.md`](deploy-server/README.md). `./gis.sh
  start` runs it in the foreground; `sudo ./deploy-server/install-native.sh`
  installs it as two systemd units that start at boot.

In socket and native mode the admin interface is bound to **localhost** by
default, since there is no login. Reach it over an SSH tunnel:

```bash
ssh -L 8888:127.0.0.1:8888 <server>
```

---

## What each interface does

The interface you get is decided by the port, not by a login. There is no
authentication by design: put your own access control (reverse proxy, VPN,
firewall) in front of the two ports.

**User interface (port 8000)**

| Tab | What it does |
| --- | --- |
| Generate index | Pick tool, version, parameters, organism, release, and build |
| Jobs | Live progress and logs for downloads, builds and indexing |
| Existing indexes | What is already built on disk |
| Available tools | Which tools and versions exist, and whether the image is built |
| Requests | Ask the administrator for a new tool or version |

**Admin interface (port 8888)** has the same tabs plus:

| Tab | What it does |
| --- | --- |
| Add tool | Add a tool: Dockerfile + index command + parameters |
| Requests | See pending requests; "Add" opens the Add tool tab pre-filled |
| Existing indexes | Also allows removing an index |
| Available tools | Also allows building/rebuilding images |

Admin-only extras: forcing a rebuild of an existing index, building images,
removing indexes, and adding tools. These are blocked on the user instance both
in the interface and in the API.

---

## How it fits together

```
                     Docker Desktop (host)
  +--------------------------------------------------------------+
  |   genome-index-service   (one privileged container)          |
  |                                                              |
  |   inner Docker daemon  <----- local unix socket ------+      |
  |   (dockerd, runs INSIDE this container)               |      |
  |        |  builds & runs tool images                   |      |
  |        v                                              |      |
  |   [ STAR / BWA / Bowtie2 / HISAT2 / ... containers ]   |      |
  |        |  bind /workspace/data                        |      |
  |        v                                        admin GUI 8888|
  |   +--------- bind mount: ./data -------------+   user  GUI 8000|
  |   |  tools/ genomes/ indexes/ requests/ jobs |   (two waitress |
  |   +------------------------------------------+    processes)  |
  +--------------------------------------------------------------+
```

- **No database.** The folder tree under `./data` is the single source of truth.
  Available tools are whatever Dockerfiles exist under `data/tools/`; an index
  exists if its completion marker exists; requests and job logs are JSON files.
- **Real Docker in Docker.** The Docker daemon runs *inside* the container and
  is reached through its own local socket. The host Docker socket is never
  mounted or shared. The host needs nothing but Docker: no Python, no conda, no
  aligners.
- **No persistent volumes.** The compose folder is bind-mounted at `/workspace`,
  so all data sits in `./data` right next to the compose file, visible from your
  file manager. The inner daemon's image store is not persisted, so tool images
  are rebuilt after `docker compose down`.
- **One container, two GUIs.** Admin (8888) and user (8000) are two waitress
  (WSGI) processes sharing the inner daemon and the same data folder.

---

## Folder layout (everything under the data directory)

```
<data directory>          # GIS_DATA_DIR: ./data by default in dind mode
  tools/<tool>/<version>/Dockerfile     available tools (discovery source)
  tools/<tool>/index_command.txt        how to run the indexer
  tools/<tool>/params.json              tunable parameters and defaults
  genomes/<species>/<release>/          downloaded FASTA + GTF (+ metadata)
  indexes/<tool>/<version>/<species>/<release>/
                                        the built index + INDEX_COMPLETE.json
  requests/<id>.json                    pending tool requests
  requests/fulfilled/<id>.json          fulfilled requests
  jobs/<id>.json                        job records and logs
```

**Your indexes are in `<data directory>/indexes/<tool>/<version>/<organism>/<release>/`.**

### File permissions

Everything under `./data` is written by containers running as **root**, so
without care those files end up owned by root with restrictive permissions and
the host user cannot delete them. The service handles this in three places:

- the container runs with `umask 000`, so new files and folders are created
  world-writable;
- after each genome download and each finished index, permissions are relaxed
  (directories `0777`, files `0666`) — you will see a line about it in the job
  log;
- at startup, the whole `./data` tree is repaired, which fixes anything left
  over by an earlier run.

So deleting `./data` from your file manager just works. If you have a folder
left from *before* this fix and it still refuses to go, run `clean-data.cmd`
(Windows) or `./clean-data.sh` (Linux/macOS): they delete the contents from
inside a container as root, which always succeeds.

On Linux and macOS you can also set `HOST_UID` and `HOST_GID` in `.env` (from
`id -u` and `id -g`) to have the files owned by your user outright. On Windows
this is unnecessary.

---

## How indexing works

**Check sources is mandatory.** The Generate button stays disabled until a
source check succeeds for the exact tool, version, organism and release you have
selected; changing any of them invalidates the check and you run it again. This
way nothing is ever queued against sources that turn out not to exist.

- **FASTA is required.** Without it there is nothing to index, so a missing
  FASTA fails the check and blocks the run.
- **GTF is a warning, not a blocker.** Some organism/release combinations on
  Ensembl have no annotation. The check reports it, and:
  - DNA-only tools (BWA, Bowtie2, minimap2) proceed normally;
  - tools whose command references `{gtf}` (STAR, HISAT2) are blocked, with the
    reason spelled out, since they genuinely cannot build without annotation.

Then the run itself:

1. You pick tool, version, parameters, organism and Ensembl release.
2. The service reads the real Ensembl FTP listing and resolves the actual FASTA
   and GTF filenames (the assembly name is read from the file, never guessed).
3. It downloads and decompresses them (skipped if already on disk).
4. If that exact index already exists, it stops and tells you.
5. If the tool image is not built yet, it builds it on the fly.
6. It runs the tool's index command in a container and writes a completion
   marker recording tool, version, assembly, parameters and timestamp.

### Organisms and releases

The organism list comes from the Ensembl FTP (the authoritative set of species
with downloadable data), so model organisms such as *Drosophila melanogaster*,
*C. elegans* and *S. cerevisiae* are included alongside the vertebrates. Search
is a substring match: typing `dro` shows every match. Once you pick an organism,
the release dropdown is populated with only the releases that actually contain
that organism.

Scope: this targets Ensembl main. Species that live only in Ensembl Genomes
(Metazoa, Plants, Fungi, Protists, Bacteria) are not covered; the release list
will show "Not available on Ensembl (main)" for them.

### DNA flavour

The service prefers `primary_assembly` and falls back to `toplevel`.
`primary_assembly` is what the STAR manual and nf-core recommend when it exists
(it drops haplotype and patch scaffolds); small genomes that have no
`primary_assembly` file use `toplevel`. Change the order with `DNA_PREFERENCE`.

---

## Adding a tool

A tool is described by **three things**, all stored as plain files:

1. **Dockerfile** — `data/tools/<tool>/<version>/Dockerfile`
2. **Index command** — `data/tools/<tool>/index_command.txt`
3. **Parameters** (optional) — `data/tools/<tool>/params.json`

Add it from the admin **Add tool** tab (or drop the files in by hand). The
folders are created automatically and the tool becomes selectable immediately.

### Placeholders for the index command

`{fasta}` and `{gtf}` are **supplied by the service, not by you**: once the user
picks an organism and release, the service resolves the real Ensembl filenames,
downloads and decompresses them, and substitutes those exact paths into the
command. So you never declare them as parameters and never point at a file
yourself; they are always the right files for the combination being built.
Parameters are only for the tunables (threads, k-mer size, and so on).

| Placeholder | Meaning | Comes from |
| --- | --- | --- |
| `{fasta}` | Decompressed genome FASTA | Resolved and downloaded from Ensembl |
| `{gtf}` | Decompressed annotation GTF | Resolved and downloaded from Ensembl |
| `{index_dir}` | Output folder (created for you) | The service |
| `{threads}` | CPU threads | Parameter, else `INDEX_THREADS` |
| `{sjdb_overhang}` | STAR sjdbOverhang | Parameter, else `.env` |
| `{sa_index_nbases}` | STAR genomeSAindexNbases | Computed from genome size |
| `{genome_length}` | Total genome length | Measured while decompressing |
| `{name}` | Any parameter you declare | The form field, else its default |

### Parameters

Declare them one per line as `name=default` (for example `threads=4`). They
appear as editable fields in the index form, pre-filled with the default, and
can be changed per job; the values used are recorded in the index marker.

Seeded defaults: STAR exposes `threads` and `sjdb_overhang`; Bowtie2 and HISAT2
expose `threads`; BWA has none. Values are restricted to a safe character set so
they cannot inject shell commands into the container.

### No conda

The shipped Dockerfiles use tagged releases straight from GitHub: STAR and
Bowtie2 use the official precompiled Linux binaries pinned to the tag, BWA and
HISAT2 are compiled from the tagged source. Each image only needs the tool on
`PATH`; the index command is supplied at run time.

---

## Worked example: adding minimap2

**1.** Admin interface → **Add tool** tab.

**2.** Tool name `minimap2`, Version `2.28`.

**3.** Dockerfile:

```dockerfile
# minimap2 2.28 - compiled from the tagged GitHub source.
# Runtime needs only zlib, which is already in the base image.
FROM debian:bookworm-slim
ARG TOOL_VERSION=2.28
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates wget make gcc zlib1g-dev \
 && wget -qO /tmp/mm2.tar.gz "https://github.com/lh3/minimap2/archive/refs/tags/v${TOOL_VERSION}.tar.gz" \
 && tar -xzf /tmp/mm2.tar.gz -C /tmp \
 && make -C /tmp/minimap2-${TOOL_VERSION} \
 && cp /tmp/minimap2-${TOOL_VERSION}/minimap2 /usr/local/bin/minimap2 \
 && chmod +x /usr/local/bin/minimap2 \
 && rm -rf /tmp/minimap2* /var/lib/apt/lists/* \
 && minimap2 --version
```

**4.** Index command:

```
minimap2 -t {threads} -d {index_dir}/genome.mmi {fasta}
```

**5.** Parameters:

```
threads=4
```

**6.** Click **Add and build image**, watch it in **Jobs**, then generate an
index with it from the Generate tab. The result is
`data/indexes/minimap2/2.28/<organism>/<release>/genome.mmi`.

minimap2 does not use the GTF at index time (splice information is supplied when
aligning), which is why the command does not reference `{gtf}`.

---

## Interface

- **Appearance** is set by two independent selectors in the top bar:
  - **Mode**: Light or Dark (the first visit follows your operating system).
  - **Colour vision palette**: Default, Deuteranopia, Protanopia, Tritanopia or
    Monochrome. Every palette works in both light and dark, so there are ten
    combinations. The palettes only change the meaning-carrying colours
    (success, failure, warning, accent) and are built on the Okabe-Ito
    colour-blind-safe set:
    - *Deuteranopia* (green-blind): blue vs vermillion, never green vs red.
    - *Protanopia* (red-blind): blue vs amber, since deep reds read as near-black.
    - *Tritanopia* (blue-yellow blind): red and green stay usable, blues and
      yellows do not.
    - *Monochrome* (achromatopsia): no hue at all, separation by lightness plus
      the text label on every status.
  Both choices are remembered.
- **Tabs** keep each concern separate; the page itself never scrolls, only
  panels scroll internally.
- **Badges** show the number of active jobs and pending requests.
- Requests flow straight into fulfilment: clicking **Add** on a request opens
  the Add tool tab pre-filled with the requested tool and version, and adding it
  marks the request fulfilled.

---

## Configuration

`./setup.sh` writes `.env` for you; these are the settings it contains (and you
can edit them by hand at any time, then `./gis.sh restart`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `GIS_MODE` | `dind` | `dind`, `socket` or `native` |
| `GIS_DATA_DIR` | `./data` | Where genomes, indexes, tools and jobs are stored (absolute path required in socket mode) |
| `GIS_USER_PORT` | `8000` | Port for the user interface |
| `GIS_ADMIN_PORT` | `8888` | Port for the admin interface |
| `GIS_ADMIN_BIND` | `127.0.0.1` | Address the admin interface listens on |
| `GIS_USER_BIND` | `0.0.0.0` | Address the user interface listens on |
| `INDEX_THREADS` | `4` | Fallback thread count when a tool has no `threads` parameter |
| `DNA_PREFERENCE` | `primary_assembly,toplevel` | FASTA flavour preference order |
| `HOST_UID` / `HOST_GID` | unset | Linux only: own the data files as this user instead of root |

---

## Notes and caveats

### System check

The Jobs tab has a **System check** panel with a *Run check* button. It probes,
in about a second or two:

| Check | What it tells you |
| --- | --- |
| Docker daemon | Whether the service can talk to the daemon at all |
| Image registry | Whether the daemon can pull images |
| Name resolution inside containers | The usual cause of failed image builds |
| Outbound HTTPS inside containers | Whether containers can fetch sources |
| Ensembl reachable | Whether genome downloads will work |
| Data folder | Writable, and with which permissions |

It runs **only when you press the button**: no check runs during a build or an
index job, so normal use pays nothing for it. The daemon indicator in the top bar
is refreshed from the result. If an image build does fail on name resolution, the
job log says so explicitly and points you here instead of leaving you with a wall
of apt output.

### Networking inside the nested Docker (dind mode only)

This applies to **dind** mode only. In socket and native mode the machine's own
Docker handles networking, and none of it is needed.

Image builds run in containers created by the inner daemon, and those need to
resolve host names to fetch packages (apt) and sources (GitHub). They do not
inherit this container's resolver, and pointing them at public DNS is not enough
because many networks block outbound UDP/53. On startup the service therefore:

1. reads the resolvers this container uses;
2. if one is routable, hands it straight to the inner daemon;
3. if they are all loopback (Docker Desktop uses `127.0.0.11`, which nested
   containers cannot reach), starts a small `dnsmasq` forwarder on the nested
   bridge and points the daemon at that.

You can see which path was taken in the container log:

```
docker compose logs gis | grep "nested DNS"
```

Before each image build the service also probes name resolution from a
container and says so in the job log, so a DNS problem is reported as a DNS
problem rather than as a wall of apt errors.

If a build fails with `Could not resolve deb.debian.org` (or similar), that is
this issue: check the `nested DNS` lines above, and note that STAR still builds
in such a case because its Dockerfile uses `ADD`, which is fetched by the daemon
itself rather than inside a build container.

### Other notes

- **Privileged container.** Docker-in-Docker requires it. Docker Desktop allows
  this; some locked-down hosts do not.
- **First start takes a few seconds** while the inner daemon comes up.
- **Resources.** A STAR index for a large genome (human, mouse) needs a lot of
  RAM (roughly 30 GB) available to the Docker engine, and the indexes are large
  on disk.
- **Concurrency.** Jobs run two at a time in-process. This is a self-contained
  service, not a cluster scheduler.
- **Security.** The admin port can build images and delete indexes, so guard it.
- **Bowtie2, not Bowtie1.** "Bowtie" was read as Bowtie2; Bowtie1 can be added
  the same way as any other tool.

### Why all three modes work from one codebase

Nothing under `app/` knows how Docker is provided. The service talks to whatever
daemon `DOCKER_HOST` points at, writes everything under `DATA_DIR`, and keeps the
environment checks in a separate `diagnostics` module that never runs on the
indexing path.

Each mode is therefore just a different deployment layer around the same code:
Docker-in-Docker in the project root, sibling containers in `deploy-socket/`, and
a plain process in `deploy-server/`. That is why all three behave identically.
