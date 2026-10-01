"""Flask web application.

Flask + waitress keeps the whole stack pure Python, so it installs from wheels
on any base image without needing a C or Rust toolchain.

No login and no sessions: access control is left to whatever you put in front of
the ports. The running instance's role (config.APP_ROLE) decides what the UI and
API expose. One instance runs as admin on 8888 and one as user on 8000, both
sharing the same data volume and the same inner Docker daemon.
"""

from flask import Flask, g, request, jsonify, render_template

import config
import diagnostics
import discovery
import docker_ops
import ensembl
import indexing
import jobs
import perms
import service

app = Flask(__name__, static_folder="static", template_folder="templates")

if config.HUB_MODE:
    import hubauth  # login through JupyterHub, role from the hub admin flag
    hubauth.init_app(app)

# Startup (Flask has no async startup hook, so run it once at import). Both the
# admin and user processes run this; every step is idempotent.
config.ensure_dirs()
discovery.seed_tools()
jobs.load_persisted()

# Repair anything written by an earlier run (before the umask fix, or by a tool
# container) so the host can always delete ./data. Cheap and never fatal.
perms.relax(config.DATA_DIR, config.HOST_UID, config.HOST_GID)


def _is_admin():
    """Admin rights: the hub admin flag in hub mode, else the instance role."""
    if config.HUB_MODE:
        return bool(g.hub_user.get("admin"))
    return config.is_admin_instance()


def _username():
    """The logged-in hub user in hub mode, else None."""
    return g.hub_user["name"] if config.HUB_MODE else None


def _admin_only():
    """Return a (json, 403) tuple if this instance is not the admin one, else
    None."""
    if not _is_admin():
        return jsonify(
            {"error": "This action is only available on the admin instance."}
        ), 403
    return None


def _body():
    return request.get_json(force=True, silent=True) or {}


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
@app.route("/")
def home():
    return render_template(
        "index.html",
        role="admin" if _is_admin() else "user",
        is_admin=_is_admin(),
        docker_ok=docker_ops.daemon_ready(),
        dna_pref=", ".join(config.DNA_PREFERENCE),
    )


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
@app.route("/api/tools")
def api_tools():
    tools = discovery.list_tools()
    prefix = config.TOOL_IMAGE_PREFIX
    all_jobs = jobs.list_jobs()
    images = []
    for tool, versions in tools.items():
        for version in versions:
            tag = discovery.tool_image_tag(tool, version, prefix)
            built = docker_ops.image_exists(tag)
            images.append(
                {
                    "tool": tool,
                    "version": version,
                    "image": tag,
                    "built": built,
                    "status": _tool_status(tool, version, built, all_jobs),
                }
            )
    return {"tools": tools, "images": images}


def _tool_status(tool, version, built, all_jobs):
    """built | building | failed | not-built, from the image plus build jobs."""
    if built:
        return "built"
    newest = None
    for j in all_jobs:  # newest first
        if j.get("kind") != "build":
            continue
        meta = j.get("meta", {})
        if meta.get("tool") == tool and str(meta.get("version")) == str(version):
            if j.get("status") in ("queued", "running"):
                return "building"
            if newest is None:
                newest = j.get("status")
    if newest in ("failed", "interrupted"):
        return "failed"
    return "not-built"


@app.route("/api/indexes")
def api_indexes():
    return {"indexes": discovery.list_indexes()}


@app.route("/api/species")
def api_species():
    q = request.args.get("q", "")
    return {"species": ensembl.search_species(q)}


@app.route("/api/releases")
def api_releases():
    species = request.args.get("species", "").strip()
    if species:
        return {"species": species,
                "releases": ensembl.releases_for_species(species)}
    return {"releases": ensembl.list_releases()}


@app.route("/api/resolve", methods=["POST"])
def api_resolve():
    body = _body()
    species = body.get("species", "")
    release = str(body.get("release", ""))
    tool = (body.get("tool", "") or "").strip().lower()
    try:
        info = ensembl.resolve(species, release)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 400
    info["genome_ready"] = discovery.genome_ready(species, release)
    info["fasta_ok"] = bool(info.get("fasta"))
    info["gtf_ok"] = bool(info.get("gtf"))

    # Whether the chosen tool actually needs the annotation, so the interface can
    # turn a missing GTF into either a harmless note or a blocking problem.
    needs_gtf = False
    if tool:
        template = discovery.read_tool_command(tool) or ""
        needs_gtf = "{gtf}" in template
    info["tool_needs_gtf"] = needs_gtf
    if needs_gtf and not info["gtf_ok"]:
        info["blocking"] = (
            f"{tool} needs an annotation GTF and none is available for this "
            f"organism and release."
        )
    return info


