"""Environment diagnostics: a quick, on-demand health check.

Deliberately kept in its own module and off the indexing path. Nothing here runs
during a build or an index job: the checks happen only when asked for (the
"Run check" button, or GET /api/diagnostics). That keeps the primary code free of
environment-specific concerns and means these checks cost nothing in normal use.

The checks are written against "whatever Docker daemon we are configured to talk
to", so they are valid unchanged whether that daemon is a nested one
(Docker-in-Docker) or the plain daemon of a server. Only the deployment layer
(entrypoint, compose file) knows about Docker-in-Docker.

Each check returns:
    {"id", "label", "status": ok|warn|fail|skip, "detail"}
"""

import os
import time

import config
import docker_ops

# Small image used to run checks from inside a container. Pulled once and cached
# by the daemon afterwards.
PROBE_IMAGE = "alpine:3.20"
PROBE_DNS_HOST = "deb.debian.org"
PROBE_HTTPS_URL = "https://github.com/"


def _result(cid, label, status, detail=""):
    return {"id": cid, "label": label, "status": status, "detail": detail}


def check_daemon():
    """Is the Docker daemon reachable at all?"""
    try:
        client = docker_ops.get_client()
        info = client.version()
        return _result(
            "daemon", "Docker daemon", "ok",
            f"Reachable at {config.DOCKER_HOST} (engine {info.get('Version', '?')})",
        )
    except Exception as exc:  # noqa: BLE001
        return _result(
            "daemon", "Docker daemon", "fail",
            f"Not reachable at {config.DOCKER_HOST}: {exc}",
        )


def check_data_dir():
    """Can we write to the data folder, and is it deletable from the host?"""
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = config.DATA_DIR / ".write_probe"
        probe.write_text("ok")
        mode = oct(probe.stat().st_mode & 0o777)
        probe.unlink()
        return _result("data", "Data folder", "ok",
                       f"{config.DATA_DIR} is writable (new files {mode})")
    except Exception as exc:  # noqa: BLE001
        return _result("data", "Data folder", "fail",
                       f"Cannot write to {config.DATA_DIR}: {exc}")


def check_ensembl():
    """Can the service itself reach Ensembl? (Needed to list and download.)"""
    import requests
    try:
        started = time.time()
        resp = requests.head(f"{config.ENSEMBL_FTP}/pub/", timeout=15,
                             allow_redirects=True)
        ms = int((time.time() - started) * 1000)
        if resp.status_code < 400:
            return _result("ensembl", "Ensembl reachable (from the service)", "ok",
                           f"HTTP {resp.status_code} in {ms} ms")
        return _result("ensembl", "Ensembl reachable (from the service)", "warn",
                       f"HTTP {resp.status_code} from {config.ENSEMBL_FTP}")
    except Exception as exc:  # noqa: BLE001
        return _result("ensembl", "Ensembl reachable (from the service)", "fail",
                       f"{exc}")


def check_container_network(pull=True):
    """DNS and outbound HTTPS as seen from inside a container.

    This is the check that matters for image builds: they install packages and
    fetch sources, so they need working name resolution and egress. Both are
    probed in a single short-lived container.
    """
    results = []
    try:
        client = docker_ops.get_client()
    except Exception as exc:  # noqa: BLE001
        return [_result("net", "Container network", "fail",
                        f"No Docker daemon: {exc}")]

    # Make sure the probe image is available.
    try:
        client.images.get(PROBE_IMAGE)
    except Exception:
        if not pull:
            return [_result("net", "Container network", "skip",
                            f"{PROBE_IMAGE} not present and pulling was skipped")]
        try:
            client.images.pull(PROBE_IMAGE)
        except Exception as exc:  # noqa: BLE001
            return [
                _result("registry", "Image registry reachable", "fail",
                        f"Could not pull {PROBE_IMAGE}: {exc}"),
                _result("net", "Container network", "skip",
                        "Skipped because the probe image is unavailable"),
            ]
    results.append(_result("registry", "Image registry reachable", "ok",
                           f"{PROBE_IMAGE} is available to the daemon"))

    script = (
        f"if getent hosts {PROBE_DNS_HOST} >/dev/null 2>&1; then echo dns:ok; "
        f"else echo dns:fail; fi; "
        f"if wget -q -T 10 -O /dev/null {PROBE_HTTPS_URL} 2>/dev/null; "
        f"then echo https:ok; else echo https:fail; fi"
    )
    try:
        out = client.containers.run(
            image=PROBE_IMAGE, command=["sh", "-c", script],
            remove=True, stdout=True, stderr=True,
        )
        text = (out or b"").decode(errors="replace")
    except Exception as exc:  # noqa: BLE001
        results.append(_result("net", "Container network", "fail",
                               f"Probe container failed: {exc}"))
        return results

    dns_ok = "dns:ok" in text
    https_ok = "https:ok" in text

    results.append(_result(
        "dns", "Name resolution inside containers",
        "ok" if dns_ok else "fail",
        f"Resolved {PROBE_DNS_HOST}" if dns_ok else
        f"Could not resolve {PROBE_DNS_HOST}. Image builds that install "
        f"packages (apt) or download sources will fail. Check the container "
        f"log for the 'nested DNS' lines to see which resolver was chosen.",
    ))
    results.append(_result(
        "https", "Outbound HTTPS inside containers",
        "ok" if https_ok else ("warn" if dns_ok else "fail"),
        f"Fetched {PROBE_HTTPS_URL}" if https_ok else
        f"Could not fetch {PROBE_HTTPS_URL} from a container.",
    ))
    return results


def run_all(pull=True):
    """Run every check and return {"checks": [...], "summary": ok|warn|fail}."""
    checks = [check_daemon()]
    if checks[0]["status"] == "ok":
        checks.extend(check_container_network(pull=pull))
    else:
        checks.append(_result("net", "Container network", "skip",
                              "Skipped: the Docker daemon is not reachable"))
    checks.append(check_ensembl())
    checks.append(check_data_dir())

    if any(c["status"] == "fail" for c in checks):
        summary = "fail"
    elif any(c["status"] in ("warn", "skip") for c in checks):
        summary = "warn"
    else:
        summary = "ok"
    return {"checks": checks, "summary": summary,
            "docker_host": config.DOCKER_HOST,
            "data_dir": str(config.DATA_DIR)}
