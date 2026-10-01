"""Run the indexing container through the JupyDo job queue (hub mode).

Instead of starting the tool container directly, the service submits it to the
job queue's internal API. The queue decides when it starts (same priority rules
and CPU/memory pool as users' %%job cells) and enforces the limits. The
container's output goes to a log file under the data directory, which is read
back here and streamed into this service's job log.
"""

import shlex
import time
import uuid

import requests

import config

POLL_S = 5


def _call(method, path, payload=None):
    try:
        res = requests.request(
            method, config.JOBQUEUE_URL + path, json=payload, timeout=30,
            headers={"Authorization": "token " + config.JOBQUEUE_TOKEN})
    except requests.RequestException as exc:
        raise RuntimeError(f"Job queue unreachable: {exc}") from None
    if not res.ok:
        try:
            msg = res.json().get("error")
        except ValueError:
            msg = res.text[:200]
        raise RuntimeError(f"Job queue: {msg} (HTTP {res.status_code})")
    return res.json()


def _tail(path, offset, log):
    """Log the lines appended to path since offset; return the new offset."""
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
    except FileNotFoundError:
        return offset
    # Only consume complete lines, keep a partial last line for the next read
    end = chunk.rfind(b"\n") + 1
    for line in chunk[:end].decode(errors="replace").splitlines():
        if line.strip():
            log(line)
    return offset + end


def run_indexing(image, command, mount_source, mount_target, owner, name, cpus, log):
    """Submit the indexing container, follow it, return its exit code."""
    log_file = config.JOBS_DIR / f"queue-{uuid.uuid4().hex[:12]}.log"
    shell = "{} > {} 2>&1".format(
        " ".join(shlex.quote(part) for part in command), shlex.quote(str(log_file)))

    job = _call("POST", "/internal/jobs", {
        "owner": owner or "genome-index",
        "source": "genome-index",
        "name": name,
        "image": image,
        "command": shell,
        "binds": [f"{mount_source}:{mount_target}:rw"],
        "cpus": cpus,
        "mem_gb": config.INDEX_MEM_GB,
        "walltime_min": config.INDEX_WALLTIME_MIN,
        "log": str(log_file),
    })
    job_id = job["id"]
    log(f"Submitted to the JupyDo job queue as job {job_id} "
        f"({job['cpus']:g} CPU, {job['mem_gb']:g} GB, time limit {config.INDEX_WALLTIME_MIN} min).")

    offset, last_state = 0, None
    try:
        while True:
            state = _call("GET", f"/internal/jobs/{job_id}")
            if state["state"] != last_state:
                if state["state"] == "pending":
                    log(f"Waiting in the job queue (position {state.get('position', '?')}).")
                elif state["state"] == "running":
                    log("Indexing started.")
                last_state = state["state"]
            offset = _tail(log_file, offset, log)
            if state["state"] not in ("pending", "running"):
                break
            time.sleep(POLL_S)
        offset = _tail(log_file, offset, log)
    finally:
        log_file.unlink(missing_ok=True)

    if state["state"] == "done":
        return 0
    detail = state.get("error") or f"exit code {state.get('exit_code')}"
    raise RuntimeError(f"Job queue job {job_id} ended as '{state['state']}' ({detail}).")
