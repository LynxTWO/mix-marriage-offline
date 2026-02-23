"""Seed-first BFS expansion for diff-focused graph builds.

When ``--diff`` and ``--diff-seed-first`` are both active, this module builds
a smaller graph by starting from changed files (seeds) and crawling outward in
deterministic BFS steps, using cheap discovery passes first:

* ``.py`` files: AST import resolution (``py_import_file`` edges).
* JSON schema files: cross-file ``$ref`` resolution (``schema_ref`` edges).

Canonical ID edges are NOT followed during expansion (too expensive for
seed-first mode — those edges are emitted by the normal build phases later,
but only within the already-included file set).

Public API:
    expand_seed_first_bfs    BFS expansion from seed files; returns (file_list, parent_map).
"""

from __future__ import annotations

import pathlib
from typing import Optional

from .budgets import Budgets, BudgetExceededError
from .repo_ops import parse_py_imports, resolve_module_to_path, scan_schema_refs
from .trace import Tracer


def expand_seed_first_bfs(
    seeds: list[str],
    repo_root: pathlib.Path,
    max_frontier: int,
    max_steps: int,
    budgets: Budgets,
    tracer: Tracer,
) -> tuple[list[pathlib.Path], dict[str, dict]]:
    """BFS expansion from seed files using cheap AST + schema-ref discovery.

    Starts from *seeds*, then iteratively follows Python import edges and
    cross-file JSON schema ``$ref`` edges.  Canonical-ID edges are not
    followed here (they are handled by the normal build phases, which run only
    over the resulting scoped file set).

    All operations are deterministic: candidates are stable-sorted at every
    step, and tie-breaking of parent assignment uses the lexicographically
    smallest ``(parent_posix, edge_kind, evidence)`` triple.

    Args:
        seeds: POSIX-relative file paths from ``git diff`` (or explicit seeds).
               Paths that do not exist on disk are silently skipped.
        repo_root: Absolute repository root for path operations and import
                   resolution.
        max_frontier: Hard cap on the total number of files that may be
                      included in the expanded set (inclusive of seeds).
        max_steps: Maximum BFS depth (number of expansion steps after step 0).
        budgets: Budget tracker.  File reads are charged for each file parsed
                 during expansion.
        tracer: Trace sink.

    Returns:
        A ``(file_list, parent_map)`` tuple where:

        * ``file_list`` — sorted list of absolute :class:`~pathlib.Path`
          objects in the expanded scope.
        * ``parent_map`` — ``{child_posix: {"edge_kind": str, "evidence": str,
          "parent": parent_posix}}`` mapping each non-seed file to the
          canonical edge that first pulled it in.  Seeds have no entry.
    """
    tracer.emit(
        "seed_first_bfs_start",
        max_frontier=max_frontier,
        max_steps=max_steps,
        seed_count=len(seeds),
        seeds=sorted(seeds)[:20],
    )

    # Resolve seeds to absolute paths, skip non-existent files.
    # Keep insertion order deterministic by processing in sorted order.
    included: dict[str, pathlib.Path] = {}   # posix_rel -> abs_path
    parent_map: dict[str, dict] = {}

    for s in sorted(seeds):
        abs_p = (repo_root / s).resolve()
        if abs_p.exists():
            try:
                rel = abs_p.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            if rel not in included:
                included[rel] = abs_p

    if not included:
        tracer.emit(
            "seed_first_bfs_done",
            file_count=0,
            reason="no_valid_seeds",
            steps=0,
        )
        return [], {}

    tracer.emit("seed_first_step", frontier_size=len(included), step=0)

    # BFS
    frontier: list[pathlib.Path] = sorted(
        included.values(),
        key=lambda p: p.relative_to(repo_root).as_posix(),
    )

    steps_taken = 0
    for step in range(1, max_steps + 1):
        if not frontier or len(included) >= max_frontier:
            break

        steps_taken = step

        # candidates: posix_rel -> (abs_path, parent_posix, edge_kind, evidence)
        # When multiple paths lead to the same candidate, keep lex-min parent.
        candidates: dict[str, tuple[pathlib.Path, str, str, str]] = {}

        try:
            budgets.charge_step()
        except BudgetExceededError:
            tracer.emit("seed_first_budget_exceeded", phase="step_charge", step=step)
            break

        for file_path in frontier:
            try:
                rel = file_path.relative_to(repo_root).as_posix()
            except ValueError:
                continue

            if file_path.suffix == ".py":
                _expand_py_file(
                    file_path=file_path,
                    rel=rel,
                    repo_root=repo_root,
                    included=included,
                    candidates=candidates,
                    budgets=budgets,
                    tracer=tracer,
                    step=step,
                )

            elif file_path.suffix == ".json" and (
                "schemas" in file_path.parts
                or file_path.name.endswith(".schema.json")
            ):
                _expand_schema_file(
                    file_path=file_path,
                    rel=rel,
                    repo_root=repo_root,
                    included=included,
                    candidates=candidates,
                    budgets=budgets,
                    tracer=tracer,
                    step=step,
                )

        # Sort candidates and apply max_frontier cap.
        sorted_candidates = sorted(candidates.items(), key=lambda x: x[0])
        remaining_capacity = max_frontier - len(included)
        admitted = sorted_candidates[:remaining_capacity]

        if len(sorted_candidates) > len(admitted):
            tracer.emit(
                "seed_first_cap_applied",
                admitted=len(admitted),
                cap=max_frontier,
                candidates=len(sorted_candidates),
                step=step,
            )

        next_frontier: list[pathlib.Path] = []
        for posix_rel, (abs_p, parent_rel, edge_kind, evidence) in admitted:
            if posix_rel not in included:
                included[posix_rel] = abs_p
                parent_map[posix_rel] = {
                    "edge_kind": edge_kind,
                    "evidence": evidence,
                    "parent": parent_rel,
                }
                next_frontier.append(abs_p)

        tracer.emit(
            "seed_first_step",
            added=len(next_frontier),
            frontier_size=len(included),
            step=step,
        )

        if not next_frontier:
            tracer.emit("seed_first_bfs_stable", step=step)
            break

        frontier = sorted(
            next_frontier,
            key=lambda p: p.relative_to(repo_root).as_posix(),
        )

    file_list = sorted(
        included.values(),
        key=lambda p: p.relative_to(repo_root).as_posix(),
    )

    tracer.emit(
        "seed_first_bfs_done",
        file_count=len(file_list),
        steps=steps_taken,
    )
    return file_list, parent_map


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _try_add_candidate(
    posix_rel: str,
    abs_p: pathlib.Path,
    parent_rel: str,
    edge_kind: str,
    evidence: str,
    candidates: dict[str, tuple[pathlib.Path, str, str, str]],
) -> None:
    """Add or replace a candidate using lex-min (parent, edge_kind, evidence)."""
    new_key = (parent_rel, edge_kind, evidence)
    existing = candidates.get(posix_rel)
    if existing is None:
        candidates[posix_rel] = (abs_p, parent_rel, edge_kind, evidence)
    else:
        existing_key = (existing[1], existing[2], existing[3])
        if new_key < existing_key:
            candidates[posix_rel] = (abs_p, parent_rel, edge_kind, evidence)


