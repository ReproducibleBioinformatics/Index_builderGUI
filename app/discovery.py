"""Folder analysis: the folder tree replaces a database.

Available tools and versions are whatever Dockerfiles exist under
tools/<tool>/<version>/. Existing indexes are whatever completed markers exist
under indexes/<tool>/<version>/<species>/<release>/. Tool requests are JSON
files under requests/. Nothing is stored in SQL.
"""

import json
import re
import shutil
import time
from pathlib import Path

from config import (
    TOOLS_DIR,
    GENOMES_DIR,
    INDEXES_DIR,
    REQUESTS_DIR,
    SEED_TOOLS_DIR,
)

_SAFE = re.compile(r"^[A-Za-z0-9._+-]+$")
INDEX_MARKER = "INDEX_COMPLETE.json"
GENOME_MARKER = "genome_meta.json"


def safe_name(value):
    """Reject anything that could escape the data tree."""
    value = (value or "").strip()
    if not value or value in (".", "..") or not _SAFE.match(value):
        raise ValueError(f"Unsafe name: {value!r}")
    return value


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
def seed_tools():
    """On first start, copy the baked-in tool files (Dockerfiles and
    index_command.txt) into the shared folder so both instances discover the
    same set. Never overwrites existing files (an admin may have edited them)."""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if not SEED_TOOLS_DIR.exists():
        return
    for src in SEED_TOOLS_DIR.rglob("*"):
        if not src.is_file():
            continue
        target = TOOLS_DIR / src.relative_to(SEED_TOOLS_DIR)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)


# --------------------------------------------------------------------------- #
# Tools and versions
# --------------------------------------------------------------------------- #
def list_tools():
    """Return {tool: [versions...]} discovered from the folder tree."""
    result = {}
    if not TOOLS_DIR.exists():
        return result
    for tool_dir in sorted(p for p in TOOLS_DIR.iterdir() if p.is_dir()):
        if tool_dir.name.startswith("_"):
            continue
        versions = []
        for ver_dir in sorted(p for p in tool_dir.iterdir() if p.is_dir()):
            if (ver_dir / "Dockerfile").exists():
                versions.append(ver_dir.name)
        if versions:
            result[tool_dir.name] = versions
    return result


def tool_dockerfile_dir(tool, version):
    return TOOLS_DIR / safe_name(tool) / safe_name(version)


def tool_image_tag(tool, version, prefix):
    return f"{prefix}-{safe_name(tool)}:{safe_name(version)}"


# --------------------------------------------------------------------------- #
# Genomes
# --------------------------------------------------------------------------- #
def genome_dir(species, release):
    return GENOMES_DIR / safe_name(species) / safe_name(str(release))


def genome_ready(species, release):
    marker = genome_dir(species, release) / GENOME_MARKER
    return marker.exists()


def read_genome_meta(species, release):
    marker = genome_dir(species, release) / GENOME_MARKER
    if marker.exists():
        return json.loads(marker.read_text())
    return None


# --------------------------------------------------------------------------- #
# Indexes
# --------------------------------------------------------------------------- #
def index_dir(tool, version, species, release):
    return (
        INDEXES_DIR
        / safe_name(tool)
        / safe_name(version)
        / safe_name(species)
        / safe_name(str(release))
    )


def index_exists(tool, version, species, release):
    return (index_dir(tool, version, species, release) / INDEX_MARKER).exists()


def read_index_meta(tool, version, species, release):
    marker = index_dir(tool, version, species, release) / INDEX_MARKER
    if marker.exists():
        return json.loads(marker.read_text())
    return None


def list_indexes():
    """Walk indexes/<tool>/<version>/<species>/<release>/ for completed markers."""
    out = []
    if not INDEXES_DIR.exists():
        return out
    for marker in INDEXES_DIR.rglob(INDEX_MARKER):
        try:
            out.append(json.loads(marker.read_text()))
        except Exception:
            continue
    out.sort(key=lambda m: m.get("completed_at", ""), reverse=True)
    return out


# --------------------------------------------------------------------------- #
# Tool requests (folder based inbox)
# --------------------------------------------------------------------------- #
def save_request(tool, version, notes, requested_by):
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    rid = f"{int(time.time() * 1000)}"
    payload = {
        "id": rid,
        "tool": tool.strip(),
        "version": version.strip(),
        "notes": (notes or "").strip(),
        "requested_by": requested_by,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "pending",
    }
    (REQUESTS_DIR / f"{rid}.json").write_text(json.dumps(payload, indent=2))
    return payload


def list_requests(status=None):
    out = []
    if not REQUESTS_DIR.exists():
        return out
    for f in REQUESTS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        if status is None or data.get("status") == status:
            out.append(data)
    out.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return out


def get_request(rid):
    f = REQUESTS_DIR / f"{safe_name(rid)}.json"
    if f.exists():
        return json.loads(f.read_text())
    return None


def mark_request_fulfilled(rid):
    src = REQUESTS_DIR / f"{safe_name(rid)}.json"
    if not src.exists():
        return None
    data = json.loads(src.read_text())
    data["status"] = "fulfilled"
    data["fulfilled_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    dest = REQUESTS_DIR / "fulfilled" / f"{safe_name(rid)}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2))
    src.unlink()
    return data


