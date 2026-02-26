"""Scope filtering, preset presets, and diff-expansion utilities.

Provides three complementary ways to narrow a graph build for faster daily use:

1. **Presets** — named shortcuts for common path scopes (``--preset core``, etc.).
2. **Scope paths** — explicit ``--scope <path>`` filters that restrict which
   files are scanned by :func:`~graph_build.build_graph`.
3. **Diff mode** — expand a set of git-changed files by one BFS step in the
   graph to include their immediate neighbours.

All operations are deterministic: stable-sorted inputs produce stable outputs.

Public API:
    PRESETS                  Dict mapping preset names to lists of relative paths.
    resolve_scope_paths      Convert CLI --scope/--preset args to absolute paths.
    get_git_changed_files    Run ``git diff --name-only HEAD`` and return changed files.
    expand_diff_scope        BFS-expand a seed file set using a pre-built graph.
    filter_graph_to_scope    Remove nodes/edges outside a frozenset of paths.
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Optional

# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

PRESETS: dict[str, list[str]] = {
    "core": ["src/mmo/core"],
    "schemas": ["schemas"],
    "ontology": ["ontology"],
    "cli": ["src/mmo/cli.py", "src/mmo/cli_commands"],
}
"""Preset name → list of repo-relative paths included in the scope.

These are the *documented* preset definitions; additional paths may appear in
graph output (e.g. ``id_ref`` destination nodes that are canonical ID strings
rather than file paths — those are not filtered by scope).
"""


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------

def resolve_scope_paths(
    root: pathlib.Path,
    scope_args: list[str],
    preset: Optional[str],
) -> list[pathlib.Path]:
    """Resolve ``--scope`` arguments and a ``--preset`` name to absolute paths.

    Args:
        root: Repository root (used to resolve relative paths).
        scope_args: List of relative or absolute path strings from ``--scope``.
        preset: Optional preset name or comma-separated list of preset names
            (keys in :data:`PRESETS`).  Example: ``"schemas,ontology"`` expands
            both the ``schemas`` and ``ontology`` presets.

    Returns:
        Sorted, deduplicated list of absolute :class:`pathlib.Path` objects.
        Returns an empty list if neither scope nor preset is specified, which
        means "no filtering — scan everything".
    """
    raw: list[pathlib.Path] = []

    if preset is not None:
        for preset_name in [p.strip() for p in preset.split(",") if p.strip()]:
            for rel in PRESETS.get(preset_name, []):
                raw.append(root / rel)

    for s in scope_args:
        p = pathlib.Path(s)
        raw.append(p if p.is_absolute() else root / p)

    # Deduplicate and sort for determinism
    seen: set[pathlib.Path] = set()
    result: list[pathlib.Path] = []
    for p in raw:
        if p not in seen:
            seen.add(p)
            result.append(p)
    result.sort(key=lambda p: p.as_posix())
    return result


# ---------------------------------------------------------------------------
# Git diff support
# ---------------------------------------------------------------------------

def get_git_changed_files(root: pathlib.Path) -> list[str]:
    """Run ``git diff --name-only HEAD`` and return sorted POSIX-relative paths.

    Args:
        root: Repository root (used as ``cwd`` for the git command).

    Returns:
        Sorted list of changed file paths (POSIX format, relative to *root*).

    Raises:
        RuntimeError: If ``git`` is not on ``$PATH`` or the command fails.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(root),
            capture_output=True,
            encoding="utf-8",
            text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "git is not available on PATH; --diff mode requires git"
        )

    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"git diff --name-only HEAD failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )

    files = sorted(
        line.strip() for line in result.stdout.splitlines() if line.strip()
    )
    return files


# ---------------------------------------------------------------------------
# BFS diff expansion
# ---------------------------------------------------------------------------

def expand_diff_scope(
    seed_files: list[str],
    graph: dict,
    cap: int = 50,
) -> frozenset[str]:
    """Breadth-first expansion from *seed_files* using *graph* edges.

    Starting from *seed_files*, the BFS adds neighbours reachable by any edge
    (in either direction).  The queue is stable-sorted at each step so that
    identical inputs always produce identical outputs.

    The expansion stops when *cap* total nodes have been included or the queue
    is exhausted, whichever comes first.

    Args:
        seed_files: Initial set of file paths (POSIX-relative, matching node
            ``"id"`` strings in *graph*).
        graph: The dict returned by :func:`~graph_build.build_graph`.
        cap: Hard cap on total included nodes (inclusive).

    Returns:
        Frozenset of node ``"id"`` strings (includes seeds + neighbours).
    """
    # Build bidirectional adjacency index from graph edges
    adj: dict[str, list[str]] = {}
    for edge in graph["edges"]:
        src, dst = edge["src"], edge["dst"]
        adj.setdefault(src, []).append(dst)
        adj.setdefault(dst, []).append(src)

    included: set[str] = set()
    # BFS queue: stable-sorted initial seeds
    queue: list[str] = sorted(set(seed_files))

    # Seed all valid nodes
    for f in queue:
        if f not in included:
            included.add(f)

    qi = 0
    while qi < len(queue) and len(included) < cap:
        current = queue[qi]
        qi += 1
        for neighbour in sorted(adj.get(current, [])):
            if neighbour not in included:
                included.add(neighbour)
                queue.append(neighbour)
                if len(included) >= cap:
                    break

    return frozenset(included)


# ---------------------------------------------------------------------------
# Graph filtering
# ---------------------------------------------------------------------------

def filter_graph_to_scope(
    graph: dict,
    scope: frozenset[str],
) -> dict:
    """Return a new graph dict containing only nodes and edges within *scope*.

    An edge is included only if **both** ``src`` and ``dst`` are in *scope*.
    Warnings are preserved unchanged.

    Args:
        graph: The dict returned by :func:`~graph_build.build_graph`.
        scope: Frozenset of node ``"id"`` strings to retain.

    Returns:
        New graph dict with ``"nodes"``, ``"edges"``, and ``"warnings"`` keys.
        Nodes and edges preserve their original sorted order.
    """
    filtered_nodes = [n for n in graph["nodes"] if n["id"] in scope]
    filtered_edges = [
        e for e in graph["edges"]
        if e["src"] in scope and e["dst"] in scope
    ]
    return {
        "edges": filtered_edges,
        "nodes": filtered_nodes,
        "warnings": list(graph.get("warnings", [])),
    }