# --------------------------------------------------------------------------- #
# Index generation
# --------------------------------------------------------------------------- #
@app.route("/api/index", methods=["POST"])
def api_index():
    body = _body()
    tool = body.get("tool", "")
    version = body.get("version", "")
    species = body.get("species", "")
    release = str(body.get("release", ""))
    # Forcing a rebuild over an existing index is an admin-only capability, so
    # the user instance ignores force_rebuild even if it is sent.
    force = bool(body.get("force_rebuild", False)) and _is_admin()

    try:
        for value in (tool, version, species, release):
            discovery.safe_name(value)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if version not in discovery.list_tools().get(tool, []):
        return jsonify(
            {"error": f"Tool {tool} {version} is not available. "
                      f"Add or request it in the Tools tab first."}
        ), 400

    if discovery.index_exists(tool, version, species, release) and not force:
        meta = discovery.read_index_meta(tool, version, species, release)
        return {
            "status": "already-exists",
            "message": f"Index already exists for {tool} {version} / "
                       f"{species} {release}.",
            "meta": meta,
        }

    # Resolve tool parameters: submitted value or the tool's default, validated.
    submitted = body.get("params", {}) or {}
    resolved = {}
    for p in discovery.read_tool_params(tool):
        val = str(submitted.get(p["name"], p["default"]))
        if not indexing.valid_param_value(val):
            return jsonify({"error":
                f"Invalid value for parameter '{p['name']}': {val!r}. "
                "Allowed characters: letters, digits and . _ , : + -"}), 400
        resolved[p["name"]] = val

    title = f"index {tool} {version} :: {species} {release}"
    job_id = jobs.create_job(
        "index", title,
        meta={"tool": tool, "version": version,
              "species": species, "release": release, "params": resolved},
    )
    owner = _username()  # read now: the worker thread has no request context
    jobs.submit(
        job_id,
        lambda logger: service.run_index_job(
            tool, version, species, release, force, resolved, logger, owner=owner
        ),
    )
    return {"status": "queued", "job_id": job_id}


@app.route("/api/index/remove", methods=["POST"])
def api_index_remove():
    guard = _admin_only()
    if guard:
        return guard
    body = _body()
    tool = body.get("tool", "")
    version = body.get("version", "")
    species = body.get("species", "")
    release = str(body.get("release", ""))
    try:
        removed = discovery.remove_index(tool, version, species, release)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not removed:
        return jsonify({"error": "No such index."}), 404
    return {"status": "removed",
            "index": f"{tool}/{version}/{species}/{release}"}


# --------------------------------------------------------------------------- #
# Diagnostics (on demand only; nothing here runs during a build or an index)
# --------------------------------------------------------------------------- #
@app.route("/api/diagnostics")
def api_diagnostics():
    pull = request.args.get("pull", "1") != "0"
    return diagnostics.run_all(pull=pull)


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
@app.route("/api/jobs")
def api_jobs():
    return {"jobs": jobs.list_jobs()}


@app.route("/api/jobs/<job_id>")
def api_job(job_id):
    job = jobs.get_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return job


# --------------------------------------------------------------------------- #
# Tools: template, view, add, build
# --------------------------------------------------------------------------- #
@app.route("/api/tools/template")
def api_tool_template():
    tool = request.args.get("tool", "")
    version = request.args.get("version", "")
    return {"dockerfile": discovery.template_for(tool, version)}


@app.route("/api/tools/params")
def api_tool_params():
    tool = request.args.get("tool", "")
    return {"params": discovery.read_tool_params(tool)}


@app.route("/api/tools/dockerfile")
def api_tool_dockerfile():
    tool = request.args.get("tool", "")
    version = request.args.get("version", "")
    try:
        text = discovery.read_tool_dockerfile(tool, version)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if text is None:
        return jsonify({"error": "No Dockerfile for that tool/version."}), 404
    return {"dockerfile": text}


