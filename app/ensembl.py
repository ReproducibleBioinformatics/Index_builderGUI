"""Ensembl access layer.

Responsibilities:
  * fuzzy (non exact match) species search. The organism list comes from the
    Ensembl FTP directory listing (the authoritative set of species that have
    downloadable data, including model organisms like drosophila that the REST
    species feed can omit); pretty names are enriched from REST, best-effort
  * list available Ensembl releases, and which releases a given species has
  * resolve the real FASTA (DNA) and GTF download URLs for a species + release
    by reading the actual FTP directory listing, so we never hard code an
    assembly name
  * stream those files to disk and decompress them

Everything here degrades gracefully when the network is unavailable: searches
return an empty list and release listing falls back to a static recent range,
so the web app never crashes offline.

Scope note: this targets Ensembl main (vertebrates) via rest.ensembl.org and
ftp.ensembl.org, which covers the common cases (human, mouse, and the other
vertebrate model organisms). Plants and fungi live under Ensembl Genomes on a
different host and are intentionally out of scope; the resolver would just need
a different base URL to support them.
"""

import gzip
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

import requests

from config import ENSEMBL_REST, ENSEMBL_FTP, DNA_PREFERENCE

_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']')
_TIMEOUT = 30


# --------------------------------------------------------------------------- #
# Tiny time based cache so we do not hammer Ensembl on every keystroke.
# --------------------------------------------------------------------------- #
class _TTLCache:
    def __init__(self, ttl_seconds):
        self.ttl = ttl_seconds
        self._value = None
        self._stamp = 0.0
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            if self._value is not None and (time.time() - self._stamp) < self.ttl:
                return self._value
            return None

    def set(self, value):
        with self._lock:
            self._value = value
            self._stamp = time.time()


class _KeyedTTLCache:
    """Per-key TTL cache (used to remember which releases a species has)."""

    def __init__(self, ttl_seconds):
        self.ttl = ttl_seconds
        self._d = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            entry = self._d.get(key)
            if entry and (time.time() - entry[1]) < self.ttl:
                return entry[0]
            return None

    def set(self, key, value):
        with self._lock:
            self._d[key] = (value, time.time())


_species_cache = _TTLCache(ttl_seconds=6 * 3600)
_release_cache = _TTLCache(ttl_seconds=6 * 3600)
_species_release_cache = _KeyedTTLCache(ttl_seconds=6 * 3600)


def _rest_json(path, attempts=3):
    """GET a REST endpoint as JSON, robustly.

    Ensembl negotiates the response format from the Accept header (and the
    content-type query parameter), not from Content-Type. Sending the wrong
    header can yield a non-JSON body or a partial response, which is a likely
    cause of an incomplete species list. We ask for JSON explicitly and retry a
    couple of times on transient failures.
    """
    url = f"{ENSEMBL_REST}{path}"
    last = None
    for i in range(attempts):
        try:
            resp = requests.get(
                url,
                headers={"Accept": "application/json"},
                params={"content-type": "application/json"},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1 + i)
    raise last


# --------------------------------------------------------------------------- #
# Species
# --------------------------------------------------------------------------- #
_SPECIES_DIR_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)+$")

# Directories under pub/current_fasta/ that look like a species name but are not.
_NON_SPECIES = {"ancestral_alleles"}


def _prettify(name):
    # drosophila_melanogaster -> Drosophila melanogaster (binomial style)
    return name.replace("_", " ").capitalize()


def _species_names_from_ftp():
    """The authoritative list of organisms: every directory under the current
    FASTA release on the FTP. This is what actually has downloadable DNA, and it
    includes the non-vertebrate model organisms (drosophila, c. elegans, yeast)
    that the REST species list can omit.
    """
    entries = _http_listing(f"{ENSEMBL_FTP}/pub/current_fasta/")
    names = []
    for entry in entries:
        leaf = entry.strip("/").split("/")[-1]
        if _SPECIES_DIR_RE.match(leaf) and leaf not in _NON_SPECIES:
            names.append(leaf)
    return sorted(set(names))


def _species_labels_from_rest():
    """Best-effort pretty names (display and common) keyed by systematic name.
    Never fatal: returns {} if the REST feed is unavailable."""
    try:
        raw = _rest_json("/info/species").get("species", [])
    except Exception:
        return {}
    labels = {}
    for item in raw:
        name = item.get("name")
        if name:
            labels[name] = {
                "display_name": item.get("display_name") or "",
                "common_name": item.get("common_name") or "",
                "assembly": item.get("assembly") or "",
            }
    return labels


