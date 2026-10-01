"use strict";

const IS_ADMIN = document.body.dataset.admin === "true";
// URL prefix when served under a path (e.g. /services/genome-index in JupyDo).
const BASE = document.body.dataset.base || "";

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

async function api(path, opts = {}) {
  const res = await fetch(BASE + path, { headers: { "Content-Type": "application/json" }, ...opts });
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

let toastTimer = null;
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("err", isError);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3600);
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// --------------------------------------------------------------------------- //
// Theme: two independent axes, both persisted.
//   mode    -> light | dark            (falls back to the OS preference)
//   palette -> default | deuteranopia | protanopia | tritanopia | monochrome
// --------------------------------------------------------------------------- //
const MODE_KEY = "gis-mode";
const PALETTE_KEY = "gis-palette";

function readStored(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}
function writeStored(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* private mode */ }
}

function initTheme() {
  let mode = readStored(MODE_KEY);
  if (!mode) {
    const prefersDark = window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    mode = prefersDark ? "dark" : "light";
  }
  const palette = readStored(PALETTE_KEY) || "default";

  document.documentElement.setAttribute("data-theme", mode);
  document.documentElement.setAttribute("data-palette", palette);

  const modeSel = $("#mode-select");
  const palSel = $("#palette-select");
  modeSel.value = mode;
  palSel.value = palette;

  modeSel.addEventListener("change", () => {
    document.documentElement.setAttribute("data-theme", modeSel.value);
    writeStored(MODE_KEY, modeSel.value);
  });
  palSel.addEventListener("change", () => {
    document.documentElement.setAttribute("data-palette", palSel.value);
    writeStored(PALETTE_KEY, palSel.value);
  });
}

// --------------------------------------------------------------------------- //
// Role visibility + tabs
// --------------------------------------------------------------------------- //
function applyRoleVisibility() {
  const hideSel = IS_ADMIN ? "[data-user-only]" : "[data-admin-only]";
  $$(hideSel).forEach((el) => { el.style.display = "none"; });
}

function showTab(name) {
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tabpane").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
  if (name === "tools") loadToolsTable();
  if (name === "indexes") loadIndexesTable();
  if (name === "requests") loadRequests();
}

function initTabs() {
  $$(".tab").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });
}

// --------------------------------------------------------------------------- //
// Generate: tools, versions, params
// --------------------------------------------------------------------------- //
let TOOLS = {};

async function loadTools() {
  const data = await api("/api/tools");
  TOOLS = data.tools || {};
  const sel = $("#tool");
  const names = Object.keys(TOOLS);
  if (!names.length) {
    sel.innerHTML = '<option value="">No tools available</option>';
    $("#version").innerHTML = '<option value="">Add a tool first</option>';
    return;
  }
  const keep = sel.value;
  sel.innerHTML = '<option value="">Select a tool</option>' +
    names.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join("");
  if (keep && names.includes(keep)) { sel.value = keep; }
  sel.onchange = () => {
    populateVersions(sel.value);
    loadToolParams(sel.value);
    invalidateCheck("Tool changed. Run Check sources again.");
  };
  $("#version").addEventListener("change", () =>
    invalidateCheck("Version changed. Run Check sources again."));
  $("#release").addEventListener("change", () =>
    invalidateCheck("Release changed. Run Check sources again."));
}

function populateVersions(tool) {
  const sel = $("#version");
  const versions = TOOLS[tool] || [];
  sel.innerHTML = versions.length
    ? versions.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join("")
    : '<option value="">Select a tool first</option>';
}

async function loadToolParams(tool) {
  const section = $("#params-section");
  const grid = $("#params-grid");
  if (!tool) { section.style.display = "none"; grid.innerHTML = ""; return; }
  try {
    const data = await api("/api/tools/params?tool=" + encodeURIComponent(tool));
    const params = data.params || [];
    if (!params.length) { section.style.display = "none"; grid.innerHTML = ""; return; }
    grid.innerHTML = params.map((p) => `
      <div class="param-item">
        <label>${escapeHtml(p.name)}</label>
        <input type="text" class="param-input" data-param="${escapeHtml(p.name)}"
               value="${escapeHtml(p.default)}" />
      </div>`).join("");
    section.style.display = "";
  } catch (e) { section.style.display = "none"; grid.innerHTML = ""; }
}

