"""High level orchestration tying folders, Ensembl, and Docker together.

An index job does, in order:
  1. resolve the FASTA and GTF URLs for the chosen species + release
  2. download and decompress the genome (skipped if already on disk)
  3. stop early if this exact index already exists
  4. build the tool image on the fly if it is not already built
  5. run the aligner's index builder in a container
  6. write the completion marker so future requests see it as existing
"""

import json
import time
from pathlib import Path

import config
import discovery
import docker_ops
import ensembl
import indexing
import perms


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_genome(species, release, log):
    """Make sure the genome (and the GTF, when one exists) are present and
    decompressed. Returns (fasta_path, gtf_path_or_None, meta).

    The FASTA is mandatory. The GTF is downloaded whenever Ensembl has one, even
    for tools that do not use it, so the genome folder is complete; when Ensembl
    has none, gtf_path is None and only GTF-dependent tools are affected.
    """
    gdir = discovery.genome_dir(species, release)
    gdir.mkdir(parents=True, exist_ok=True)

    existing = discovery.read_genome_meta(species, release)
    if existing:
        log(f"Genome already present for {species} release {release} "
            f"(assembly {existing.get('assembly')}).")
        gtf_name = existing.get("gtf_file")
        return (
            gdir / existing["fasta_file"],
            (gdir / gtf_name) if gtf_name else None,
            existing,
        )

    log(f"Resolving Ensembl URLs for {species} release {release}...")
    info = ensembl.resolve(species, release)
    log(f"Assembly {info['assembly']}, DNA flavour {info['dna_type']}.")
    for w in info.get("warnings", []):
        log(f"WARNING: {w}")

    # FASTA (required)
    fasta_gz = gdir / info["fasta"]["filename"]
    fasta_fa = gdir / fasta_gz.name[:-3]  # drop .gz
    ensembl.download(info["fasta"]["url"], fasta_gz, log=log)
    genome_length = ensembl.gunzip_measure(fasta_gz, fasta_fa, measure=True, log=log)
    fasta_gz.unlink(missing_ok=True)

    # GTF (optional)
    gtf_file = None
    if info.get("gtf"):
        gtf_gz = gdir / info["gtf"]["filename"]
        gtf_file = gdir / gtf_gz.name[:-3]
        ensembl.download(info["gtf"]["url"], gtf_gz, log=log)
        ensembl.gunzip_measure(gtf_gz, gtf_file, measure=False, log=log)
        gtf_gz.unlink(missing_ok=True)
    else:
        log("No annotation GTF for this combination; continuing without it.")

    meta = {
        "species": species,
        "release": str(release),
        "assembly": info["assembly"],
        "dna_type": info["dna_type"],
        "fasta_file": fasta_fa.name,
        "gtf_file": gtf_file.name if gtf_file else None,
        "genome_length": genome_length,
        "fasta_url": info["fasta"]["url"],
        "gtf_url": info["gtf"]["url"] if info.get("gtf") else None,
        "downloaded_at": _now(),
    }
    (gdir / discovery.GENOME_MARKER).write_text(json.dumps(meta, indent=2))
    perms.relax(gdir, config.HOST_UID, config.HOST_GID, log=log)
    log("Genome ready.")
    return fasta_fa, gtf_file, meta


def ensure_tool_image(tool, version, log):
    """Build the tool image if the daemon does not already have it."""
    tag = discovery.tool_image_tag(tool, version, config.TOOL_IMAGE_PREFIX)
    if docker_ops.image_exists(tag):
        log(f"Image {tag} already built.")
        return tag
    context = discovery.tool_dockerfile_dir(tool, version)
    if not (context / "Dockerfile").exists():
        raise FileNotFoundError(
            f"No Dockerfile for {tool} {version} at {context}."
        )
    try:
        docker_ops.build_tool_image(
            context, tag, buildargs={"TOOL_VERSION": version}, log=log
        )
    except Exception as exc:
        # Most tool Dockerfiles install packages, so a failure to resolve host
        # names is the usual cause. Point at it instead of leaving the user with
        # a wall of apt output. No checks run on the happy path.
        text = str(exc).lower()
        if any(k in text for k in ("could not resolve", "temporary failure in name",
                                   "name or service not known", "no installation candidate",
                                   "unable to locate package")):
            log("HINT: this looks like a name-resolution failure inside the build "
                "container, not a problem with the Dockerfile. Open the Jobs tab "
                "and press 'Run check' to confirm.")
        raise
    return tag


def run_index_job(tool, version, species, release, force_rebuild, params,
                  job_logger):
    """Full index pipeline. Sets its own terminal status only for the
    already-exists shortcut; otherwise the job runner marks it completed."""
    idir = discovery.index_dir(tool, version, species, release)

    if discovery.index_exists(tool, version, species, release) and not force_rebuild:
        meta = discovery.read_index_meta(tool, version, species, release)
        job_logger(
            f"Index already exists: {tool} {version} / {species} {release}. "
            f"Built at {meta.get('completed_at')}. Nothing to do."
        )
        return "already-exists"

    fasta, gtf, gmeta = ensure_genome(species, release, log=job_logger)

    tag = ensure_tool_image(tool, version, log=job_logger)

    idir.mkdir(parents=True, exist_ok=True)
    if params:
        job_logger("Parameters: " + ", ".join(
            f"{k}={v}" for k, v in params.items()))
    command = indexing.build_command(
        tool=tool,
        fasta=str(fasta),
        gtf=str(gtf) if gtf else "",
        index_dir=str(idir),
        genome_length=gmeta.get("genome_length", 0),
        command_template=discovery.read_tool_command(tool),
        params=params,
        default_threads=config.INDEX_THREADS,
        default_sjdb_overhang=config.STAR_SJDB_OVERHANG,
    )
    job_logger(f"Running {tool} {version} indexing (image {tag})...")
    code = docker_ops.run_indexing(
        tag, command,
        mount_source=config.DATA_HOST_BIND,
        mount_target=str(config.DATA_DIR),
        log=job_logger,
    )
    if code != 0:
        raise RuntimeError(f"Indexing container exited with code {code}.")

    marker = {
        "tool": tool,
        "tool_version": version,
        "species": species,
        "release": str(release),
        "assembly": gmeta.get("assembly"),
        "dna_type": gmeta.get("dna_type"),
        "image": tag,
        "params": params or {},
        "index_path": str(idir),
        "completed_at": _now(),
    }
    (idir / discovery.INDEX_MARKER).write_text(json.dumps(marker, indent=2))
    n = perms.relax(idir, config.HOST_UID, config.HOST_GID, log=job_logger)
    job_logger(f"Index complete. Marker written. "
               f"Permissions relaxed on {n} entries (deletable from the host).")
    return "completed"


def run_build_job(tool, version, job_logger):
    """Build (or rebuild) a tool image on demand."""
    ensure_tool_image(tool, version, log=job_logger)
    return "completed"
