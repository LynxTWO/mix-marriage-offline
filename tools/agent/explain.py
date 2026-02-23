"""Edge-path explanation for agent graph artifacts.

Provides two modes that work against an already-built ``agent_graph.json``
artifact (no repo re-scan needed):

``explain``
    Prints the shortest directed path from a seed (or an explicit
    ``--from-seed`` node) to a target node.  Tie-breaking is deterministic:
    when multiple shortest paths exist the one with the lexicographically
    smallest ``(kind, src, dst, evidence)`` edge sequence is chosen.

``explain-scope``
    Prints the seed list and the first-hop justification for every non-seed
    node recorded in ``graph.meta.parent_map`` (produced by a seed-first
    build).

Both modes are read-only: they never scan the repo or write files.

Public API:
    find_shortest_path    BFS shortest path between two nodes.
    run_explain           Handler for the ``explain`` CLI mode.
    run_explain_scope     Handler for the ``explain-scope`` CLI mode.
"""

from __future__ import annotations

import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Shortest-path algorithm
# ---------------------------------------------------------------------------

def find_shortest_path(
    graph: dict,
    from_node: str,
    to_node: str,
    directed: bool = True,
) -> Optional[list[dict]]:
    """Find the shortest path from *from_node* to *to_node* in *graph*.

    Uses BFS (unweighted).  When multiple shortest paths exist the path whose
    edge sequence is lexicographically smallest by
    ``(kind, src, dst, evidence)`` is returned.

    Args:
        graph: Graph dict with ``"edges"`` and ``"nodes"`` keys, as produced
               by :func:`~graph_build.build_graph`.
        from_node: Source node ``"id"`` string.
        to_node: Target node ``"id"`` string.
        directed: When ``True`` (default) edges are traversed in their
                  declared direction only.  When ``False`` edges may be
                  traversed in either direction.

    Returns:
        List of edge dicts on the path (may be empty when *from_node* equals
        *to_node*), or ``None`` if no path exists.
    """
    if from_node == to_node:
        return []

    # Build adjacency index: node -> sorted list of (neighbor, edge_dict).
    # Sorting at build time ensures the BFS explores in a deterministic order.
    adj: dict[str, list[tuple[str, dict]]] = {}
    for e in sorted(
        graph["edges"],
        key=lambda x: (x["kind"], x["src"], x["dst"], x["evidence"]),
    ):
        src, dst = e["src"], e["dst"]
        adj.setdefault(src, []).append((dst, e))
        if not directed:
            adj.setdefault(dst, []).append((src, e))

    # BFS: layer-by-layer with deterministic tie-breaking.
    # parent[node] = (prev_node, edge_dict) — records the lex-min edge that
    # first reached each node.
    parent: dict[str, tuple[str, dict]] = {}
    visited: set[str] = {from_node}
    current_layer: list[str] = [from_node]

    while current_layer:
        # next_candidates: node -> (prev_node, edge) for lex-min incoming edge
        next_candidates: dict[str, tuple[str, dict]] = {}

        for node in sorted(current_layer):
            for neighbor, edge in adj.get(node, []):
                if neighbor in visited:
                    continue
                edge_key = (edge["kind"], edge["src"], edge["dst"], edge["evidence"])
                if neighbor not in next_candidates:
                    next_candidates[neighbor] = (node, edge)
                else:
                    existing_node, existing_edge = next_candidates[neighbor]
                    existing_key = (
                        existing_edge["kind"],
                        existing_edge["src"],
                        existing_edge["dst"],
                        existing_edge["evidence"],
                    )
                    if edge_key < existing_key:
                        next_candidates[neighbor] = (node, edge)

        next_layer = sorted(next_candidates.keys())
        found = False
        for node in next_layer:
            if node not in visited:
                visited.add(node)
                parent[node] = next_candidates[node]
                if node == to_node:
                    found = True
        if found:
            break
        current_layer = next_layer

    if to_node not in parent:
        return None

    # Reconstruct path by tracing back through parent pointers.
    path: list[dict] = []
    node = to_node
    while node != from_node:
        prev_node, edge = parent[node]
        path.append(edge)
        node = prev_node
    path.reverse()
    return path


# ---------------------------------------------------------------------------
# Explain mode
# ---------------------------------------------------------------------------