function collectParams() {
  const params = {};
  $$(".param-input").forEach((i) => { params[i.dataset.param] = i.value; });
  return params;
}

// --------------------------------------------------------------------------- //
// Releases (organism dependent)
// --------------------------------------------------------------------------- //
function resetReleases(message) {
  const sel = $("#release");
  sel.innerHTML = `<option value="">${escapeHtml(message)}</option>`;
  sel.disabled = true;
}

async function loadReleasesForSpecies(species) {
  const sel = $("#release");
  sel.disabled = true;
  sel.innerHTML = '<option value="">Loading releases…</option>';
  try {
    const data = await api("/api/releases?species=" + encodeURIComponent(species));
    const releases = data.releases || [];
    if (!releases.length) {
      sel.innerHTML = '<option value="">Not available on Ensembl (main)</option>';
      return;
    }
    sel.innerHTML = releases.map((r) => `<option value="${r}">${r}</option>`).join("");
    sel.disabled = false;
  } catch (e) {
    sel.innerHTML = '<option value="">Could not load releases</option>';
  }
}

// --------------------------------------------------------------------------- //
// Organism autocomplete
// --------------------------------------------------------------------------- //
function initOrganismSearch() {
  const input = $("#organism");
  const ac = $("#organism-ac");
  const hidden = $("#species");
  let items = [];
  let active = -1;

  // The list is position: fixed, so its coordinates are taken from the input.
  // Without this the scrolling form body would clip it.
  const place = () => {
    const r = input.getBoundingClientRect();
    ac.style.left = r.left + "px";
    ac.style.top = r.bottom + "px";
    ac.style.width = r.width + "px";
  };

  const render = () => {
    if (!items.length) { ac.classList.remove("open"); ac.innerHTML = ""; return; }
    ac.innerHTML = items.map((sp, i) => `
      <div class="ac-item ${i === active ? "active" : ""}" data-i="${i}">
        ${escapeHtml(sp.name)}
        <span class="sub">${escapeHtml(sp.display_name || "")}${sp.assembly ? " &middot; " + escapeHtml(sp.assembly) : ""}</span>
      </div>`).join("");
    place();
    ac.classList.add("open");
    $$(".ac-item", ac).forEach((el) => {
      el.addEventListener("mousedown", (e) => {
        e.preventDefault();
        choose(items[parseInt(el.dataset.i, 10)]);
      });
    });
  };

  // Keep the list glued to the input while anything scrolls or resizes.
  const track = () => { if (ac.classList.contains("open")) place(); };
  const body = $("#generate-body");
  if (body) body.addEventListener("scroll", track);
  window.addEventListener("resize", track);

  const choose = (sp) => {
    input.value = sp.name;
    hidden.value = sp.name;
    items = []; active = -1;
    ac.classList.remove("open");
    loadReleasesForSpecies(sp.name);
    invalidateCheck("Organism changed. Run Check sources again.");
  };

  const search = debounce(async () => {
    const q = input.value.trim();
    hidden.value = "";
    resetReleases("Choose an organism first");
    invalidateCheck("Organism changed. Run Check sources again.");
    if (q.length < 2) { items = []; ac.classList.remove("open"); return; }
    try {
      const data = await api("/api/species?q=" + encodeURIComponent(q));
      items = data.species || []; active = -1; render();
    } catch (e) { /* offline: stay quiet */ }
  }, 280);

  input.addEventListener("input", search);
  input.addEventListener("keydown", (e) => {
    if (!items.length) return;
    if (e.key === "ArrowDown") { active = Math.min(active + 1, items.length - 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); render(); e.preventDefault(); }
    else if (e.key === "Enter" && active >= 0) { choose(items[active]); e.preventDefault(); }
    else if (e.key === "Escape") { items = []; ac.classList.remove("open"); }
  });
  input.addEventListener("blur", () => setTimeout(() => ac.classList.remove("open"), 150));
}

// --------------------------------------------------------------------------- //
// Resolve + submit
// --------------------------------------------------------------------------- //
function selectedSpecies() {
  const sp = $("#species").value.trim();
  if (sp) return sp;
  return $("#organism").value.trim().toLowerCase().replace(/\s+/g, "_");
}