# --------------------------------------------------------------------------- #
# Adding a tool by pasting a Dockerfile (admin action)
# --------------------------------------------------------------------------- #
def add_tool_dockerfile(tool, version, dockerfile_text):
    """Create tools/<tool>/<version>/Dockerfile from pasted text.

    Folders are created automatically. Returns the Dockerfile path. Overwrites
    an existing Dockerfile for the same tool + version on purpose, so an admin
    can correct a broken one.
    """
    tool = safe_name(tool).lower()
    version = safe_name(version)
    text = (dockerfile_text or "").strip()
    if not text:
        raise ValueError("The Dockerfile text is empty.")
    if not text.upper().startswith("FROM") and "\nFROM" not in text.upper():
        raise ValueError("That does not look like a Dockerfile (no FROM line).")
    out_dir = tool_dockerfile_dir(tool, version)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "Dockerfile"
    out_file.write_text(text if text.endswith("\n") else text + "\n")
    return out_file


def read_tool_dockerfile(tool, version):
    path = tool_dockerfile_dir(tool, version) / "Dockerfile"
    return path.read_text() if path.exists() else None


# --------------------------------------------------------------------------- #
# Per-tool index command (stored next to the tool, shared across its versions)
# --------------------------------------------------------------------------- #
def tool_command_path(tool):
    return TOOLS_DIR / safe_name(tool) / "index_command.txt"


def read_tool_command(tool):
    try:
        p = tool_command_path(tool)
    except ValueError:
        return None
    return p.read_text() if p.exists() else None


def save_tool_command(tool, command):
    """Store the index command template for a tool. An empty command clears it."""
    tdir = TOOLS_DIR / safe_name(tool)
    tdir.mkdir(parents=True, exist_ok=True)
    p = tdir / "index_command.txt"
    command = (command or "").strip()
    if command:
        p.write_text(command if command.endswith("\n") else command + "\n")
    elif p.exists():
        p.unlink()
    return p


# --------------------------------------------------------------------------- #
# Per-tool parameters (name + default), shown as editable fields in the form
# --------------------------------------------------------------------------- #
_PARAM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def tool_params_path(tool):
    return TOOLS_DIR / safe_name(tool) / "params.json"


def read_tool_params(tool):
    """Return [{name, default}, ...] for a tool, or []."""
    try:
        p = tool_params_path(tool)
    except ValueError:
        return []
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        name = str(item.get("name", "")).strip()
        if name:
            out.append({"name": name, "default": str(item.get("default", ""))})
    return out


def save_tool_params(tool, params_list):
    """Write params.json for a tool. An empty list clears it."""
    tdir = TOOLS_DIR / safe_name(tool)
    tdir.mkdir(parents=True, exist_ok=True)
    p = tdir / "params.json"
    clean = [
        {"name": d["name"], "default": str(d.get("default", ""))}
        for d in params_list if d.get("name")
    ]
    if clean:
        p.write_text(json.dumps(clean, indent=2))
    elif p.exists():
        p.unlink()
    return p


def parse_params_text(text):
    """Parse 'name=default' lines into [{name, default}]. Blank lines and lines
    starting with # are ignored. Raises ValueError on an invalid name."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, default = line.split("=", 1)
        else:
            name, default = line, ""
        name = name.strip()
        if not _PARAM_NAME_RE.match(name):
            raise ValueError(
                f"Invalid parameter name '{name}' (use letters, digits, "
                f"underscore; must start with a letter or underscore)."
            )
        out.append({"name": name, "default": default.strip()})
    return out


def template_for(tool, version):
    """A ready to edit starting Dockerfile for the editor. It shows the tagged
    GitHub pattern (binary or compile) with the tool name and version filled in.
    Nothing is written to disk here, it only feeds the text editor."""
    tool_l = (tool or "").strip().lower() or "TOOL"
    version = (version or "").strip() or "VERSION"
    template = (SEED_TOOLS_DIR / "_template" / "Dockerfile.tmpl")
    if not template.exists():
        template = (TOOLS_DIR / "_template" / "Dockerfile.tmpl")
    if template.exists():
        text = template.read_text()
        text = text.replace("__VERSION__", version)
        return text.replace("__TOOL__", tool_l)
    # Inline fallback if the template file is missing.
    return (
        "# Edit before adding. No conda/mamba: use a tagged GitHub release.\n"
        "# The image only needs the tool on PATH; the indexing command is\n"
        "# supplied at run time.\n"
        "FROM debian:bookworm-slim\n"
        f"ARG TOOL_VERSION={version}\n"
        f"# ADD https://github.com/ORG/REPO/releases/download/v${{TOOL_VERSION}}/{tool_l}-linux-x86_64 /usr/local/bin/{tool_l}\n"
        f"# RUN chmod +x /usr/local/bin/{tool_l}\n"
    )


# --------------------------------------------------------------------------- #
# Removing an index (admin action)
# --------------------------------------------------------------------------- #
def remove_index(tool, version, species, release):
    """Delete an index directory and everything under it. Returns True if it
    existed. Refuses to touch anything outside INDEXES_DIR."""
    target = index_dir(tool, version, species, release).resolve()
    root = INDEXES_DIR.resolve()
    if root not in target.parents and target != root:
        raise ValueError("Refusing to remove a path outside the index tree.")
    if not target.exists():
        return False
    shutil.rmtree(target)
    # Tidy now empty parent folders (tool/version, tool) without touching the root.
    for parent in (target.parent, target.parent.parent):
        try:
            if parent != root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
    return True
