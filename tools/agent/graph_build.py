"""Dependency graph builder for the agent REPL harness.

Builds a file-level dependency graph across a repository by extracting four
edge kinds:

* ``py_import``      — Python AST import edges (dotted module name as dst).
* ``py_import_file`` — Resolved file-path variant of ``py_import`` edges.
* ``schema_ref``     — JSON schema ``$ref`` edges.
* ``id_ref``         — MMO canonical ID references in any text file.

All output is deterministically ordered (nodes by ``(kind, id)``, edges by
``(kind, src, dst, evidence)``).  No timestamps are included in the artifact.

Scoping
-------
The *scope_paths* parameter (list of absolute paths) restricts which files are
processed.  Only files that are descendants of at least one scope path are
scanned.  If *scope_paths* is empty the entire *root* tree is scanned.

Typical usage::

    from tools.agent.graph_build import build_graph, save_graph
    from tools.agent.budgets import Budgets, BudgetConfig

    budgets = Budgets(BudgetConfig(max_file_reads=200))
    graph = build_graph(root=pathlib.Path("."), budgets=budgets)
    save_graph(graph, pathlib.Path("sandbox_tmp/agent_graph.json"))
"""

from __future__ import annotations

import json
import pathlib
from typing import Optional

from .budgets import Budgets, BudgetConfig, BudgetExceededError
from .repo_ops import (
    build_id_allowlist,
    list_files,
    parse_py_imports,
    resolve_module_to_path,
    scan_id_refs,
    scan_schema_refs,
)
from .trace import Tracer


# ---------------------------------------------------------------------------
# Directories to skip when walking the repo
# ---------------------------------------------------------------------------
_SKIP_DIRS: frozenset[str] = frozenset({
    ".git",
    "__pycache__",
    ".tmp_pytest",
    ".tmp_claude",
    ".tmp_codex",
    "sandbox_tmp",
    ".pytest_cache",
    "node_modules",
    ".venv",
    "venv",
    "corpus",
    "private",
    ".mmo_agent",
    ".mmo_cache",
    ".mmo_tmp",
})

# File-type globs to scan for id_refs
_ID_REF_GLOBS = ("*.py", "*.yaml", "*.yml", "*.json", "*.md")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _node(node_id: str, kind: str = "file") -> dict:
    return {"id": node_id, "kind": kind}


def _edge(
    kind: str,
    src: str,
    dst: str,
    evidence: str,
    source_file: str,
) -> dict:
    return {
        "dst": dst,
        "evidence": evidence,
        "kind": kind,
        "source_file": source_file,
        "src": src,
    }