// The Generate button is gated on a successful source check: you must confirm
// that Ensembl actually has the FASTA before a job can be queued. The check is
// tied to the exact tool/version/organism/release it was run for, so changing
// any of them invalidates it.
let checkedKey = null;

function currentKey() {
  return [$("#tool").value, $("#version").value, selectedSpecies(), $("#release").value].join("|");
}

function invalidateCheck(message) {
  checkedKey = null;
  updateSubmitState(message);
}

function updateSubmitState(message) {
  const btn = $("#btn-submit");
  const note = $("#submit-note");
  const ok = checkedKey !== null && checkedKey === currentKey();
  btn.disabled = !ok;
  if (note) {
    note.textContent = ok ? "" : (message || "Run Check sources first.");
    note.style.display = ok ? "none" : "";
  }
}

async function checkSources() {
  const tool = $("#tool").value;
  const species = selectedSpecies();
  const release = $("#release").value;
  const box = $("#resolve-preview");
  if (!species || !release) {
    box.className = "preview err";
    box.textContent = "Select an organism (from the list) and a release first.";
    invalidateCheck("Select an organism and a release, then check.");
    return;
  }
  box.className = "preview";
  box.textContent = "Resolving from Ensembl…";
  const btn = $("#btn-check");
  btn.disabled = true;
  try {
    const info = await api("/api/resolve", {
      method: "POST", body: JSON.stringify({ species, release, tool }),
    });

    const rows = [
      ["species", escapeHtml(info.species)],
      ["assembly", escapeHtml(info.assembly)],
      ["dna type", escapeHtml(info.dna_type)],
      ["fasta", escapeHtml(info.fasta.filename)],
      ["gtf", info.gtf_ok ? escapeHtml(info.gtf.filename) : "not available"],
      ["on disk", info.genome_ready ? "yes (cached)" : "no (will download)"],
    ];
    let html = rows.map(([k, v]) =>
      `<div><span class="k">${k}</span> <span class="v">${v}</span></div>`).join("");

    if (info.blocking) {
      html += `<div class="note note-bad">BLOCKED &mdash; ${escapeHtml(info.blocking)}</div>`;
      box.className = "preview err";
      box.innerHTML = html;
      invalidateCheck(escapeHtml(info.blocking));
      return;
    }
    if (!info.gtf_ok) {
      html += `<div class="note note-warn">WARNING &mdash; no annotation GTF for this
               combination. Fine for DNA-only tools (BWA, Bowtie2, minimap2); tools that
               need annotation (STAR, HISAT2) cannot use it.</div>`;
    }
    box.className = "preview";
    box.innerHTML = html;

    // FASTA present and nothing blocking: the check passes.
    checkedKey = currentKey();
    updateSubmitState();
    toast(info.gtf_ok ? "Sources found. You can generate the index."
                      : "FASTA found, no GTF (see the warning).");
  } catch (e) {
    box.className = "preview err";
    box.textContent = "Could not resolve: " + e.message;
    invalidateCheck("The source check failed; fix it and check again.");
  } finally {
    btn.disabled = false;
  }
}

