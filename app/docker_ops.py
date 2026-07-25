"""Docker operations.

The web app never runs aligners itself. It asks the Docker daemon at DOCKER_HOST
to build a tool image and then to run a short lived container that does the
indexing. Nothing here assumes a particular deployment: the daemon may be a
nested one (the Docker-in-Docker packaging) or simply the daemon of the machine
the service runs on. Only the entrypoint and compose file know the difference.

The data directory is bind-mounted into each tool container too, so it can read
the genomes the app downloaded and write the index back to the same place. The
mount's source (what the daemon resolves on its own side) and target (the path
the app's commands reference, config.DATA_DIR) are passed in separately by the
caller, because in socket mode the daemon runs outside this container and may
need a different string to reach the same directory (see config.DATA_HOST_BIND).
"""

import docker
from docker.errors import ImageNotFound, APIError

from config import DOCKER_HOST


def get_client():
    return docker.DockerClient(base_url=DOCKER_HOST, timeout=120)


def daemon_ready():
    try:
        get_client().ping()
        return True
    except Exception:
        return False


def image_exists(tag):
    try:
        get_client().images.get(tag)
        return True
    except ImageNotFound:
        return False
    except Exception:
        return False


def build_tool_image(context_dir, tag, buildargs=None, log=print):
    """Build a tool image from a Dockerfile context and stream the build log."""
    client = get_client()
    log(f"Building image {tag} from {context_dir}")
    # low-level build streams JSON events we can surface line by line
    stream = client.api.build(
        path=str(context_dir),
        tag=tag,
        buildargs=buildargs or {},
        rm=True,
        decode=True,
    )
    for event in stream:
        if "stream" in event:
            line = event["stream"].rstrip()
            if line:
                log(line)
        elif "error" in event:
            raise RuntimeError(event["error"].strip())
    log(f"Image {tag} ready")
    return tag


def run_indexing(image, command, mount_source, mount_target, log=print):
    """Run a detached container that performs the indexing and stream its logs.

    Returns the container exit code. `command` is a list, typically
    ["bash", "-lc", "<script>"]. `mount_source` is the data directory path as
    the daemon itself can resolve it (config.DATA_HOST_BIND); `mount_target` is
    the path the command string references (config.DATA_DIR). The two are the
    same string in the Docker-in-Docker packaging and in plain Linux/macOS
    socket mode; they differ on Docker Desktop for Windows.
    """
    client = get_client()
    container = client.containers.run(
        image=image,
        command=command,
        volumes={mount_source: {"bind": mount_target, "mode": "rw"}},
        detach=True,
        network_mode="none",  # indexing needs no network
    )
    try:
        for raw in container.logs(stream=True, follow=True):
            line = raw.decode(errors="replace").rstrip()
            if line:
                log(line)
        result = container.wait()
        return int(result.get("StatusCode", 1))
    finally:
        try:
            container.remove(force=True)
        except APIError:
            pass