def run_explain(
    graph: dict,
    target: str,
    from_seed: Optional[str],
    max_hops: int,
    directed: bool,
) -> int:
    """Print the shortest path from a seed (or *from_seed*) to *target*.

    Args:
        graph: Loaded graph dict.
        target: Target node id to explain.
        from_seed: Explicit starting node, or ``None`` to try seeds from
                   ``graph.meta.seeds`` (or all nodes as a last resort).
        max_hops: Maximum path length to report.  Longer paths are reported
                  but still shown (the cap is advisory for display).
        directed: Whether to treat edges as directed.

    Returns:
        Unix exit code: ``0`` on success, ``1`` on error.
    """
    node_ids = {n["id"] for n in graph.get("nodes", [])}

    if target not in node_ids:
        print(
            f"[ERROR] Target '{target}' not found in graph.",
            file=sys.stderr,
        )
        print(
            f"        Graph has {len(node_ids)} nodes.",
            file=sys.stderr,
        )
        return 1

    # Determine which nodes to search from.
    if from_seed is not None:
        if from_seed not in node_ids:
            print(
                f"[ERROR] From-seed '{from_seed}' not found in graph.",
                file=sys.stderr,
            )
            return 1
        from_nodes: list[str] = [from_seed]
    else:
        meta = graph.get("meta", {})
        seeds: list[str] = sorted(meta.get("seeds", []))
        if seeds:
            from_nodes = seeds
        else:
            # No seeds known — search from every node (expensive but complete).
            from_nodes = sorted(node_ids)

    # Find the shortest path from any from-node to target.
    # Tie-break: shorter path wins; equal length → lex-min edge sequence.
    best_path: Optional[list[dict]] = None
    best_from: Optional[str] = None

    for fn in from_nodes:
        if fn == target:
            best_path = []
            best_from = fn
            break
        path = find_shortest_path(graph, fn, target, directed=directed)
        if path is None:
            continue
        if len(path) > max_hops:
            continue
        if best_path is None or len(path) < len(best_path):
            best_path = path
            best_from = fn
        elif len(path) == len(best_path):
            path_key = [
                (e["kind"], e["src"], e["dst"], e["evidence"]) for e in path
            ]
            best_key = [
                (e["kind"], e["src"], e["dst"], e["evidence"]) for e in best_path
            ]
            if path_key < best_key:
                best_path = path
                best_from = fn

    if best_path is None:
        print(
            f"[ERROR] No path found to '{target}' within {max_hops} hops.",
            file=sys.stderr,
        )
        if directed:
            print(
                "  [HINT] Try --undirected to allow reverse edge traversal.",
                file=sys.stderr,
            )
        return 1

    # Print results.
    print(f"target     : {target}")
    print(f"from       : {best_from}")
    print(f"hops       : {len(best_path)}")
    if best_path:
        print()
        for i, edge in enumerate(best_path):
            ev = edge.get("evidence", "")[:60].replace("\n", " ")
            print(
                f"  [{i}] {edge['kind']}: {edge['src']} -> {edge['dst']}"
                f" | evidence: {ev}"
            )
    else:
        print("  (target is a seed — zero hops)")

    return 0


# ---------------------------------------------------------------------------
# Explain-scope mode
# ---------------------------------------------------------------------------

def run_explain_scope(
    graph: dict,
    max_display: int = 30,
) -> int:
    """Print seeds and first-hop justifications from ``graph.meta.parent_map``.

    Args:
        graph: Loaded graph dict.
        max_display: Maximum number of non-seed nodes to display.

    Returns:
        Unix exit code: always ``0``.
    """
    meta = graph.get("meta", {})
    seeds: list[str] = sorted(meta.get("seeds", []))
    parent_map: dict[str, dict] = meta.get("parent_map", {})

    if not seeds and not parent_map:
        print(
            "[INFO] Graph has no seed-first metadata.\n"
            "       Run with --diff (or --diff --diff-seed-first) to populate seeds."
        )
        print(f"       Nodes in graph: {len(graph.get('nodes', []))}")
        return 0

    print(f"seeds ({len(seeds)}):")
    for s in seeds:
        print(f"  {s}")

    if not parent_map:
        print(
            "\n[INFO] No parent_map in graph.meta — "
            "run with --diff --diff-seed-first to get first-hop justifications."
        )
        return 0

    seed_set = set(seeds)
    non_seed_nodes = sorted(k for k in parent_map if k not in seed_set)
    displayed = non_seed_nodes[:max_display]
    total = len(non_seed_nodes)

    print(f"\nnon-seed nodes ({len(displayed)} of {total} shown):")
    for node in displayed:
        info = parent_map[node]
        ev = str(info.get("evidence", ""))[:50].replace("\n", " ")
        print(f"  {node}")
        print(
            f"    via {info.get('edge_kind', '?')}: "
            f"{info.get('parent', '?')} | evidence: {ev}"
        )

    if total > max_display:
        print(f"\n  ... {total - max_display} more nodes not shown.")

    return 0
