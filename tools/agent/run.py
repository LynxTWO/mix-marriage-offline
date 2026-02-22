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

Budget overrides (CLI flags)::

    --max-steps N              (default 40)
    --max-file-reads N         (default 60)
    --max-total-lines N        (default 4000)
    --max-grep-hits N          (default 300)
    --max-graph-nodes-summary N (default 200)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Optional

# Support both ``python -m tools.agent.run`` (relative imports) and direct
# ``python tools/agent/run.py`` (absolute fallback).
if __package__:
    from .budgets import Budgets, BudgetConfig, BudgetExceededError
    from .graph_build import build_graph, save_graph, top_connected_nodes
    from .trace import Tracer
else:
    _here = pathlib.Path(__file__).resolve().parent.parent.parent
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))
    from tools.agent.budgets import Budgets, BudgetConfig, BudgetExceededError
    from tools.agent.graph_build import build_graph, save_graph, top_connected_nodes
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
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _build_and_save(
    root: pathlib.Path,
    out_dir: pathlib.Path,
    budgets: Budgets,
    tracer: Tracer,
) -> dict:
    """Run graph build and persist the artifact.  Returns the graph dict."""
    graph = build_graph(root=root, budgets=budgets, tracer=tracer)
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

    n_py = sum(1 for e in edges if e["kind"] == "py_import")
    n_sc = sum(1 for e in edges if e["kind"] == "schema_ref")
    n_id = sum(1 for e in edges if e["kind"] == "id_ref")

    print("=== Agent Graph Summary ===")
    print(f"Nodes        : {len(nodes)}")
    print(f"Edges total  : {len(edges)}")
    print(f"  py_import  : {n_py}")
    print(f"  schema_ref : {n_sc}")
    print(f"  id_ref     : {n_id}")

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


# ---------------------------------------------------------------------------
# Mode implementations
# ---------------------------------------------------------------------------

def _mode_graph_only(
    args: argparse.Namespace,
    budgets: Budgets,
    tracer: Tracer,
) -> int:
    """Build graph and print summary.  Exit 0 on success, 1 on budget stop."""
    try:
        graph = _build_and_save(args.root, args.out, budgets, tracer)
    except BudgetExceededError as exc:
        print(f"[STOPPED] Budget exceeded before graph could be built: {exc}",
              file=sys.stderr)
        tracer.emit("halted", reason=str(exc))
        return 1
    _print_summary(graph, budgets, args.out)
    return 1 if budgets.is_exceeded else 0


def _mode_plan(
    args: argparse.Namespace,
    budgets: Budgets,
    tracer: Tracer,
) -> int:
    """Build graph + emit a JSON plan.  Exit 0 on success, 1 on budget stop."""
    try:
        graph = _build_and_save(args.root, args.out, budgets, tracer)
    except BudgetExceededError as exc:
        print(f"[STOPPED] Budget exceeded: {exc}", file=sys.stderr)
        tracer.emit("halted", reason=str(exc))
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
    return 1 if budgets.is_exceeded else 0


def _mode_patch(
    args: argparse.Namespace,
    budgets: Budgets,
    tracer: Tracer,
) -> int:
    """Guarded patch stub.

    Contract:
    * Refuses to proceed if no valid graph artifact exists.
    * Does NOT autonomously edit files.
    * Returns exit code 2 on refusal, 0 on stub success.

    This mode is scaffolding for a future agent extension that will accept a
    ``--patch-file`` argument or explicit edit instructions.
    """
    graph_path = args.graph or (args.out / "agent_graph.json")

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
        Unix exit code: 0 = success, 1 = budget exceeded / error, 2 = refused.
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
    rc = dispatch[args.mode](args, budgets, tracer)

    tracer.emit(
        "run_end",
        budget_summary=budgets.summary(),
        mode=args.mode,
        rc=rc,
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
