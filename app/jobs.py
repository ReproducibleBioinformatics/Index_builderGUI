"""Job registry and background runner.

Both GUIs (admin and user) run as two processes inside the one container. To let
either GUI see every job with its live log, job state is written to disk on every
update and reads come from disk. The owning process keeps an in-memory copy only
so its worker thread can accumulate and persist the log. There is no broker and
no database, just JSON files on the shared volume.
"""

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from config import JOBS_DIR, JOB_WORKERS

_executor = ThreadPoolExecutor(max_workers=JOB_WORKERS)
_jobs = {}                 # jobs owned (created) by this process
_lock = threading.Lock()


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _path(job_id):
    return JOBS_DIR / f"{job_id}.json"


def _persist(job):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(job["id"]).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, indent=2))
    tmp.replace(_path(job["id"]))


def load_persisted():
    """Runs once at startup. Any job still marked running/queued on disk is a
    leftover from a previous container run (its thread is gone), so mark it
    interrupted. Safe to run from both processes."""
    if not JOBS_DIR.exists():
        return
    for f in sorted(JOBS_DIR.glob("*.json")):
        try:
            job = json.loads(f.read_text())
        except Exception:
            continue
        if job.get("status") in ("queued", "running"):
            job["status"] = "interrupted"
            job["updated_at"] = _now()
            try:
                _persist(job)
            except Exception:
                pass


def create_job(kind, title, meta=None):
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "kind": kind,          # "index" | "build"
        "title": title,
        "status": "queued",
        "log": [],
        "meta": meta or {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _lock:
        _jobs[job_id] = job
        _persist(job)
    return job_id


def append_log(job_id, message):
    stamp = time.strftime("%H:%M:%S", time.gmtime())
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["log"].append(f"[{stamp}] {message}")
        job["updated_at"] = _now()
        _persist(job)


def set_status(job_id, status):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["status"] = status
        job["updated_at"] = _now()
        _persist(job)


def get_job(job_id):
    """Read from disk (fresh across processes), fall back to in-memory."""
    p = _path(job_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    with _lock:
        job = _jobs.get(job_id)
        return json.loads(json.dumps(job)) if job else None


def list_jobs(limit=50):
    """List all jobs from disk so both GUIs see the same set."""
    out = []
    if JOBS_DIR.exists():
        for f in JOBS_DIR.glob("*.json"):
            try:
                out.append(json.loads(f.read_text()))
            except Exception:
                continue
    out.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return out[:limit]


def submit(job_id, func):
    """Run func(logger) in the pool, driving the job's status transitions.

    func may return a terminal status string (for example "already-exists");
    if it returns nothing the job is marked "completed".
    """

    def runner():
        set_status(job_id, "running")

        def logger(message):
            append_log(job_id, str(message))

        try:
            result = func(logger)
            final = result if isinstance(result, str) and result else "completed"
            set_status(job_id, final)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            append_log(job_id, f"ERROR: {exc}")
            set_status(job_id, "failed")

    _executor.submit(runner)