async function submitIndex() {
  const tool = $("#tool").value;
  const version = $("#version").value;
  const species = selectedSpecies();
  const release = $("#release").value;
  const forceEl = $("#force");
  const force = forceEl ? forceEl.checked : false;

  if (!tool || !version) { toast("Pick a tool and version.", true); return; }
  if (!species) { toast("Pick an organism from the list.", true); return; }
  if (!release) { toast("Pick a release.", true); return; }

  const btn = $("#btn-submit");
  btn.disabled = true;
  try {
    const res = await api("/api/index", {
      method: "POST",
      body: JSON.stringify({ tool, version, species, release, force_rebuild: force, params: collectParams() }),
    });
    if (res.status === "already-exists") {
      toast("Index already exists. Nothing to rebuild.");
      $("#resolve-preview").className = "preview";
      $("#resolve-preview").innerHTML =
        `<div><span class="k">status</span> <span class="v">already exists (${escapeHtml(res.meta.completed_at)})</span></div>`;
    } else {
      toast("Index job queued. See Jobs.");
      invalidateCheck("Job queued. Run Check sources again for another build.");
      pollJobs(true);
    }
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

// --------------------------------------------------------------------------- //
// Jobs
// --------------------------------------------------------------------------- //
const openJobs = new Set();
let jobsTimer = null;
let prevBuildActive = false;

function statusClass(s) { return "s-" + String(s).replace(/[^a-z-]/g, ""); }

// Jobs are re-fetched every couple of seconds. Rebuilding the markup each time
// would reset every open log to the top, which is why scrolling down used to
// snap back. Instead each job's node is created once and then updated in place:
// only new log lines are appended, so the scroll position is preserved. A log
// that is already scrolled to the bottom keeps following the output (like
// tail -f); one the user has scrolled up in is left alone.
function logLineHtml(line) {
  const safe = escapeHtml(line);
  return /ERROR:|WARNING:|\bErr:/.test(line) ? `<span class="err">${safe}</span>` : safe;
}

function renderJobsInto(container, jobs) {
  const limit = parseInt(container.dataset.limit || "0", 10);
  const list = limit > 0 ? jobs.slice(0, limit) : jobs;

  if (!list.length) {
    if (!container.dataset.empty) {
      container.innerHTML = '<div class="empty">No jobs yet.</div>';
      container.dataset.empty = "1";
    }
    return;
  }
  if (container.dataset.empty) {
    container.innerHTML = "";
    delete container.dataset.empty;
  }

  const seen = new Set();

  list.forEach((j, position) => {
    seen.add(j.id);
    let node = container.querySelector(`.job[data-id="${j.id}"]`);

    if (!node) {
      node = document.createElement("div");
      node.className = "job";
      node.dataset.id = j.id;
      node.innerHTML = `
        <div class="job-head">
          <span class="job-title"></span>
          <span class="job-status"></span>
        </div>
        <pre class="log"></pre>`;
      const head = node.querySelector(".job-head");
      const logEl = node.querySelector(".log");
      head.addEventListener("click", () => {
        const nowOpen = logEl.classList.toggle("open");
        if (nowOpen) { openJobs.add(j.id); logEl.scrollTop = logEl.scrollHeight; }
        else openJobs.delete(j.id);
      });
      container.appendChild(node);
    }

    // Keep the newest-first order without touching nodes that are already right.
    const atPosition = container.children[position];
    if (atPosition !== node) container.insertBefore(node, atPosition || null);

    const titleEl = node.querySelector(".job-title");
    if (titleEl.textContent !== j.title) titleEl.textContent = j.title;

    const statusEl = node.querySelector(".job-status");
    if (statusEl.textContent !== j.status) {
      statusEl.textContent = j.status;
      statusEl.className = "job-status " + statusClass(j.status);
    }

    const logEl = node.querySelector(".log");
    logEl.classList.toggle("open", openJobs.has(j.id));

    const lines = j.log || [];
    const rendered = parseInt(logEl.dataset.lines || "0", 10);
    if (lines.length < rendered) {
      // Log replaced (should not normally happen): redraw from scratch.
      logEl.innerHTML = lines.map(logLineHtml).join("\n");
      logEl.dataset.lines = String(lines.length);
      logEl.scrollTop = logEl.scrollHeight;
    } else if (lines.length > rendered) {
      const wasAtBottom =
        logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 32;
      // Appending does not reset scrollTop, so the position survives.
      const addition = lines.slice(rendered).map(logLineHtml).join("\n");
      logEl.insertAdjacentHTML("beforeend", (rendered ? "\n" : "") + addition);
      logEl.dataset.lines = String(lines.length);
      if (wasAtBottom) logEl.scrollTop = logEl.scrollHeight;
    }
  });

  // Drop nodes for jobs that are no longer in the list.
  Array.from(container.querySelectorAll(".job")).forEach((node) => {
    if (!seen.has(node.dataset.id)) node.remove();
  });
}

function renderJobs(jobs) {
  $$(".jobs-container").forEach((c) => renderJobsInto(c, jobs));
  const active = jobs.filter((j) => j.status === "running" || j.status === "queued").length;
  setBadge("#badge-jobs", active);
}

function setBadge(sel, n) {
  const el = $(sel);
  if (!el) return;
  el.textContent = n;
  el.classList.toggle("zero", !n);
}

async function pollJobs(force = false) {
  try {
    const data = await api("/api/jobs");
    const jobsList = data.jobs || [];
    renderJobs(jobsList);
    const anyRunning = jobsList.some((j) => j.status === "running" || j.status === "queued");
    const anyBuildActive = jobsList.some(
      (j) => j.kind === "build" && (j.status === "running" || j.status === "queued"));
    if ((anyBuildActive || prevBuildActive) && $("#tab-tools").classList.contains("active")) {
      loadToolsTable();
    }
    prevBuildActive = anyBuildActive;
    clearTimeout(jobsTimer);
    jobsTimer = setTimeout(() => pollJobs(false), (anyRunning || force) ? 2000 : 6000);
  } catch (e) {
    clearTimeout(jobsTimer);
    jobsTimer = setTimeout(() => pollJobs(false), 6000);
  }
}

// --------------------------------------------------------------------------- //
// Tables
// --------------------------------------------------------------------------- //
async function loadToolsTable() {
  const root = $("#tools-table");
  try {
    const data = await api("/api/tools");
    const images = data.images || [];
    if (!images.length) { root.innerHTML = '<div class="empty">No tools yet.</div>'; return; }
    root.innerHTML = `
      <table><thead><tr>
        <th>Tool</th><th>Version</th><th>Image</th><th>Status</th>${IS_ADMIN ? "<th></th>" : ""}
      </tr></thead><tbody>
      ${images.map((im) => {
        const s = im.status || (im.built ? "built" : "not-built");
        const pillClass = s === "not-built" ? "unbuilt" : s;
        const pillLabel = { built: "built", building: "building", failed: "build failed", "not-built": "not built" }[s] || s;
        const btn = s === "building"
          ? `<button class="btn btn-sm" disabled>Building…</button>`
          : `<button class="btn btn-sm build-btn" data-tool="${escapeHtml(im.tool)}" data-version="${escapeHtml(im.version)}">${im.built ? "Rebuild" : "Build"}</button>`;
        return `<tr>
          <td class="mono">${escapeHtml(im.tool)}</td>
          <td class="mono">${escapeHtml(im.version)}</td>
          <td class="mono">${escapeHtml(im.image)}</td>
          <td><span class="pill ${pillClass}">${pillLabel}</span></td>
          ${IS_ADMIN ? `<td>${btn}</td>` : ""}
        </tr>`;
      }).join("")}
      </tbody></table>`;
    if (IS_ADMIN) {
      $$(".build-btn", root).forEach((b) =>
        b.addEventListener("click", () => buildImage(b.dataset.tool, b.dataset.version, b)));
    }
  } catch (e) {
    root.innerHTML = `<div class="empty">Could not load tools: ${escapeHtml(e.message)}</div>`;
  }
}

async function loadIndexesTable() {
  const root = $("#indexes-table");
  try {
    const data = await api("/api/indexes");
    const idx = data.indexes || [];
    if (!idx.length) { root.innerHTML = '<div class="empty">No indexes built yet.</div>'; return; }
    root.innerHTML = `
      <table><thead><tr>
        <th>Tool</th><th>Ver</th><th>Organism</th><th>Release</th><th>Assembly</th><th>Built</th>${IS_ADMIN ? "<th></th>" : ""}
      </tr></thead><tbody>
      ${idx.map((m) => `
        <tr>
          <td class="mono">${escapeHtml(m.tool)}</td>
          <td class="mono">${escapeHtml(m.tool_version)}</td>
          <td class="mono">${escapeHtml(m.species)}</td>
          <td class="mono">${escapeHtml(m.release)}</td>
          <td class="mono">${escapeHtml(m.assembly || "")}</td>
          <td class="mono">${escapeHtml((m.completed_at || "").replace("T", " ").replace("Z", ""))}</td>
          ${IS_ADMIN ? `<td><button class="btn btn-sm btn-danger rm-btn"
              data-tool="${escapeHtml(m.tool)}" data-version="${escapeHtml(m.tool_version)}"
              data-species="${escapeHtml(m.species)}" data-release="${escapeHtml(m.release)}">Remove</button></td>` : ""}
        </tr>`).join("")}
      </tbody></table>`;
    if (IS_ADMIN) $$(".rm-btn", root).forEach((b) => b.addEventListener("click", () => removeIndex(b)));
  } catch (e) {
    root.innerHTML = `<div class="empty">Could not load indexes: ${escapeHtml(e.message)}</div>`;
  }
}

async function loadRequests() {
  const root = $("#requests");
  try {
    const data = await api("/api/requests");
    const pending = data.pending || [];
    setBadge("#badge-requests", pending.length);
    if (!pending.length) { root.innerHTML = '<div class="empty">No pending requests.</div>'; return; }
    root.innerHTML = `
      <table><thead><tr>
        <th>Tool</th><th>Version</th><th>Notes</th><th>Requested</th>${IS_ADMIN ? "<th></th>" : ""}
      </tr></thead><tbody>
      ${pending.map((r) => `
        <tr>
          <td class="mono">${escapeHtml(r.tool)}</td>
          <td class="mono">${escapeHtml(r.version)}</td>
          <td>${escapeHtml(r.notes || "")}</td>
          <td class="mono">${escapeHtml((r.created_at || "").replace("T", " ").replace("Z", ""))}</td>
          ${IS_ADMIN ? `<td><button class="btn btn-sm btn-accent add-req-btn"
              data-id="${escapeHtml(r.id)}" data-tool="${escapeHtml(r.tool)}"
              data-version="${escapeHtml(r.version)}">Add</button></td>` : ""}
        </tr>`).join("")}
      </tbody></table>`;
    if (IS_ADMIN) {
      $$(".add-req-btn", root).forEach((b) => b.addEventListener("click", () => openAddFromRequest(b)));
    }
  } catch (e) {
    root.innerHTML = `<div class="empty">Could not load requests: ${escapeHtml(e.message)}</div>`;
  }
}

async function refreshCounts() {
  try {
    const data = await api("/api/requests");
    setBadge("#badge-requests", (data.pending || []).length);
  } catch (e) { /* ignore */ }
}

// --------------------------------------------------------------------------- //
// Actions
// --------------------------------------------------------------------------- //
async function buildImage(tool, version, btn) {
  btn.disabled = true;
  try {
    await api("/api/tools/build", { method: "POST", body: JSON.stringify({ tool, version }) });
    toast(`Build queued for ${tool} ${version}.`);
    setTimeout(loadToolsTable, 1200);
  } catch (e) { toast(e.message, true); btn.disabled = false; }
}

async function removeIndex(btn) {
  const { tool, version, species, release } = btn.dataset;
  if (!confirm(`Remove the ${tool} ${version} index for ${species} ${release}? This deletes the files.`)) return;
  btn.disabled = true;
  try {
    await api("/api/index/remove", {
      method: "POST", body: JSON.stringify({ tool, version, species, release }),
    });
    toast("Index removed.");
    loadIndexesTable();
  } catch (e) { toast(e.message, true); btn.disabled = false; }
}

// Requests -> Add tool tab, pre-filled
let PENDING_REQUEST_ID = null;

async function openAddFromRequest(btn) {
  PENDING_REQUEST_ID = btn.dataset.id;
  const tool = btn.dataset.tool;
  const version = btn.dataset.version;
  showTab("add");
  $("#add-tool").value = tool;
  $("#add-version").value = version;
  $("#add-command").value = "";
  $("#add-params").value = "";
  try {
    const d = await api(`/api/tools/template?tool=${encodeURIComponent(tool)}&version=${encodeURIComponent(version)}`);
    $("#add-dockerfile").value = d.dockerfile || "";
  } catch (e) { /* leave empty */ }
  toast(`Fulfilling request: ${tool} ${version}`);
}

function initAddTool() {
  if (!IS_ADMIN) return;
  $("#btn-template").addEventListener("click", async () => {
    const tool = $("#add-tool").value.trim();
    const version = $("#add-version").value.trim();
    try {
      const d = await api(`/api/tools/template?tool=${encodeURIComponent(tool)}&version=${encodeURIComponent(version)}`);
      $("#add-dockerfile").value = d.dockerfile || "";
    } catch (e) { toast(e.message, true); }
  });

  const add = async (build) => {
    const tool = $("#add-tool").value.trim();
    const version = $("#add-version").value.trim();
    const dockerfile = $("#add-dockerfile").value;
    const command = $("#add-command").value;
    const params = $("#add-params").value;
    if (!tool || !version) { toast("Enter a tool name and version.", true); return; }
    try {
      if (PENDING_REQUEST_ID) {
        await api("/api/requests/fulfil", {
          method: "POST",
          body: JSON.stringify({ id: PENDING_REQUEST_ID, dockerfile, command, params, build }),
        });
        PENDING_REQUEST_ID = null;
        toast(`Request fulfilled: ${tool} ${version}.`);
        refreshCounts();
      } else {
        await api("/api/tools/add", {
          method: "POST",
          body: JSON.stringify({ tool, version, dockerfile, command, params, build }),
        });
        toast(build ? `Added ${tool} ${version}, build queued.` : `Added ${tool} ${version}.`);
      }
      $("#add-tool").value = ""; $("#add-version").value = "";
      $("#add-dockerfile").value = ""; $("#add-command").value = ""; $("#add-params").value = "";
      loadTools();
      if (build) pollJobs(true);
    } catch (e) { toast(e.message, true); }
  };
  $("#btn-add").addEventListener("click", () => add(false));
  $("#btn-add-build").addEventListener("click", () => add(true));
}

function initRequest() {
  if (IS_ADMIN) return;
  $("#btn-request").addEventListener("click", async () => {
    const tool = $("#req-tool").value.trim();
    const version = $("#req-version").value.trim();
    const notes = $("#req-notes").value.trim();
    if (!tool || !version) { toast("Enter a tool name and version.", true); return; }
    try {
      await api("/api/tool-request", { method: "POST", body: JSON.stringify({ tool, version, notes }) });
      toast("Request sent.");
      $("#req-tool").value = ""; $("#req-version").value = ""; $("#req-notes").value = "";
      loadRequests();
    } catch (e) { toast(e.message, true); }
  });
}

// --------------------------------------------------------------------------- //
// System check (on demand). Also refreshes the daemon dot in the top bar.
// --------------------------------------------------------------------------- //
async function runDiagnostics() {
  const btn = $("#btn-diag");
  const note = $("#diag-note");
  const out = $("#diag-results");
  btn.disabled = true;
  note.textContent = "Running…";
  out.innerHTML = '<div class="empty">Checking daemon, container network, Ensembl and the data folder…</div>';
  try {
    const data = await api("/api/diagnostics");
    out.innerHTML = (data.checks || []).map((c) => `
      <div class="diag-row">
        <span class="diag-state diag-${escapeHtml(c.status)}">${escapeHtml(c.status)}</span>
        <span class="diag-label">${escapeHtml(c.label)}</span>
        <span class="diag-detail">${escapeHtml(c.detail || "")}</span>
      </div>`).join("");
    const summary = { ok: "Everything looks fine.",
                      warn: "Working, with warnings.",
                      fail: "Something is broken (see the failing rows)." }[data.summary]
                    || data.summary;
    note.textContent = summary;
    // keep the top bar dot honest
    const daemon = (data.checks || []).find((c) => c.id === "daemon");
    if (daemon) {
      const dot = $("#docker-dot");
      if (dot) {
        dot.className = "dot " + (daemon.status === "ok" ? "ok" : "off");
        const label = $("#docker-label");
        if (label) label.textContent = daemon.status === "ok" ? "docker ready" : "docker unreachable";
      }
    }
  } catch (e) {
    out.innerHTML = `<div class="empty">Could not run the check: ${escapeHtml(e.message)}</div>`;
    note.textContent = "";
  } finally {
    btn.disabled = false;
  }
}

// --------------------------------------------------------------------------- //
// Boot
// --------------------------------------------------------------------------- //
window.addEventListener("DOMContentLoaded", () => {
  initTheme();
  applyRoleVisibility();
  initTabs();
  initOrganismSearch();
  initAddTool();
  initRequest();

  $("#btn-check").addEventListener("click", checkSources);
  const diagBtn = $("#btn-diag");
  if (diagBtn) diagBtn.addEventListener("click", runDiagnostics);
  $("#btn-submit").addEventListener("click", submitIndex);

  loadTools().catch((e) => toast("Tools: " + e.message, true));
  resetReleases("Choose an organism first");
  updateSubmitState("Run Check sources first.");
  refreshCounts();
  pollJobs(false);
});