@app.route("/api/tools/add", methods=["POST"])
def api_tool_add():
    guard = _admin_only()
    if guard:
        return guard
    body = _body()
    tool = body.get("tool", "")
    version = body.get("version", "")
    dockerfile = body.get("dockerfile", "")
    command = body.get("command", "")
    params_text = body.get("params", "")
    build_now = bool(body.get("build", False))
    tool_l = tool.strip().lower()

    # Parse the tool's parameter declarations (name=default lines).
    try:
        params_list = discovery.parse_params_text(params_text)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Every tool needs an index command. It may be provided now or already
    # stored (the shipped aligners come with theirs seeded).
    if tool_l:
        has_command = bool(command and command.strip()) or \
            discovery.read_tool_command(tool_l) is not None
        if not has_command:
            return jsonify({"error":
                "This tool has no index command yet, so you must provide one. "
                "Placeholders: " + " ".join(indexing.COMMAND_PLACEHOLDERS)
                + ". Example for minimap2: minimap2 -t {threads} "
                "-d {index_dir}/genome.mmi {fasta}"}), 400

    # If a command is provided, every placeholder it uses must be a system one
    # or a declared parameter, otherwise it would be left unfilled.
    if command and command.strip():
        used = indexing.placeholders_in(command)
        declared = {p["name"] for p in params_list} | indexing.SYSTEM_PLACEHOLDERS
        missing = sorted(used - declared)
        if missing:
            return jsonify({"error":
                "The command uses placeholders that are neither system "
                "placeholders nor declared parameters: "
                + ", ".join("{" + m + "}" for m in missing)
                + ". Declare them in Parameters (name=default)."}), 400

    try:
        discovery.add_tool_dockerfile(tool, version, dockerfile)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if command and command.strip():
        discovery.save_tool_command(tool_l, command)
    if (command and command.strip()) or (params_text and params_text.strip()):
        discovery.save_tool_params(tool_l, params_list)

    result = {"status": "added", "tool": tool_l, "version": version.strip()}
    if build_now:
        result["job_id"] = _queue_build(tool_l, version.strip())
    return result


@app.route("/api/tools/build", methods=["POST"])
def api_build():
    guard = _admin_only()
    if guard:
        return guard
    body = _body()
    tool = body.get("tool", "")
    version = body.get("version", "")
    try:
        discovery.safe_name(tool)
        discovery.safe_name(version)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if version not in discovery.list_tools().get(tool, []):
        return jsonify({"error": f"No Dockerfile for {tool} {version}."}), 400
    return {"status": "queued", "job_id": _queue_build(tool, version)}


def _queue_build(tool, version):
    job_id = jobs.create_job("build", f"build {tool} {version}",
                             meta={"tool": tool, "version": version})
    jobs.submit(job_id,
                lambda logger: service.run_build_job(tool, version, logger))
    return job_id


# --------------------------------------------------------------------------- #
# Requests: users create, admin fulfils by pasting a Dockerfile
# --------------------------------------------------------------------------- #
@app.route("/api/tool-request", methods=["POST"])
def api_tool_request():
    body = _body()
    tool = body.get("tool", "")
    version = body.get("version", "")
    notes = body.get("notes", "")
    if not tool.strip() or not version.strip():
        return jsonify({"error": "Tool and version are required."}), 400
    payload = discovery.save_request(tool, version, notes, _username() or config.APP_ROLE)
    return {"status": "saved", "request": payload}


@app.route("/api/requests")
def api_requests():
    return {
        "pending": discovery.list_requests(status="pending"),
        "fulfilled": discovery.list_requests(status="fulfilled"),
    }


@app.route("/api/requests/fulfil", methods=["POST"])
def api_request_fulfil():
    guard = _admin_only()
    if guard:
        return guard
    body = _body()
    rid = body.get("id", "")
    dockerfile = body.get("dockerfile", "")
    command = body.get("command", "")
    params_text = body.get("params", "")
    build_now = bool(body.get("build", True))
    req = discovery.get_request(rid)
    if not req:
        return jsonify({"error": "Request not found."}), 404

    try:
        params_list = discovery.parse_params_text(params_text)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    tool_l = req["tool"].strip().lower()
    has_command = bool(command and command.strip()) or \
        discovery.read_tool_command(tool_l) is not None
    if not has_command:
        return jsonify({"error":
            "This tool has no index command yet, so you must provide one. "
            "Placeholders: " + " ".join(indexing.COMMAND_PLACEHOLDERS) + "."}), 400

    if command and command.strip():
        used = indexing.placeholders_in(command)
        declared = {p["name"] for p in params_list} | indexing.SYSTEM_PLACEHOLDERS
        missing = sorted(used - declared)
        if missing:
            return jsonify({"error":
                "The command uses undeclared placeholders: "
                + ", ".join("{" + m + "}" for m in missing)
                + ". Declare them in Parameters (name=default)."}), 400

    try:
        discovery.add_tool_dockerfile(req["tool"], req["version"], dockerfile)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if command and command.strip():
        discovery.save_tool_command(tool_l, command)
    if (command and command.strip()) or (params_text and params_text.strip()):
        discovery.save_tool_params(tool_l, params_list)
    discovery.mark_request_fulfilled(rid)

    result = {"status": "fulfilled", "tool": req["tool"],
              "version": req["version"]}
    if build_now:
        result["job_id"] = _queue_build(tool_l, req["version"].strip())
    return result