def _fetch_species():
    labels = _species_labels_from_rest()  # best-effort, {} on failure
    try:
        names = _species_names_from_ftp()
    except Exception:
        names = []
    if not names:
        # FTP unreachable: fall back to whatever the REST feed listed.
        names = sorted(labels.keys())
    species = []
    for name in names:
        meta = labels.get(name, {})
        species.append(
            {
                "name": name,  # e.g. drosophila_melanogaster, used to build URLs
                "display_name": meta.get("display_name") or _prettify(name),
                "common_name": meta.get("common_name") or "",
                "assembly": meta.get("assembly") or "",
            }
        )
    species.sort(key=lambda s: s["name"])
    return species


def all_species():
    cached = _species_cache.get()
    if cached is not None:
        return cached
    try:
        species = _fetch_species()
    except Exception:
        # Offline or Ensembl down: return nothing rather than raising.
        return []
    _species_cache.set(species)
    return species


def search_species(query, limit=25):
    """Substring, case insensitive match across name / display / common name.

    Typing 'mus' returns every match (mus_musculus, mus_spretus, ...) rather
    than requiring an exact identifier.
    """
    query = (query or "").strip().lower().replace(" ", "_")
    species = all_species()
    if not query:
        return species[:limit]
    scored = []
    for sp in species:
        haystack = (
            f"{sp['name']} {sp['display_name']} {sp['common_name']}".lower()
        )
        if query in haystack:
            # Prefer matches at the start of the systematic name.
            rank = 0 if sp["name"].startswith(query) else 1
            scored.append((rank, sp["name"], sp))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [sp for _, _, sp in scored[:limit]]


# --------------------------------------------------------------------------- #
# Releases
# --------------------------------------------------------------------------- #
def _current_release():
    releases = _rest_json("/info/data").get("releases", [])
    return max(releases) if releases else None


def _fetch_releases():
    # Primary source: parse the /pub/ listing for release-NNN directories.
    listing = _http_listing(f"{ENSEMBL_FTP}/pub/")
    releases = sorted(
        {
            int(m.group(1))
            for entry in listing
            for m in [re.search(r"release-(\d+)", entry)]
            if m
        },
        reverse=True,
    )
    if releases:
        return releases
    # Fallback: current release from REST, expanded into a descending range.
    current = _current_release()
    if current:
        return list(range(current, max(current - 20, 40), -1))
    return []


def list_releases():
    cached = _release_cache.get()
    if cached is not None:
        return cached
    try:
        releases = _fetch_releases()
    except Exception:
        releases = []
    if not releases:
        # Static, clearly recent fallback so the dropdown is never empty.
        releases = [114, 113, 112, 111, 110]
    _release_cache.set(releases)
    return releases


# --------------------------------------------------------------------------- #
# Which releases actually contain a given species
# --------------------------------------------------------------------------- #
def _dir_exists(url):
    """True if an FTP directory exists (HTTP 200), fetching only headers."""
    try:
        resp = requests.get(url, stream=True, timeout=_TIMEOUT)
        ok = resp.status_code == 200
        resp.close()
        return ok
    except Exception:
        return False


def releases_for_species(species, max_check=15):
    """Return the recent Ensembl releases that actually have DNA data for this
    species, newest first.

    Not every organism exists in every release (a species added recently has no
    old releases), so we probe the FTP for the most recent releases and keep the
    ones where .../fasta/<species>/dna/ exists. Probes run concurrently and the
    result is cached per species.
    """
    species = (species or "").strip().lower()
    if not species:
        return []
    cached = _species_release_cache.get(species)
    if cached is not None:
        return cached

    candidates = list_releases()[:max_check]

    def check(rel):
        url = f"{ENSEMBL_FTP}/pub/release-{rel}/fasta/{species}/dna/"
        return rel, _dir_exists(url)

    found = []
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for rel, ok in pool.map(check, candidates):
                if ok:
                    found.append(rel)
    except Exception:
        found = []
    found.sort(reverse=True)
    if found:
        _species_release_cache.set(species, found)
    return found


# --------------------------------------------------------------------------- #
# Directory listing helper
# --------------------------------------------------------------------------- #
def _http_listing(url):
    """Return the href entries of an Ensembl FTP-over-HTTPS directory page."""
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    return _HREF_RE.findall(resp.text)


