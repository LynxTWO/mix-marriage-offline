"""CLI entrypoint for the agent REPL harness.

Runs the graph-first loop: Locate → Graph → Plan → Patch (optional).

Modes
-----
graph-only
    Build the dependency graph and print a human-readable summary.
    Writes ``<out>/agent_graph.json`` and ``<out>/agent_trace.ndjson``.
    **No edits are made.**

plan
    Build the graph, then produce a structured plan listing the most
    connected files and suggested tests.
    Writes ``<out>/agent_graph.json``, ``<out>/agent_plan.json``, and
    ``<out>/agent_trace.ndjson``.  **No edits are made.**

patch
    Guarded stub: only proceeds if a valid graph artifact already exists
    (from a previous or the current run).  Does **not** perform autonomous
    edits.  A future agent extension may provide a ``--patch-file`` flag to
    apply a pre-approved, minimal diff.

Usage (from repo root)::

    python -m tools.agent.run graph-only
    python -m tools.agent.run plan --out sandbox_tmp/
    python -m tools.agent.run patch --graph sandbox_tmp/agent_graph.json
    python -m tools.agent.run graph-only --max-file-reads 120

Scoping (Upgrade 3)::

    python -m tools.agent.run graph-only --preset schemas
    python -m tools.agent.run graph-only --scope src/mmo/core --scope ontology
    python -m tools.agent.run graph-only --diff
    python -m tools.agent.run graph-only --diff --diff-cap 30

Budget overrides (CLI flags)::

    --max-steps N              (default 40)
    --max-file-reads N         (default 60)
    --max-total-lines N        (default 4000)
    --max-grep-hits N          (default 300)
    --max-graph-nodes-summary N (default 200)

Contract stamp (PR A)::

    --no-contract-stamp        Disable writing/validating the stamp
    --contract-stamp-path PATH Override the default stamp path

Hot-path index (PR B)::

    --no-index                 Disable writing the index
    --index-path PATH          Override the default index path
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib
import sys
from typing import Optional

# Support both ``python -m tools.agent.run`` (relative imports) and direct
# ``python tools/agent/run.py`` (absolute fallback).
if __package__:
    from .budgets import Budgets, BudgetConfig, BudgetExceededError
    from .contract_stamp import (
        ContractStamp,
        get_git_head_sha,
        make_contract_stamp,
        read_contract_stamp,
        validate_contract_stamp,
        write_contract_stamp,
    )
    from .graph_build import build_graph, save_graph, top_connected_nodes
    from .index_build import build_index, save_index
    from .scoping import (
        expand_diff_scope,
        filter_graph_to_scope,
        get_git_changed_files,
        resolve_scope_paths,
    )
    from .trace import Tracer
else:
    _here = pathlib.Path(__file__).resolve().parent.parent.parent
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))
    from tools.agent.budgets import Budgets, BudgetConfig, BudgetExceededError
    from tools.agent.contract_stamp import (
        ContractStamp,
        get_git_head_sha,
        make_contract_stamp,
        read_contract_stamp,
        validate_contract_stamp,
        write_contract_stamp,
    )
    from tools.agent.graph_build import build_graph, save_graph, top_connected_nodes
    from tools.agent.index_build import build_index, save_index
    from tools.agent.scoping import (
        expand_diff_scope,
        filter_graph_to_scope,
        get_git_changed_files,
        resolve_scope_paths,
    )
    from tools.agent.trace import Tracer


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.agent.run",
        description="Agent REPL harness for Mix Marriage Offline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "mode",
        choices=["graph-only", "plan", "patch"],
        help="Harness mode.",
    )
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path("."),
        help="Repository root to scan (default: current directory).",
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=pathlib.Path("sandbox_tmp"),
        help="Output directory for artifacts (default: sandbox_tmp/).",
    )
    parser.add_argument(
        "--graph",
        type=pathlib.Path,
        default=None,
        help=(
            "Existing graph artifact path (patch mode only; defaults to "
            "<out>/agent_graph.json)."
        ),
    )

    # Budget overrides
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--max-file-reads", type=int, default=60)
    parser.add_argument("--max-total-lines", type=int, default=4000)
    parser.add_argument("--max-grep-hits", type=int, default=300)
    parser.add_argument("--max-graph-nodes-summary", type=int, default=200)

    # Upgrade 3: scoping
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "Restrict scanning to files under PATH (relative to --root). "
            "Repeatable."
        ),
    )
    parser.add_argument(
        "--preset",
        choices=["core", "schemas", "ontology", "cli"],
        default=None,
        help=(
            "Named scope preset. "
            "core=src/mmo/core, schemas=schemas, ontology=ontology, "
            "cli=src/mmo/cli.py+src/mmo/cli_commands."
        ),
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        default=False,
        help=(
            "Diff-focused mode: restrict graph to files changed vs HEAD "
            "plus their graph neighbours. Requires git."
        ),
    )
    parser.add_argument(
        "--diff-cap",
        type=int,
        default=50,
        help="Maximum nodes to include in diff expansion (default: 50).",
    )

    # Upgrade 2: id allowlist
    parser.add_argument(
        "--no-id-allowlist",
        action="store_true",
        default=False,
        help=(
            "Disable ontology allowlist for id_ref edges; use full regex "
            "mode instead (more noise, no ontology dependency)."
        ),
    )

    # PR A: contract stamp
    parser.add_argument(
        "--no-contract-stamp",
        action="store_true",
        default=False,
        help=(
            "Disable writing (graph-only/plan) and validating (patch) the "
            "contract stamp artifact."
        ),
    )
    parser.add_argument(
        "--contract-stamp-path",
        type=pathlib.Path,
        default=None,
        help=(
            "Override the contract stamp path.  Default: "
            "<root>/.mmo_agent/graph_contract.json"
        ),
    )

    # PR B: hot-path index
    parser.add_argument(
        "--no-index",
        action="store_true",
        default=False,
        help="Disable writing the hot-path index artifact.",
    )
    parser.add_argument(
        "--index-path",
        type=pathlib.Path,
        default=None,
        help=(
            "Override the hot-path index path.  Default: "
            "<root>/.mmo_agent/agent_index.json"
        ),
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_and_save(
    root: pathlib.Path,
    out_dir: pathlib.Path,
    budgets: Budgets,
    tracer: Tracer,
    scope_paths: Optional[list[pathlib.Path]] = None,
    use_id_allowlist: bool = True,
) -> dict:
    """Run graph build and persist the artifact.  Returns the graph dict."""
    graph = build_graph(
        root=root,
        budgets=budgets,
        tracer=tracer,
        scope_paths=scope_paths,
        use_id_allowlist=use_id_allowlist,
    )
    save_graph(graph, out_dir / "agent_graph.json")
    return graph


def _print_summary(
    graph: dict,
    budgets: Budgets,
    out_dir: pathlib.Path,
) -> None:
    """Print a human-readable graph summary to stdout."""
    nodes = graph["nodes"]
    edges = graph["edges"]
    warnings = graph.get("warnings", [])

    n_py  = sum(1 for e in edges if e["kind"] == "py_import")
    n_pif = sum(1 for e in edges if e["kind"] == "py_import_file")
    n_sc  = sum(1 for e in edges if e["kind"] == "schema_ref")
    n_id  = sum(1 for e in edges if e["kind"] == "id_ref")

    print("=== Agent Graph Summary ===")
    print(f"Nodes            : {len(nodes)}")
    print(f"Edges total      : {len(edges)}")
    print(f"  py_import      : {n_py}")
    print(f"  py_import_file : {n_pif}")
    print(f"  schema_ref     : {n_sc}")
    print(f"  id_ref         : {n_id}")

    top = top_connected_nodes(graph, n=20)
    if top:
        print(f"\nTop {len(top)} most connected nodes (by degree):")
        for rank, node in enumerate(top, start=1):
            print(
                f"  {rank:2d}. [{node['kind']:6s}] "
                f"deg={node['degree']:4d}  {node['id']}"
            )

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ! {w}")

    if budgets.is_exceeded:
        print(f"\n[BUDGET EXCEEDED] first cap hit: {budgets.state.exceeded}")

    print(f"\nBudget usage : {budgets.summary()}")
    print(f"Artifacts    : {out_dir}/")


def _apply_diff_filter(
    graph: dict,
    root: pathlib.Path,
    diff_cap: int,
    out_dir: pathlib.Path,
    tracer: Tracer,
) -> Optional[dict]:
    """Get changed files, expand neighbours, filter graph.

    Returns the filtered graph, or None on failure (after printing an error).
    """
    try:
        seed_files = get_git_changed_files(root)
    except RuntimeError as exc:
        print(f"[ERROR] --diff requires git: {exc}", file=sys.stderr)
        tracer.emit("diff_mode_error", error=str(exc))
        return None

    tracer.emit(
        "diff_mode_seeds",
        cap=diff_cap,
        seed_count=len(seed_files),
        seeds=seed_files[:20],  # trace at most 20 for readability
    )

    if not seed_files:
        print("[INFO] --diff: no changed files vs HEAD; returning full graph.")
        return graph

    scope = expand_diff_scope(seed_files, graph, cap=diff_cap)
    filtered = filter_graph_to_scope(graph, scope)
    save_graph(filtered, out_dir / "agent_graph.json")

    tracer.emit(
        "diff_mode_done",
        included=len(scope),
        original_nodes=len(graph["nodes"]),
    )
    return filtered


def _find_git_root(start: pathlib.Path) -> pathlib.Path:
    """Walk up from *start* to find the git repo root (``.git`` dir).

    Returns *start* resolved if no git root is found (graceful fallback).
    """
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return start.resolve()  # filesystem root reached
        current = parent


def _stamp_path_default(root: pathlib.Path) -> pathlib.Path:
    """Return the default contract stamp path anchored to the git repo root.

    Always uses the git repo root (not just ``args.root``) so that scoped
    runs (e.g. ``--root ontology/``) do not create artifacts inside
    subdirectories of the repository.
    """
    return _find_git_root(root) / ".mmo_agent" / "graph_contract.json"


def _index_path_default(root: pathlib.Path) -> pathlib.Path:
    """Return the default hot-path index path anchored to the git repo root."""
    return _find_git_root(root) / ".mmo_agent" / "agent_index.json"


def _resolve_stamp_path(args: argparse.Namespace) -> pathlib.Path:
    if args.contract_stamp_path is not None:
        return args.contract_stamp_path.resolve()
    return _stamp_path_default(args.root)


def _resolve_index_path(args: argparse.Namespace) -> pathlib.Path:
    if args.index_path is not None:
        return args.index_path.resolve()
    return _index_path_default(args.root)


def _write_artifacts(
    args: argparse.Namespace,
    config: BudgetConfig,
    budgets: Budgets,
    tracer: Tracer,
    graph: dict,
) -> None:
    """Write contract stamp and hot-path index after a successful graph build.

    Both writes are best-effort: failures are reported but do not abort the run.

    Args:
        args: Parsed CLI arguments.
        config: The BudgetConfig used for this run.
        budgets: The Budgets instance (used for index building).
        tracer: Trace sink.
        graph: The final graph dict (after any diff filtering).
    """
    root = args.root.resolve()
    graph_path = args.out / "agent_graph.json"
    trace_path = args.out / "agent_trace.ndjson"

    # Compute git info once (shared by stamp and index)
    sha = get_git_head_sha(root)
    git_available = sha != "unknown"

    # Compute graph SHA-256 (used by both stamp and index)
    if graph_path.exists():
        _h = hashlib.sha256()
        _h.update(graph_path.read_bytes())
        graph_sha256 = _h.hexdigest()
    else:
        graph_sha256 = ""

    # -----------------------------------------------------------------------
    # PR A: Contract stamp
    # -----------------------------------------------------------------------
    if not args.no_contract_stamp:
        scope_dict = {
            "diff": args.diff,
            "diff_cap": args.diff_cap,
            "id_allowlist": not args.no_id_allowlist,
            "preset": args.preset,
            "scope_paths": sorted(args.scope),
        }
        budgets_dict = dataclasses.asdict(config)
        stamp = make_contract_stamp(
            repo_root=root,
            git_sha=sha,
            git_available=git_available,
            graph_path=graph_path.resolve(),
            trace_path=trace_path.resolve(),
            graph=graph,
            run_mode=args.mode,
            scope=scope_dict,
            budgets_config=budgets_dict,
        )
        stamp_path = _resolve_stamp_path(args)
        try:
            write_contract_stamp(stamp_path, stamp)
            tracer.emit("contract_stamp_written", path=str(stamp_path))
        except OSError as exc:
            print(f"[WARNING] Could not write contract stamp: {exc}", file=sys.stderr)
            tracer.emit("contract_stamp_error", error=str(exc))

    # -----------------------------------------------------------------------
    # PR B: Hot-path index
    # -----------------------------------------------------------------------
    if not args.no_index:
        index_path = _resolve_index_path(args)
        try:
            index = build_index(
                graph=graph,
                repo_root=root,
                budgets=budgets,
                tracer=tracer,
                git_sha=sha,
                git_available=git_available,
                graph_sha256=graph_sha256,
            )
            save_index(index_path, index)
            tracer.emit("index_written", path=str(index_path))
        except OSError as exc:
            print(f"[WARNING] Could not write index: {exc}", file=sys.stderr)
            tracer.emit("index_error", error=str(exc))


# ---------------------------------------------------------------------------
# Mode implementations
# ---------------------------------------------------------------------------

def _mode_graph_only(
    args: argparse.Namespace,
    config: BudgetConfig,
    budgets: Budgets,
    tracer: Tracer,
) -> int:
    """Build graph and print summary.  Exit 0 on success, 1 on budget stop."""
    scope_paths = resolve_scope_paths(args.root, args.scope, args.preset)
    tracer.emit(
        "scope_resolved",
        preset=args.preset,
        scope_paths=[str(p) for p in scope_paths],
    )

    try:
        graph = _build_and_save(
            args.root,
            args.out,
            budgets,
            tracer,
            scope_paths=scope_paths,
            use_id_allowlist=not args.no_id_allowlist,
        )
    except BudgetExceededError as exc:
        print(f"[STOPPED] Budget exceeded before graph could be built: {exc}",
              file=sys.stderr)
        tracer.emit("halted", reason=str(exc))
        return 1

    if args.diff:
        graph = _apply_diff_filter(graph, args.root, args.diff_cap, args.out, tracer)
        if graph is None:
            return 1

    _print_summary(graph, budgets, args.out)
    _write_artifacts(args, config, budgets, tracer, graph)
    return 1 if budgets.is_exceeded else 0


def _mode_plan(
    args: argparse.Namespace,
    config: BudgetConfig,
    budgets: Budgets,
    tracer: Tracer,
) -> int:
    """Build graph + emit a JSON plan.  Exit 0 on success, 1 on budget stop."""
    scope_paths = resolve_scope_paths(args.root, args.scope, args.preset)
    tracer.emit(
        "scope_resolved",
        preset=args.preset,
        scope_paths=[str(p) for p in scope_paths],
    )

    try:
        graph = _build_and_save(
            args.root,
            args.out,
            budgets,
            tracer,
            scope_paths=scope_paths,
            use_id_allowlist=not args.no_id_allowlist,
        )
    except BudgetExceededError as exc:
        print(f"[STOPPED] Budget exceeded: {exc}", file=sys.stderr)
        tracer.emit("halted", reason=str(exc))
        return 1

    if args.diff:
        graph = _apply_diff_filter(graph, args.root, args.diff_cap, args.out, tracer)
        if graph is None:
            return 1

    _print_summary(graph, budgets, args.out)

    top = top_connected_nodes(graph, n=10)
    plan: dict = {
        "mode": "plan",
        "note": (
            "Plan mode does not perform edits. "
            "Review top_files and the graph artifact before patching."
        ),
        "suggested_tests": ["tests/test_agent_harness.py"],
        "top_files": [n["id"] for n in top if n["kind"] == "file"],
    }
    plan_path = args.out / "agent_plan.json"
    plan_path.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nPlan written to : {plan_path}")
    _write_artifacts(args, config, budgets, tracer, graph)
    return 1 if budgets.is_exceeded else 0


def _mode_patch(
    args: argparse.Namespace,
    config: BudgetConfig,
    budgets: Budgets,
    tracer: Tracer,
) -> int:
    """Guarded patch stub.

    Contract:
    * If a contract stamp exists (and --no-contract-stamp is not set), validates
      it against the current repo state; exits with code 3 if invalid.
    * Refuses to proceed if no valid graph artifact exists (exit 2).
    * Does NOT autonomously edit files.
    * Returns exit code 3 on invalid stamp, 2 on refusal, 0 on stub success.

    This mode is scaffolding for a future agent extension that will accept a
    ``--patch-file`` argument or explicit edit instructions.
    """
    graph_path = args.graph or (args.out / "agent_graph.json")

    # -----------------------------------------------------------------------
    # PR A: Validate contract stamp before doing anything
    # -----------------------------------------------------------------------
    if not args.no_contract_stamp:
        stamp_path = _resolve_stamp_path(args)
        if stamp_path.exists():
            try:
                stamp = read_contract_stamp(stamp_path)
                errors = validate_contract_stamp(
                    stamp, args.root.resolve(), graph_path
                )
                if errors:
                    print(
                        "[REFUSED] Contract stamp validation failed "
                        f"({len(errors)} error(s)):",
                        file=sys.stderr,
                    )
                    for err in errors:
                        print(f"  - {err}", file=sys.stderr)
                    print(
                        f"  Stamp   : {stamp_path}\n"
                        f"  Fix     : re-run 'graph-only' or 'plan' mode to "
                        "refresh the stamp, or pass --no-contract-stamp to skip.",
                        file=sys.stderr,
                    )
                    tracer.emit(
                        "patch_refused",
                        errors=errors,
                        reason="invalid_contract_stamp",
                        stamp_path=str(stamp_path),
                    )
                    return 3
                tracer.emit("contract_stamp_valid", stamp_path=str(stamp_path))
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                print(
                    f"[WARNING] Could not read contract stamp ({exc}); "
                    "proceeding without stamp validation.",
                    file=sys.stderr,
                )
                tracer.emit("contract_stamp_read_error", error=str(exc))

    # -----------------------------------------------------------------------
    # Original patch guard: graph artifact must exist and be well-formed
    # -----------------------------------------------------------------------
    if not graph_path.exists():
        print(
            f"[REFUSED] Patch mode requires a graph artifact.\n"
            f"  Expected : {graph_path}\n"
            f"  Fix      : run 'graph-only' or 'plan' mode first.",
            file=sys.stderr,
        )
        tracer.emit(
            "patch_refused", path=str(graph_path), reason="no_graph_artifact"
        )
        return 2

    # Validate the graph artifact is well-formed
    try:
        raw = graph_path.read_text(encoding="utf-8")
        graph = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[REFUSED] Cannot parse graph artifact: {exc}", file=sys.stderr)
        tracer.emit("patch_refused", error=str(exc), reason="invalid_graph")
        return 2

    if not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        print(
            "[REFUSED] Graph artifact missing required keys: 'nodes' and 'edges'.",
            file=sys.stderr,
        )
        tracer.emit("patch_refused", reason="malformed_graph")
        return 2

    # Graph is valid — proceed with stub
    print(
        f"Graph validated : {len(graph['nodes'])} nodes, {len(graph['edges'])} edges\n"
        f"\n[STUB] Patch mode is scaffolded but not yet implemented for autonomous editing.\n"
        f"Provide a patch file or explicit edit instructions to a future agent extension.\n"
        f"Graph artifact  : {graph_path}"
    )
    tracer.emit(
        "patch_stub",
        edges=len(graph["edges"]),
        graph_path=str(graph_path),
        nodes=len(graph["nodes"]),
    )
    return 0


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    """Run the harness.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Unix exit code:
        * ``0`` — success
        * ``1`` — budget exceeded / error
        * ``2`` — refused (patch mode: no valid graph artifact)
        * ``3`` — refused (patch mode: contract stamp validation failed)
    """
    args = _parse_args(argv)

    config = BudgetConfig(
        max_file_reads=args.max_file_reads,
        max_graph_nodes_summary=args.max_graph_nodes_summary,
        max_grep_hits=args.max_grep_hits,
        max_steps=args.max_steps,
        max_total_lines=args.max_total_lines,
    )
    budgets = Budgets(config)
    args.out.mkdir(parents=True, exist_ok=True)

    trace_path = args.out / "agent_trace.ndjson"
    tracer = Tracer(trace_path)
    tracer.emit("run_start", mode=args.mode, root=str(args.root))

    dispatch = {
        "graph-only": _mode_graph_only,
        "plan": _mode_plan,
        "patch": _mode_patch,
    }
    rc = dispatch[args.mode](args, config, budgets, tracer)

    tracer.emit(
        "run_end",
        budget_summary=budgets.summary(),
        mode=args.mode,
        rc=rc,
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
