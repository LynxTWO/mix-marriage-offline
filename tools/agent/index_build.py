"""Hot-path index artifact for the agent REPL harness.

Generates a fast-lookup index from a pre-built graph dict.  The index lets
agents jump directly to evidence (file + line) for canonical IDs, module
imports, and schema references — without grepping from scratch.

Default index location: ``.mmo_agent/agent_index.json`` under the repo root.

Index structure (version 1, all deterministic, no timestamps)
--------------------------------------------------------------
- ``version``           (int)  — Currently 1.
- ``repo_root``         (str)  — Absolute path to the repo root (consistent
  with the contract stamp).
- ``git_sha``           (str)  — HEAD SHA or ``"unknown"``.
- ``git_available``     (bool)
- ``graph_sha256``      (str)  — SHA-256 of the saved graph artifact; links
  this index to a specific graph build.
- ``module_to_file``    (dict) — Dotted module name → repo-relative file path.
  Only in-repo modules resolvable from ``py_import_file`` edges are included.
- ``id_to_occurrences`` (dict) — Canonical ID → sorted list of occurrences.
  Each occurrence: ``{path, line, col_start, evidence}``.
- ``schema_to_refs``    (dict) — Schema file path → sorted list of ``$ref``
  items.  Each item: ``{ref, evidence}``.
- ``file_summary``      (dict) — File path → ``{py_imports_count,
  id_refs_count, schema_refs_count}``.
- ``warnings``          (list) — Non-fatal issues encountered during build
  (e.g. budget exceeded for id_occurrences).

Performance notes
-----------------
Most index data (module_to_file, schema_to_refs, file_summary) is derived
directly from the graph edges — **no extra file reads**.  Only
``id_to_occurrences`` requires file reads to locate line numbers, because the
graph edges do not store per-line positions.  Those reads are budget-aware;
if the budget is exceeded, partial results are returned with a warning.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Optional

from .budgets import Budgets, BudgetExceededError
from .trace import Tracer


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum evidence snippet length (characters)
_EVIDENCE_CAP = 120

# Canonical MMO ID pattern (uppercase prefix + dotted-uppercase suffix).
# Matches IDs like ACTION.EQ.BELL_CUT, LAYOUT.2_0, ROLE.DRUMS.KICK, …
_CANONICAL_PREFIXES = (
    "ACTION", "ISSUE", "LAYOUT", "PARAM", "UNIT", "EVID",
    "FEATURE", "ROLE", "GATE", "SPK", "TRANS", "POLICY", "LOCK",
)
_ID_PATTERN = re.compile(
    r"\b(" + "|".join(_CANONICAL_PREFIXES) + r")\.[A-Z0-9][A-Z0-9_.]*"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _trim_evidence(text: str) -> str:
    """Strip trailing whitespace and cap to ``_EVIDENCE_CAP`` characters."""
    return text.rstrip()[:_EVIDENCE_CAP]


def _build_module_to_file(graph: dict) -> dict:
    """Extract ``dotted_module -> file_path`` from ``py_import_file`` edges.

    The ``evidence`` field of a ``py_import_file`` edge holds the original
    dotted module name; ``dst`` holds the resolved file path.  Only the first
    occurrence of each module name is kept (they are all identical by
    construction).

    Returns:
        Sorted dict (keys = dotted module names).
    """
    mapping: dict[str, str] = {}
    for edge in graph.get("edges", []):
        if edge.get("kind") == "py_import_file":
            module = edge.get("evidence", "")
            file_path = edge.get("dst", "")
            if module and file_path and module not in mapping:
                mapping[module] = file_path
    return dict(sorted(mapping.items()))


def _build_schema_to_refs(graph: dict) -> dict:
    """Extract ``schema_file -> [{ref, evidence}]`` from ``schema_ref`` edges.

    Returns:
        Dict keyed by schema file path (sorted); values are ref lists sorted
        by ``(ref, evidence)``.
    """
    raw: dict[str, list[dict]] = {}
    for edge in graph.get("edges", []):
        if edge.get("kind") == "schema_ref":
            src = edge.get("src", "")
            ref = edge.get("dst", "")
            evidence = _trim_evidence(edge.get("evidence", ""))
            if src and ref:
                raw.setdefault(src, []).append(
                    {"evidence": evidence, "ref": ref}
                )
    return {
        k: sorted(v, key=lambda x: (x["ref"], x["evidence"]))
        for k, v in sorted(raw.items())
    }


def _build_file_summary(graph: dict) -> dict:
    """Count edge types per source file.

    Returns:
        Dict keyed by file path (sorted); values are
        ``{py_imports_count, id_refs_count, schema_refs_count}`` dicts.
    """
    summary: dict[str, dict] = {}

    def _rec(path: str) -> dict:
        return summary.setdefault(
            path,
            {"id_refs_count": 0, "py_imports_count": 0, "schema_refs_count": 0},
        )

    for edge in graph.get("edges", []):
        kind = edge.get("kind", "")
        src = edge.get("src", "")
        if not src:
            continue
        rec = _rec(src)
        if kind == "py_import":
            rec["py_imports_count"] += 1
        elif kind == "id_ref":
            rec["id_refs_count"] += 1
        elif kind == "schema_ref":
            rec["schema_refs_count"] += 1

    return dict(sorted(summary.items()))


def _is_path_skipped(rel_path: str, skip_paths: frozenset) -> bool:
    """Return True if *rel_path* is under any of the *skip_paths* prefixes.

    Matching is by path-prefix: ``"docs"`` matches ``"docs/foo.md"`` and the
    exact path ``"docs"`` itself.  Partial-directory matches are excluded —
    ``"doc"`` does NOT match ``"docs/foo.md"``.
    """
    for sp in skip_paths:
        if rel_path == sp or rel_path.startswith(sp + "/"):
            return True
    return False


def _build_id_occurrences(
    graph: dict,
    root: pathlib.Path,
    budgets: Budgets,
    tracer: Tracer,
    skip_paths: frozenset = frozenset(),
) -> tuple[dict, list[str]]:
    """Build ``id -> [{path, line, col_start, evidence}]`` by reading source files.

    Uses only the files already identified by the graph's ``id_ref`` edges —
    no additional greps.  One file read per unique source file.

    Args:
        graph: The pre-built graph dict.
        root: Root used for resolving the POSIX-relative paths in graph edges.
            Typically the same as the repo root.
        budgets: Budget enforcer (charges file reads for each source file).
        tracer: Trace sink.
        skip_paths: Frozenset of POSIX path prefixes to skip.  Files whose
            relative path starts with any prefix are excluded from occurrence
            scanning (graph edges are unaffected).  Useful for skipping
            ``docs/`` which is expensive and rarely needed for code navigation.

    Returns:
        Tuple of ``(occurrences_dict, warnings)``.  If the budget is exceeded
        mid-scan, partial results are returned along with a warning string.
    """
    # Collect file -> {set of canonical IDs} from id_ref edges
    file_to_ids: dict[str, set] = {}
    for edge in graph.get("edges", []):
        if edge.get("kind") == "id_ref":
            src = edge.get("src", "")
            dst = edge.get("dst", "")
            if src and dst:
                file_to_ids.setdefault(src, set()).add(dst)

    result: dict[str, list[dict]] = {}
    warnings: list[str] = []

    for rel_path in sorted(file_to_ids.keys()):
        if skip_paths and _is_path_skipped(rel_path, skip_paths):
            tracer.emit("index_id_occ_skipped", path=rel_path, reason="skip_path")
            continue
        if budgets.is_exceeded:
            warnings.append(
                f"id_to_occurrences scan stopped early (budgets exceeded) "
                f"at {rel_path!r}; results are partial."
            )
            break

        ids_wanted = file_to_ids[rel_path]
        abs_path = root / rel_path

        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            tracer.emit("index_file_read_error", path=rel_path)
            continue

        lines = text.splitlines()

        try:
            budgets.charge_file_read(len(lines))
        except BudgetExceededError as exc:
            tracer.emit("index_budget_exceeded", path=rel_path, reason=str(exc))
            warnings.append(
                f"id_to_occurrences scan stopped (budget exceeded) "
                f"after reading {rel_path!r}: {exc}"
            )
            break

        tracer.emit("index_file_read", ids=len(ids_wanted), path=rel_path)

        for lineno, line in enumerate(lines, start=1):
            for match in _ID_PATTERN.finditer(line):
                found_id = match.group(0)
                if found_id not in ids_wanted:
                    continue
                occurrence = {
                    "col_start": match.start() + 1,  # 1-based
                    "evidence": _trim_evidence(line),
                    "line": lineno,
                    "path": rel_path,
                }
                result.setdefault(found_id, []).append(occurrence)

    # Deterministic sort: IDs alphabetical, occurrences by (path, line, col_start, evidence)
    sorted_result: dict[str, list[dict]] = {}
    for id_key in sorted(result.keys()):
        sorted_result[id_key] = sorted(
            result[id_key],
            key=lambda x: (x["path"], x["line"], x.get("col_start", 0), x["evidence"]),
        )

    return sorted_result, warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_index(
    graph: dict,
    repo_root: pathlib.Path,
    budgets: Budgets,
    tracer: Tracer,
    git_sha: str,
    git_available: bool,
    graph_sha256: str,
    skip_paths: frozenset = frozenset(),
) -> dict:
    """Build the hot-path index from a pre-built graph.

    Most index sections (module_to_file, schema_to_refs, file_summary) are
    derived directly from graph edges with no additional file reads.  Only
    ``id_to_occurrences`` requires reading files to locate per-line positions;
    those reads are budget-charged.

    If the budget is exceeded during the ``id_to_occurrences`` scan, a partial
    (or empty) result is returned and a warning is recorded in the
    ``"warnings"`` key of the returned dict.

    Args:
        graph: The graph dict returned by
            :func:`~tools.agent.graph_build.build_graph`.
        repo_root: Absolute path to the repo root.  Used to resolve relative
            file paths from graph edges when reading for line-number data.
            In the standard workflow this equals the scan root (``args.root``).
        budgets: Budget enforcer.
        tracer: Trace sink.
        git_sha: HEAD SHA (from :func:`~tools.agent.contract_stamp.get_git_head_sha`).
        git_available: Whether git was reachable.
        graph_sha256: SHA-256 of the saved graph artifact file; links the index
            to its source graph.
        skip_paths: Frozenset of POSIX path prefixes to exclude from
            ``id_to_occurrences`` scanning.  Graph edges are unaffected.
            Passed through to :func:`_build_id_occurrences`.

    Returns:
        Index dict ready to serialise with :func:`save_index`.
    """
    tracer.emit("index_build_start", repo_root=str(repo_root))

    module_to_file = _build_module_to_file(graph)
    schema_to_refs = _build_schema_to_refs(graph)
    file_summary = _build_file_summary(graph)

    # id_to_occurrences requires file reads — budget aware
    try:
        id_to_occurrences, occ_warnings = _build_id_occurrences(
            graph, repo_root, budgets, tracer, skip_paths=skip_paths
        )
    except BudgetExceededError as exc:
        # Unexpected hard stop (shouldn't normally reach here because
        # _build_id_occurrences handles it internally, but guard anyway)
        id_to_occurrences = {}
        occ_warnings = [f"id_to_occurrences aborted by unexpected budget error: {exc}"]
        tracer.emit("index_budget_exceeded_fatal", reason=str(exc))

    index = {
        "file_summary": file_summary,
        "git_available": git_available,
        "git_sha": git_sha,
        "graph_sha256": graph_sha256,
        "id_to_occurrences": id_to_occurrences,
        "module_to_file": module_to_file,
        "repo_root": str(repo_root.resolve()),
        "schema_to_refs": schema_to_refs,
        "version": 1,
        "warnings": occ_warnings,
    }

    tracer.emit(
        "index_build_done",
        id_count=len(id_to_occurrences),
        module_count=len(module_to_file),
        schema_count=len(schema_to_refs),
    )
    return index


def save_index(path: pathlib.Path, index: dict) -> None:
    """Write *index* to *path* as deterministic JSON (sorted keys, 2-space indent).

    Creates parent directories as needed.

    Args:
        path: Destination ``.json`` file path.
        index: The dict returned by :func:`build_index`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