# --------------------------------------------------------------------------- #
# FASTA / GTF URL resolution
# --------------------------------------------------------------------------- #
def resolve_fasta(species, release):
    """Return metadata for the DNA FASTA of species at release.

    Reads the real listing of .../fasta/<species>/dna/ and picks the preferred
    unmasked flavour (primary_assembly, else toplevel). The assembly name is
    parsed from the chosen filename, never guessed.
    """
    base = f"{ENSEMBL_FTP}/pub/release-{release}/fasta/{species}/dna/"
    entries = _http_listing(base)
    files = [e for e in entries if e.endswith(".fa.gz")]

    def pick(flavour):
        pattern = re.compile(
            rf"^[A-Z][a-z_]+\.(.+)\.dna\.{re.escape(flavour)}\.fa\.gz$"
        )
        for f in files:
            name = f.split("/")[-1]
            m = pattern.match(name)
            if m:
                return name, m.group(1)  # (filename, assembly)
        return None

    for flavour in DNA_PREFERENCE:
        hit = pick(flavour)
        if hit:
            filename, assembly = hit
            return {
                "url": urljoin(base, filename),
                "filename": filename,
                "assembly": assembly,
                "dna_type": flavour,
            }
    raise FileNotFoundError(
        f"No DNA FASTA ({' / '.join(DNA_PREFERENCE)}) found for "
        f"{species} at release {release}."
    )


def resolve_gtf(species, release):
    """Return metadata for the main annotation GTF of species at release.

    Picks <Species>.<assembly>.<release>.gtf.gz, skipping the abinitio and
    chromosome-only variants. This GTF carries gene symbols (gene_name) as
    Ensembl ships them.
    """
    base = f"{ENSEMBL_FTP}/pub/release-{release}/gtf/{species}/"
    entries = _http_listing(base)
    candidates = [
        e.split("/")[-1]
        for e in entries
        if e.endswith(f".{release}.gtf.gz")
        and ".abinitio." not in e
        and ".chr." not in e
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No annotation GTF found for {species} at release {release}."
        )
    filename = sorted(candidates, key=len)[0]
    return {"url": urljoin(base, filename), "filename": filename}


def resolve(species, release):
    """Resolve the sources for a species + release.

    The FASTA is required: without it there is nothing to index, so a failure
    here propagates. The GTF is optional, because some assemblies on Ensembl
    have no annotation for a given release; in that case `gtf` is None and a
    warning is reported, and only tools whose command actually references the
    GTF are affected.
    """
    fasta = resolve_fasta(species, release)
    warnings = []
    try:
        gtf = resolve_gtf(species, release)
    except Exception as exc:  # noqa: BLE001
        gtf = None
        warnings.append(
            f"No annotation GTF found for {species} release {release} "
            f"({exc}). Tools that need a GTF (STAR, HISAT2) cannot build an "
            f"annotation-aware index for this combination."
        )
    return {
        "species": species,
        "release": release,
        "assembly": fasta["assembly"],
        "dna_type": fasta["dna_type"],
        "fasta": fasta,
        "gtf": gtf,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Download + decompress
# --------------------------------------------------------------------------- #
def download(url, dest: Path, log=print):
    """Stream a URL to dest (shows periodic progress through the log callback)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log(f"Downloading {url}")
    with requests.get(url, stream=True, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        next_mark = 0
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                fh.write(chunk)
                done += len(chunk)
                if total and done >= next_mark:
                    pct = done * 100 // total
                    log(f"  {pct}% ({done // (1024 * 1024)} MB / "
                        f"{total // (1024 * 1024)} MB)")
                    next_mark = done + max(total // 20, 1)
    tmp.replace(dest)
    log(f"Saved {dest.name}")


def gunzip_measure(src_gz: Path, dest: Path, measure=False, log=print):
    """Decompress src_gz into dest. When measure is True, also return the total
    length of the sequence (used to size STAR's genomeSAindexNbases)."""
    log(f"Decompressing {src_gz.name}")
    seq_len = 0
    with gzip.open(src_gz, "rb") as fin, open(dest, "wb") as fout:
        if not measure:
            shutil.copyfileobj(fin, fout)
        else:
            for line in fin:
                fout.write(line)
                if not line.startswith(b">"):
                    seq_len += len(line.rstrip(b"\r\n"))
    return seq_len