def _expand_py_file(
    file_path: pathlib.Path,
    rel: str,
    repo_root: pathlib.Path,
    included: dict[str, pathlib.Path],
    candidates: dict[str, tuple[pathlib.Path, str, str, str]],
    budgets: Budgets,
    tracer: Tracer,
    step: int,
) -> None:
    """Expand a .py file by resolving its AST imports to repo files."""
    try:
        import_edges = parse_py_imports(file_path, repo_root, budgets, tracer)
    except BudgetExceededError:
        tracer.emit(
            "seed_first_budget_exceeded",
            phase="py_imports",
            step=step,
        )
        return

    for ie in import_edges:
        resolved = resolve_module_to_path(ie.dst, repo_root)
        if resolved is None:
            continue
        abs_resolved = (repo_root / resolved).resolve()
        if not abs_resolved.exists():
            continue
        try:
            resolved_rel = abs_resolved.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if resolved_rel not in included:
            _try_add_candidate(
                posix_rel=resolved_rel,
                abs_p=abs_resolved,
                parent_rel=rel,
                edge_kind="py_import_file",
                evidence=ie.dst,
                candidates=candidates,
            )


def _expand_schema_file(
    file_path: pathlib.Path,
    rel: str,
    repo_root: pathlib.Path,
    included: dict[str, pathlib.Path],
    candidates: dict[str, tuple[pathlib.Path, str, str, str]],
    budgets: Budgets,
    tracer: Tracer,
    step: int,
) -> None:
    """Expand a schema .json file by following cross-file $ref edges."""
    try:
        ref_edges = scan_schema_refs(file_path, repo_root, budgets, tracer)
    except BudgetExceededError:
        tracer.emit(
            "seed_first_budget_exceeded",
            phase="schema_refs",
            step=step,
        )
        return

    for re_ in ref_edges:
        # Skip local $defs refs (evidence starts with "#/")
        if re_.evidence.startswith("#/"):
            continue
        # Skip absolute URIs (http/https)
        if re_.dst.startswith(("http://", "https://", "//")):
            continue

        # Strip fragment from cross-file ref (e.g. "other.json#/$defs/foo")
        dst_file = re_.dst.split("#")[0].strip()
        if not dst_file:
            continue

        # Resolve relative to the schema file's parent directory
        try:
            ref_abs = (file_path.parent / dst_file).resolve()
            ref_rel = ref_abs.relative_to(repo_root).as_posix()
        except (ValueError, OSError):
            continue

        if not ref_abs.exists():
            continue
        if ref_rel not in included:
            _try_add_candidate(
                posix_rel=ref_rel,
                abs_p=ref_abs,
                parent_rel=rel,
                edge_kind="schema_ref",
                evidence=re_.evidence[:80],
                candidates=candidates,
            )
