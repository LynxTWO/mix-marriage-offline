"""Validate an agent graph dict against the agent_graph JSON schema.

Public API:
    validate_graph(graph, schema_path=None) -> list[str]
        Returns a list of error strings.  An empty list means the graph is
        valid.  Uses jsonschema when available; falls back to a lightweight
        structural check if jsonschema is not installed.

Usage::

    from tools.agent.validate_graph import validate_graph

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    errors = validate_graph(graph)
    if errors:
        for err in errors:
            print(f"  [ERROR] {err}")
    else:
        print("Graph is valid.")
"""

from __future__ import annotations

import json
import pathlib
from typing import Optional

# ---------------------------------------------------------------------------
# Schema path
# ---------------------------------------------------------------------------

# Resolve relative to this file: tools/agent/validate_graph.py
# → repo root is three parents up  (tools/agent → tools → repo)
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_SCHEMA_PATH = _REPO_ROOT / "schemas" / "agent_graph.schema.json"

# Known valid edge kinds (structural fallback when jsonschema is unavailable)
_VALID_EDGE_KINDS: frozenset[str] = frozenset({
    "id_ref",
    "py_import",
    "py_import_file",
    "py_import_relative",
    "schema_ref",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_graph(
    graph: object,
    schema_path: Optional[pathlib.Path] = None,
) -> list[str]:
    """Validate *graph* against the agent_graph JSON schema.

    Two-phase validation:

    1. **Structural check** (always, no external dependencies):
       Verifies that *graph* is a dict with the required top-level keys
       (``nodes``, ``edges``, ``warnings``), that each node has ``id`` and
       ``kind`` string fields, and that each edge has the five required string
       fields with a recognised ``kind`` value.

    2. **JSON Schema check** (when jsonschema is installed):
       Full validation against ``schemas/agent_graph.schema.json`` (or the
       *schema_path* override).  Any jsonschema
       :class:`~jsonschema.ValidationError` is captured and returned as an
       error string.

    Args:
        graph: The object to validate (typically a ``dict`` loaded from
               ``agent_graph.json``).
        schema_path: Optional override for the schema file path.  Defaults
                     to the repo-local ``schemas/agent_graph.schema.json``.

    Returns:
        A list of human-readable error strings.  An empty list means the
        graph is valid.  Never raises.
    """
    errors: list[str] = []

    # -----------------------------------------------------------------------
    # Phase 1: structural check
    # -----------------------------------------------------------------------
    if not isinstance(graph, dict):
        return [f"Expected a dict, got {type(graph).__name__}"]

    for key in ("nodes", "edges", "warnings"):
        if key not in graph:
            errors.append(f"Missing required key: '{key}'")

    if errors:
        return errors  # cannot continue without the required keys

    nodes = graph["nodes"]
    edges = graph["edges"]
    warnings = graph["warnings"]

    if not isinstance(nodes, list):
        errors.append("'nodes' must be a list")
    if not isinstance(edges, list):
        errors.append("'edges' must be a list")
    if not isinstance(warnings, list):
        errors.append("'warnings' must be a list")

    if errors:
        return errors

    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{i}] is not a dict")
            continue
        for field in ("id", "kind"):
            if field not in node:
                errors.append(f"nodes[{i}] missing required field '{field}'")
            elif not isinstance(node[field], str):
                errors.append(f"nodes[{i}]['{field}'] must be a string")

    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"edges[{i}] is not a dict")
            continue
        for field in ("dst", "evidence", "kind", "source_file", "src"):
            if field not in edge:
                errors.append(f"edges[{i}] missing required field '{field}'")
            elif not isinstance(edge[field], str):
                errors.append(f"edges[{i}]['{field}'] must be a string")
        if isinstance(edge.get("kind"), str):
            if edge["kind"] not in _VALID_EDGE_KINDS:
                errors.append(
                    f"edges[{i}] unknown kind '{edge['kind']}'; "
                    f"expected one of {sorted(_VALID_EDGE_KINDS)}"
                )

    if errors:
        return errors

    # -----------------------------------------------------------------------
    # Phase 2: jsonschema check (optional)
    # -----------------------------------------------------------------------
    try:
        import jsonschema  # noqa: PLC0415

        spath = schema_path or _SCHEMA_PATH
        if not spath.is_file():
            # Schema file missing — skip JSON Schema check, structural was enough
            return errors

        try:
            schema = json.loads(spath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Could not load schema file ({spath}): {exc}")
            return errors

        try:
            jsonschema.validate(graph, schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"Schema validation error: {exc.message}")
        except jsonschema.SchemaError as exc:
            errors.append(f"Schema itself is invalid: {exc.message}")

    except ImportError:
        pass  # jsonschema not installed — structural check is sufficient

    return errors