def _should_skip(path: pathlib.Path, root: pathlib.Path) -> bool:
    """Return True if *path* is inside a directory that should be skipped."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return bool(frozenset(parts) & _SKIP_DIRS)


def _in_scope(path: pathlib.Path, scope_paths: list[pathlib.Path]) -> bool:
    """Return True if *path* is under any of *scope_paths*, or if scope is empty.

    Supports both directory-prefix matching (path is a descendant of a scope dir)
    and exact file matching (path equals a scope path directly).
    """
    if not scope_paths:
        return True
    for sp in scope_paths:
        try:
            path.relative_to(sp)
            return True
        except ValueError:
            pass
        if path == sp:
            return True
    return False


def _find_repo_root(start: pathlib.Path) -> pathlib.Path:
    """Walk up from *start* to find the git repo root (directory containing ``.git``).

    Returns *start* itself if no git root is found (graceful fallback).
    """
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return start  # filesystem root reached
        current = parent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_graph(
    root: pathlib.Path,
    budgets: Optional[Budgets] = None,
    tracer: Optional[Tracer] = None,
    repo_root: Optional[pathlib.Path] = None,
    use_id_allowlist: bool = True,
    scope_paths: Optional[list[pathlib.Path]] = None,
) -> dict:
    """Build a file-level dependency graph for the repository at *root*.

    The function walks *root* recursively, skipping directories in
    ``_SKIP_DIRS``, and extracts four edge kinds for each file.  Budget caps
    are enforced throughout; on first violation the current phase is aborted
    gracefully, a warning is recorded, and the function proceeds to the next
    phase (or returns early if the budget is already exceeded).

    Args:
        root: Repository root to scan.  Does not need to be the repo root —
              passing a subdirectory scopes the graph to that subtree.
        budgets: Budget enforcer.  A fresh default :class:`Budgets` is created
                 if not provided.
        tracer: Trace sink.  A no-op :class:`Tracer` is used if not provided.
        repo_root: Root used for ``py_import_file`` resolution and ontology
                   discovery.  Auto-detected via ``.git`` walk if not provided.
        use_id_allowlist: When ``True`` (default), build an ontology allowlist
                          and restrict ``id_ref`` edges to known canonical IDs.
                          Falls back to full regex mode if the allowlist is empty
                          (e.g. ontology dir not found).
        scope_paths: Optional list of **absolute** paths.  When non-empty, only
                     files under these paths are scanned (used by ``--scope``
                     and ``--preset`` CLI flags).

    Returns:
        A dict with three stable keys:

        * ``"nodes"``    — list of ``{"id": str, "kind": str}`` dicts, sorted
          by ``(kind, id)``.
        * ``"edges"``    — list of edge dicts, sorted by
          ``(kind, src, dst, evidence)``.  Each edge has keys: ``kind``,
          ``src``, ``dst``, ``evidence``, ``source_file``.
        * ``"warnings"`` — list of human-readable warning strings (budget hits,
          parse errors, etc.).

        The artifact contains **no timestamps** and is fully deterministic for
        identical repository state.
    """
    if budgets is None:
        budgets = Budgets()
    if tracer is None:
        tracer = Tracer()  # no-op (path=None)
    if scope_paths is None:
        scope_paths = []

    # Auto-detect repo root for import resolution and ontology discovery
    effective_repo_root = repo_root if repo_root is not None else _find_repo_root(root)

    nodes: dict[str, dict] = {}      # id -> node dict
    edge_list: list[dict] = []
    seen_edges: set[tuple[str, str, str, str]] = set()
    warnings: list[str] = []

    def add_node(node_id: str, kind: str = "file") -> None:
        if node_id not in nodes:
            nodes[node_id] = _node(node_id, kind)

    def add_edge(
        kind: str, src: str, dst: str, evidence: str, source_file: str
    ) -> None:
        key = (kind, src, dst, evidence)
        if key not in seen_edges:
            seen_edges.add(key)
            edge_list.append(_edge(kind, src, dst, evidence, source_file))
            add_node(src)
            add_node(dst)

    tracer.emit("graph_build_start", repo_root=str(effective_repo_root), root=str(root))

    # -----------------------------------------------------------------------
    # Phase 1: Python import edges + py_import_file resolved edges
    # -----------------------------------------------------------------------
    if not budgets.is_exceeded:
        try:
            py_files = list_files(root, "*.py", budgets, tracer)
        except BudgetExceededError as exc:
            warnings.append(f"Budget exceeded listing .py files: {exc}")
            py_files = []

        for py_path in py_files:
            if _should_skip(py_path, root):
                continue
            if not _in_scope(py_path, scope_paths):
                continue
            try:
                rel = py_path.relative_to(root).as_posix()
            except ValueError:
                continue
            add_node(rel)
            try:
                import_edges = parse_py_imports(py_path, root, budgets, tracer)
            except BudgetExceededError as exc:
                warnings.append(f"Budget exceeded parsing imports in {rel}: {exc}")
                break
            for ie in import_edges:
                add_edge("py_import", ie.src, ie.dst, ie.evidence, rel)

                # Upgrade 1: also emit a py_import_file edge when we can
                # resolve the dotted module to an actual file in the repo.
                resolved = resolve_module_to_path(ie.dst, effective_repo_root)
                if resolved is not None:
                    # Express the resolved path relative to the scan root
                    try:
                        resolved_rel = (
                            (effective_repo_root / resolved)
                            .relative_to(root)
                            .as_posix()
                        )
                    except ValueError:
                        # Resolved file exists but lies outside scan root;
                        # use the repo-root-relative path instead so the node
                        # is still useful.
                        resolved_rel = resolved
                    add_edge(
                        "py_import_file",
                        ie.src,
                        resolved_rel,
                        ie.dst,   # evidence = original dotted module name
                        rel,
                    )

    # -----------------------------------------------------------------------
    # Phase 2: JSON schema $ref edges
    # -----------------------------------------------------------------------
    if not budgets.is_exceeded:
        try:
            json_files = list_files(root, "*.json", budgets, tracer)
        except BudgetExceededError as exc:
            warnings.append(f"Budget exceeded listing .json files: {exc}")
            json_files = []

        for schema_path in json_files:
            if _should_skip(schema_path, root):
                continue
            if not _in_scope(schema_path, scope_paths):
                continue
            try:
                rel = schema_path.relative_to(root).as_posix()
            except ValueError:
                continue
            add_node(rel)
            # Only scan files that look like JSON schemas
            is_schema = (
                "schemas" in schema_path.parts
                or schema_path.name.endswith(".schema.json")
            )
            if not is_schema:
                continue
            try:
                ref_edges = scan_schema_refs(schema_path, root, budgets, tracer)
            except BudgetExceededError as exc:
                warnings.append(f"Budget exceeded scanning schema refs in {rel}: {exc}")
                break
            for re_ in ref_edges:
                add_edge("schema_ref", re_.src, re_.dst, re_.evidence, rel)

    # -----------------------------------------------------------------------
    # Phase 3: MMO canonical ID references
    # -----------------------------------------------------------------------
    if not budgets.is_exceeded:
        # Upgrade 2: build ontology allowlist for id_ref filtering
        id_allowlist: Optional[frozenset[str]] = None
        if use_id_allowlist:
            ont_root = effective_repo_root / "ontology"
            raw_allowlist = build_id_allowlist(ont_root, budgets, tracer)
            if raw_allowlist:
                id_allowlist = raw_allowlist
                tracer.emit(
                    "id_allowlist_active",
                    count=len(id_allowlist),
                )
            else:
                # Empty allowlist = ontology not found or empty; fall back to regex
                warnings.append(
                    "id_ref allowlist is empty — falling back to full regex mode"
                )
                tracer.emit("id_allowlist_fallback", reason="empty_allowlist")

        # Collect candidate files from all relevant globs, deduplicated.
        seen_paths: set[str] = set()
        id_files: list[pathlib.Path] = []

        for glob_pat in _ID_REF_GLOBS:
            if budgets.is_exceeded:
                break
            try:
                found = list_files(root, glob_pat, budgets, tracer)
            except BudgetExceededError as exc:
                warnings.append(
                    f"Budget exceeded listing {glob_pat} for id_refs: {exc}"
                )
                break
            for p in found:
                posix = p.as_posix()
                if posix not in seen_paths and not _should_skip(p, root):
                    if _in_scope(p, scope_paths):
                        seen_paths.add(posix)
                        id_files.append(p)

        # Sort once for deterministic processing order
        id_files.sort(key=lambda p: p.as_posix())

        for id_path in id_files:
            if budgets.is_exceeded:
                break
            try:
                rel = id_path.relative_to(root).as_posix()
            except ValueError:
                continue
            add_node(rel)
            try:
                id_edges = scan_id_refs(
                    id_path, root, budgets, tracer, allowlist=id_allowlist
                )
            except BudgetExceededError as exc:
                warnings.append(f"Budget exceeded scanning id_refs in {rel}: {exc}")
                break
            for ide in id_edges:
                add_edge("id_ref", ide.src, ide.dst, ide.evidence, rel)

    # -----------------------------------------------------------------------
    # Deterministic sort and finalise
    # -----------------------------------------------------------------------
    sorted_nodes = sorted(nodes.values(), key=lambda n: (n["kind"], n["id"]))
    sorted_edges = sorted(
        edge_list,
        key=lambda e: (e["kind"], e["src"], e["dst"], e["evidence"]),
    )

    budgets.set_graph_nodes(len(sorted_nodes))
    tracer.emit(
        "graph_build_done",
        edges=len(sorted_edges),
        nodes=len(sorted_nodes),
        warnings=len(warnings),
    )

    return {
        "edges": sorted_edges,
        "nodes": sorted_nodes,
        "warnings": warnings,
    }


def build_graph_from_files(
    files: list[pathlib.Path],
    root: pathlib.Path,
    repo_root: pathlib.Path,
    budgets: Optional[Budgets] = None,
    tracer: Optional[Tracer] = None,
    use_id_allowlist: bool = True,
) -> dict:
    """Build a dependency graph for an explicit set of files.

    Unlike :func:`build_graph`, this function does **not** walk the repository
    tree.  It processes the provided *files* list directly, applying the same
    three-phase edge extraction (Python imports, schema ``$ref``, and MMO
    canonical ID references) but only within the given file set.

    This is the core engine used by the seed-first diff build path so that
    only the files identified by :func:`~diff_seed_first.expand_seed_first_bfs`
    are scanned rather than the entire repository.

    Args:
        files: Explicit list of absolute file paths to scan.  The list should
               be pre-sorted for fully deterministic output; this function also
               sorts internally to guard against caller ordering.
        root: Used for computing POSIX-relative node IDs (typically the same
              as *repo_root*).
        repo_root: Used for import resolution and ontology discovery.
        budgets: Budget enforcer.  A fresh default :class:`Budgets` is created
                 if not provided.
        tracer: Trace sink.  A no-op :class:`Tracer` is used if not provided.
        use_id_allowlist: When ``True`` (default), build an ontology allowlist
                          and restrict ``id_ref`` edges to known canonical IDs.

    Returns:
        Same dict structure as :func:`build_graph`:
        ``{"nodes": [...], "edges": [...], "warnings": [...]}``.
    """
    if budgets is None:
        budgets = Budgets()
    if tracer is None:
        tracer = Tracer()

    nodes: dict[str, dict] = {}
    edge_list: list[dict] = []
    seen_edges: set[tuple[str, str, str, str]] = set()
    warnings: list[str] = []

    def add_node(node_id: str, kind: str = "file") -> None:
        if node_id not in nodes:
            nodes[node_id] = _node(node_id, kind)

    def add_edge(
        kind: str, src: str, dst: str, evidence: str, source_file: str
    ) -> None:
        key = (kind, src, dst, evidence)
        if key not in seen_edges:
            seen_edges.add(key)
            edge_list.append(_edge(kind, src, dst, evidence, source_file))
            add_node(src)
            add_node(dst)

    # Sort the input file list for determinism.
    sorted_files = sorted(files, key=lambda p: p.as_posix())

    tracer.emit(
        "graph_build_from_files_start",
        file_count=len(sorted_files),
        repo_root=str(repo_root),
        root=str(root),
    )

    # -----------------------------------------------------------------------
    # Phase 1: Python import edges + py_import_file resolved edges
    # -----------------------------------------------------------------------
    if not budgets.is_exceeded:
        for py_path in sorted_files:
            if py_path.suffix != ".py":
                continue
            if _should_skip(py_path, root):
                continue
            try:
                rel = py_path.relative_to(root).as_posix()
            except ValueError:
                continue
            add_node(rel)
            if budgets.is_exceeded:
                break
            try:
                import_edges = parse_py_imports(py_path, root, budgets, tracer)
            except BudgetExceededError as exc:
                warnings.append(f"Budget exceeded parsing imports in {rel}: {exc}")
                break
            for ie in import_edges:
                add_edge("py_import", ie.src, ie.dst, ie.evidence, rel)
                resolved = resolve_module_to_path(ie.dst, repo_root)
                if resolved is not None:
                    try:
                        resolved_rel = (
                            (repo_root / resolved)
                            .relative_to(root)
                            .as_posix()
                        )
                    except ValueError:
                        resolved_rel = resolved
                    add_edge(
                        "py_import_file",
                        ie.src,
                        resolved_rel,
                        ie.dst,
                        rel,
                    )

    # -----------------------------------------------------------------------
    # Phase 2: JSON schema $ref edges
    # -----------------------------------------------------------------------
    if not budgets.is_exceeded:
        for schema_path in sorted_files:
            if schema_path.suffix != ".json":
                continue
            if _should_skip(schema_path, root):
                continue
            is_schema = (
                "schemas" in schema_path.parts
                or schema_path.name.endswith(".schema.json")
            )
            if not is_schema:
                continue
            try:
                rel = schema_path.relative_to(root).as_posix()
            except ValueError:
                continue
            add_node(rel)
            if budgets.is_exceeded:
                break
            try:
                ref_edges = scan_schema_refs(schema_path, root, budgets, tracer)
            except BudgetExceededError as exc:
                warnings.append(f"Budget exceeded scanning schema refs in {rel}: {exc}")
                break
            for re_ in ref_edges:
                add_edge("schema_ref", re_.src, re_.dst, re_.evidence, rel)

    # -----------------------------------------------------------------------
    # Phase 3: MMO canonical ID references
    # -----------------------------------------------------------------------
    if not budgets.is_exceeded:
        id_allowlist: Optional[frozenset[str]] = None
        if use_id_allowlist:
            ont_root = repo_root / "ontology"
            raw_allowlist = build_id_allowlist(ont_root, budgets, tracer)
            if raw_allowlist:
                id_allowlist = raw_allowlist
                tracer.emit("id_allowlist_active", count=len(id_allowlist))
            else:
                warnings.append(
                    "id_ref allowlist is empty — falling back to full regex mode"
                )
                tracer.emit("id_allowlist_fallback", reason="empty_allowlist")

        _ID_REF_EXTS = frozenset({".py", ".yaml", ".yml", ".json", ".md"})
        id_files = sorted(
            [
                f for f in sorted_files
                if f.suffix in _ID_REF_EXTS and not _should_skip(f, root)
            ],
            key=lambda p: p.as_posix(),
        )

        for id_path in id_files:
            if budgets.is_exceeded:
                break
            try:
                rel = id_path.relative_to(root).as_posix()
            except ValueError:
                continue
            add_node(rel)
            try:
                id_edges = scan_id_refs(
                    id_path, root, budgets, tracer, allowlist=id_allowlist
                )
            except BudgetExceededError as exc:
                warnings.append(f"Budget exceeded scanning id_refs in {rel}: {exc}")
                break
            for ide in id_edges:
                add_edge("id_ref", ide.src, ide.dst, ide.evidence, rel)

    # -----------------------------------------------------------------------
    # Deterministic sort and finalise
    # -----------------------------------------------------------------------
    sorted_nodes = sorted(nodes.values(), key=lambda n: (n["kind"], n["id"]))
    sorted_edges = sorted(
        edge_list,
        key=lambda e: (e["kind"], e["src"], e["dst"], e["evidence"]),
    )

    budgets.set_graph_nodes(len(sorted_nodes))
    tracer.emit(
        "graph_build_from_files_done",
        edges=len(sorted_edges),
        nodes=len(sorted_nodes),
        warnings=len(warnings),
    )

    return {
        "edges": sorted_edges,
        "nodes": sorted_nodes,
        "warnings": warnings,
    }


def save_graph(graph: dict, path: pathlib.Path) -> None:
    """Write *graph* to *path* as deterministic JSON (sorted keys, 2-space indent).

    Creates parent directories as needed.

    Args:
        graph: The dict returned by :func:`build_graph`.
        path: Destination ``.json`` file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(graph, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def top_connected_nodes(graph: dict, n: int = 20) -> list[dict]:
    """Return the *n* most connected nodes by total edge degree.

    Degree is the sum of in-edges and out-edges.  Ties are broken
    alphabetically by ``id`` for determinism.

    Args:
        graph: The dict returned by :func:`build_graph`.
        n: Maximum number of nodes to return.

    Returns:
        List of ``{"degree": int, "id": str, "kind": str}`` dicts, sorted
        descending by degree then ascending by id.
    """
    degree: dict[str, int] = {}
    for edge in graph["edges"]:
        degree[edge["src"]] = degree.get(edge["src"], 0) + 1
        degree[edge["dst"]] = degree.get(edge["dst"], 0) + 1

    # Build kind lookup from nodes list
    kind_map: dict[str, str] = {n_["id"]: n_["kind"] for n_ in graph["nodes"]}

    ranked = [
        {
            "degree": deg,
            "id": node_id,
            "kind": kind_map.get(node_id, "file"),
        }
        for node_id, deg in degree.items()
    ]
    ranked.sort(key=lambda x: (-x["degree"], x["id"]))
    return ranked[:n]
