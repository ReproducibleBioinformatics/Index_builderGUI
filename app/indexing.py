"""Index command construction.

Every tool is self-describing: an image (Dockerfile), an index command template,
and a set of parameters. The command template uses placeholders that are filled
in at run time:

  System placeholders (always available):
    {fasta}            decompressed genome FASTA
    {gtf}              decompressed annotation GTF
    {index_dir}        output directory (created for you)
    {genome_length}    total genome length
    {sa_index_nbases}  min(14, floor(log2(genome_length)/2 - 1)), for STAR
    {threads}          CPU threads (default from config; overridable)
    {sjdb_overhang}    STAR sjdbOverhang (default from config; overridable)

  Tool parameters:
    Anything else a tool declares (name + default). These show up as editable
    fields in the index form and override the defaults above when named the same.
"""

import math
import re

# Placeholders the system always provides, so a command may use them without
# declaring a parameter. {threads} and {sjdb_overhang} carry config defaults and
# can also be exposed as editable parameters.
SYSTEM_PLACEHOLDERS = frozenset({
    "fasta", "gtf", "index_dir", "genome_length", "sa_index_nbases",
    "threads", "sjdb_overhang",
})

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# Allowed characters in a parameter VALUE, to keep values a single safe shell
# word (no metacharacters, no spaces): prevents command injection.
_VALUE_RE = re.compile(r"^[A-Za-z0-9._,:+-]*$")

# The core placeholders shown in hints and error messages.
COMMAND_PLACEHOLDERS = ("{fasta}", "{gtf}", "{index_dir}", "{threads}")


def star_sa_index_nbases(genome_length):
    """STAR requires genomeSAindexNbases reduced for small genomes:
    min(14, floor(log2(L)/2 - 1))."""
    if genome_length <= 0:
        return 14
    value = int(math.log2(genome_length) / 2 - 1)
    return max(4, min(14, value))


def placeholders_in(template):
    """The set of {name} placeholders used in a template."""
    return set(_PLACEHOLDER_RE.findall(template or ""))


def valid_param_value(value):
    return bool(_VALUE_RE.match(value or ""))


def build_command(tool, fasta, gtf, index_dir, genome_length, command_template,
                  params, default_threads, default_sjdb_overhang):
    """Return ["bash", "-c", script] for the tool's command template with all
    placeholders filled in. `params` (name -> value) override the defaults."""
    if not (command_template and command_template.strip()):
        raise ValueError(
            f"Tool '{tool}' has no index command. Add one first."
        )

    # A tool that consumes the annotation cannot run without it. Ensembl has no
    # GTF for some species/release combinations, so say so plainly rather than
    # letting the aligner fail on an empty path.
    if "{gtf}" in command_template and not gtf:
        raise ValueError(
            f"'{tool}' needs an annotation GTF, but Ensembl has none for this "
            f"organism and release. Use a tool that indexes DNA only (BWA, "
            f"Bowtie2, minimap2), or pick a release that has annotation."
        )
    subs = {
        "fasta": fasta,
        "gtf": gtf,
        "index_dir": index_dir,
        "genome_length": str(genome_length),
        "sa_index_nbases": str(star_sa_index_nbases(genome_length)),
        "threads": str(default_threads),
        "sjdb_overhang": str(default_sjdb_overhang),
    }
    for name, value in (params or {}).items():
        subs[name] = str(value)

    out = command_template.strip()
    for name, value in subs.items():
        out = out.replace("{" + name + "}", value)

    script = f"set -euo pipefail\nmkdir -p '{index_dir}'\n{out}\n"
    return ["bash", "-lc", script]
