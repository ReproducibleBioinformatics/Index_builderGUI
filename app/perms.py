"""Keep everything the service writes deletable from the host.

The app and the tool containers run as root, so anything they create under the
data directory would otherwise be owned by root with restrictive permissions,
and the user on the host could not delete it.

Two mechanisms, both cheap:

  * permissions: directories become 0777 and files 0666, so any host user can
    remove them regardless of ownership. Combined with `umask 000` in the
    entrypoint, most files are already created this way; this pass fixes the
    ones written by tool containers.
  * ownership (optional): if HOST_UID / HOST_GID are set, files are chowned to
    that user. This is the tidy option on Linux and macOS, where bind-mounted
    files keep their numeric owner. On Windows it is unnecessary, so it is off
    by default.

Failures here are never fatal: a permissions pass that cannot run must not fail
an index that built correctly.
"""

import os

DIR_MODE = 0o777
FILE_MODE = 0o666


def _chown(path, uid, gid):
    if uid is None or gid is None:
        return
    try:
        os.chown(path, uid, gid)
    except (OSError, AttributeError):
        pass


def relax(path, host_uid=None, host_gid=None, log=None):
    """Recursively make `path` world-writable (and optionally chown it).

    Returns the number of entries touched. Never raises.
    """
    touched = 0
    try:
        if not os.path.exists(path):
            return 0

        def fix(target, is_dir):
            nonlocal touched
            try:
                os.chmod(target, DIR_MODE if is_dir else FILE_MODE)
                _chown(target, host_uid, host_gid)
                touched += 1
            except OSError:
                pass

        fix(path, os.path.isdir(path))
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for d in dirs:
                    fix(os.path.join(root, d), True)
                for f in files:
                    fix(os.path.join(root, f), False)
    except Exception as exc:  # noqa: BLE001 - never fail a good build over this
        if log:
            log(f"Note: could not adjust permissions on {path}: {exc}")
    return touched
