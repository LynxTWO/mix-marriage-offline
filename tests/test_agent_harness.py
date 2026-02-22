"""Tests for the agent REPL harness (tools/agent/).

Adds the repo root to sys.path so ``tools.agent.*`` is importable without
modifying conftest.py or pyproject.toml.

Test matrix:
    test_scan_schema_refs_finds_ref      schema_ref edges from a real schema file
    test_parse_py_imports_finds_import   py_import edges from a real .py file
    test_scan_id_refs_finds_canonical_id id_ref scan finds canonical MMO IDs
    test_build_graph_finds_schema_ref    graph builder: >=1 schema_ref edge
    test_build_graph_finds_py_import     graph builder: >=1 py_import edge
    test_build_graph_finds_id_ref        graph builder: >=1 id_ref edge
    test_budget_exceeded_file_reads      max_file_reads=1 stops with exceeded flag
    test_deterministic_output            two identical runs produce identical JSON
    test_patch_mode_refused_without_graph  patch mode returns 2 without artifact
    test_trace_writes_ndjson             tracer emits valid NDJSON records
    test_budget_config_defaults          BudgetConfig has expected default values
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Ensure repo root is on sys.path so ``import tools.agent`` works.
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.agent.budgets import Budgets, BudgetConfig, BudgetExceededError  # noqa: E402
from tools.agent.graph_build import build_graph, save_graph, top_connected_nodes  # noqa: E402
from tools.agent.repo_ops import (  # noqa: E402
    parse_py_imports,
    scan_id_refs,
    scan_schema_refs,
)
from tools.agent.run import main as harness_main  # noqa: E402
from tools.agent.trace import Tracer  # noqa: E402


# ---------------------------------------------------------------------------
# Paths to real repo artefacts used by tests
# ---------------------------------------------------------------------------
_SCHEMA_FILE = _REPO_ROOT / "schemas" / "render_request.schema.json"
_ACTIONS_YAML = _REPO_ROOT / "ontology" / "actions.yaml"
_CLI_PY = _REPO_ROOT / "src" / "mmo" / "resources.py"
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_ONTOLOGY_DIR = _REPO_ROOT / "ontology"
_CORE_DIR = _REPO_ROOT / "src" / "mmo" / "core"


def _budgets(max_file_reads: int = 200, max_total_lines: int = 200_000) -> Budgets:
    """Create a generous budget for scanning one subdirectory."""
    return Budgets(
        BudgetConfig(
            max_steps=500,
            max_file_reads=max_file_reads,
            max_total_lines=max_total_lines,
            max_grep_hits=5000,
            max_graph_nodes_summary=5000,
        )
    )


# ===========================================================================
# Unit tests: individual scanning functions on specific known files
# ===========================================================================

class TestScanSchemaRefs:
    def test_finds_refs_in_render_request(self) -> None:
        """render_request.schema.json has multiple $ref entries."""
        assert _SCHEMA_FILE.exists(), f"Test fixture missing: {_SCHEMA_FILE}"
        edges = scan_schema_refs(_SCHEMA_FILE, _REPO_ROOT, _budgets(), Tracer())
        assert len(edges) > 0, "Expected at least one $ref edge"

    def test_edge_src_is_relative_posix(self) -> None:
        edges = scan_schema_refs(_SCHEMA_FILE, _REPO_ROOT, _budgets(), Tracer())
        for e in edges:
            assert not e.src.startswith("/"), f"src should be relative: {e.src}"
            assert "\\" not in e.src, f"src should use POSIX separators: {e.src}"

    def test_local_ref_dst_contains_def_key(self) -> None:
        """Local $ref '#/$defs/layout_id' must produce a dst with 'layout_id'."""
        edges = scan_schema_refs(_SCHEMA_FILE, _REPO_ROOT, _budgets(), Tracer())
        dsts = {e.dst for e in edges}
        assert any("layout_id" in d for d in dsts), (
            f"Expected a dst containing 'layout_id', got: {sorted(dsts)[:5]}"
        )


class TestParseImports:
    def test_finds_imports_in_resources_py(self) -> None:
        """resources.py has standard-library imports."""
        assert _CLI_PY.exists(), f"Test fixture missing: {_CLI_PY}"
        edges = parse_py_imports(_CLI_PY, _REPO_ROOT, _budgets(), Tracer())
        assert len(edges) > 0, "Expected at least one import edge"

    def test_evidence_is_ast_import(self) -> None:
        edges = parse_py_imports(_CLI_PY, _REPO_ROOT, _budgets(), Tracer())
        for e in edges:
            assert e.evidence == "ast_import"

    def test_src_is_relative_posix(self) -> None:
        edges = parse_py_imports(_CLI_PY, _REPO_ROOT, _budgets(), Tracer())
        for e in edges:
            assert not e.src.startswith("/"), f"src should be relative: {e.src}"


class TestScanIdRefs:
    def test_finds_action_ids_in_actions_yaml(self) -> None:
        """ontology/actions.yaml contains ACTION.* IDs."""
        assert _ACTIONS_YAML.exists(), f"Test fixture missing: {_ACTIONS_YAML}"
        edges = scan_id_refs(_ACTIONS_YAML, _REPO_ROOT, _budgets(), Tracer())
        ids = {e.dst for e in edges}
        action_ids = [i for i in ids if i.startswith("ACTION.")]
        assert len(action_ids) > 0, (
            f"Expected ACTION.* IDs, sample found: {sorted(ids)[:5]}"
        )

    def test_finds_param_ids_in_actions_yaml(self) -> None:
        """actions.yaml references PARAM.* in required_params fields."""
        edges = scan_id_refs(_ACTIONS_YAML, _REPO_ROOT, _budgets(), Tracer())
        ids = {e.dst for e in edges}
        param_ids = [i for i in ids if i.startswith("PARAM.")]
        assert len(param_ids) > 0, (
            f"Expected PARAM.* IDs, sample found: {sorted(ids)[:5]}"
        )

    def test_finds_gate_ids_in_actions_yaml(self) -> None:
        """actions.yaml references GATE.* in gates fields."""
        edges = scan_id_refs(_ACTIONS_YAML, _REPO_ROOT, _budgets(), Tracer())
        ids = {e.dst for e in edges}
        gate_ids = [i for i in ids if i.startswith("GATE.")]
        assert len(gate_ids) > 0, (
            f"Expected GATE.* IDs, sample found: {sorted(ids)[:5]}"
        )

    def test_evidence_snippet_is_short(self) -> None:
        edges = scan_id_refs(_ACTIONS_YAML, _REPO_ROOT, _budgets(), Tracer())
        for e in edges:
            assert len(e.evidence) <= 80, (
                f"Evidence snippet too long ({len(e.evidence)}): {e.evidence!r}"
            )

    def test_results_are_sorted(self) -> None:
        edges = scan_id_refs(_ACTIONS_YAML, _REPO_ROOT, _budgets(), Tracer())
        assert edges == sorted(edges), "scan_id_refs must return sorted edges"


# ===========================================================================
# Integration tests: full build_graph on scoped subdirectories
# ===========================================================================

class TestBuildGraphSchemaRef:
    def test_finds_schema_ref_edges(self) -> None:
        """graph builder must find at least one schema_ref edge in schemas/."""
        graph = build_graph(root=_SCHEMAS_DIR, budgets=_budgets(200))
        schema_edges = [e for e in graph["edges"] if e["kind"] == "schema_ref"]
        assert len(schema_edges) > 0, (
            f"Expected schema_ref edges. warnings={graph['warnings']}"
        )

    def test_schema_ref_edges_have_required_keys(self) -> None:
        graph = build_graph(root=_SCHEMAS_DIR, budgets=_budgets(200))
        for e in graph["edges"]:
            if e["kind"] == "schema_ref":
                assert "src" in e and "dst" in e and "evidence" in e and "source_file" in e


class TestBuildGraphPyImport:
    def test_finds_py_import_edges(self) -> None:
        """graph builder must find at least one py_import edge in src/mmo/core/."""
        assert _CORE_DIR.exists(), f"Test fixture missing: {_CORE_DIR}"
        graph = build_graph(root=_CORE_DIR, budgets=_budgets(500, 500_000))
        import_edges = [e for e in graph["edges"] if e["kind"] == "py_import"]
        assert len(import_edges) > 0, (
            f"Expected py_import edges. warnings={graph['warnings']}"
        )


class TestBuildGraphIdRef:
    def test_finds_id_ref_edges(self) -> None:
        """graph builder must find at least one id_ref edge in ontology/."""
        graph = build_graph(root=_ONTOLOGY_DIR, budgets=_budgets(100))
        id_edges = [e for e in graph["edges"] if e["kind"] == "id_ref"]
        assert len(id_edges) > 0, (
            f"Expected id_ref edges. warnings={graph['warnings']}"
        )

    def test_finds_canonical_mmo_ids(self) -> None:
        """At least one id_ref dst must be a canonical MMO ID (uppercase prefix)."""
        graph = build_graph(root=_ONTOLOGY_DIR, budgets=_budgets(100))
        canonical_prefixes = (
            "ACTION.", "ROLE.", "FEATURE.", "ISSUE.", "PARAM.",
            "UNIT.", "EVID.", "LAYOUT.", "GATE.", "SPK.",
        )
        id_dsts = {e["dst"] for e in graph["edges"] if e["kind"] == "id_ref"}
        has_canonical = any(
            dst.startswith(pfx) for dst in id_dsts for pfx in canonical_prefixes
        )
        assert has_canonical, (
            f"Expected a canonical MMO ID. Sample dsts: {sorted(id_dsts)[:10]}"
        )


# ===========================================================================
# Budget enforcement
# ===========================================================================

class TestBudgetEnforcement:
    def test_max_file_reads_1_stops_graph(self) -> None:
        """With max_file_reads=1, the graph build must stop and report exceeded."""
        # schemas/ has 46+ JSON files; second read must trigger the cap.
        config = BudgetConfig(
            max_steps=200,
            max_file_reads=1,
            max_total_lines=999_999,
            max_grep_hits=9999,
        )
        budgets = Budgets(config)
        graph = build_graph(root=_SCHEMAS_DIR, budgets=budgets)
        # Either the budget flag is set or a warning was recorded.
        assert budgets.is_exceeded or any(
            "Budget exceeded" in w for w in graph.get("warnings", [])
        ), f"Expected budget exceeded. state={budgets.state}, warnings={graph['warnings']}"

    def test_budget_exceeded_error_carries_budget_name(self) -> None:
        """BudgetExceededError exposes the budget_name attribute."""
        budgets = Budgets(BudgetConfig(max_file_reads=0))
        with pytest.raises(BudgetExceededError) as exc_info:
            budgets.charge_file_read(10)
        err = exc_info.value
        assert err.budget_name == "max_file_reads"
        assert err.limit == 0
        assert err.value > err.limit

    def test_is_exceeded_false_initially(self) -> None:
        b = Budgets()
        assert not b.is_exceeded

    def test_is_exceeded_true_after_hit(self) -> None:
        b = Budgets(BudgetConfig(max_file_reads=1))
        try:
            b.charge_file_read(1)   # OK: file_reads=1, not > 1
            b.charge_file_read(1)   # EXCEEDS: file_reads=2 > 1
        except BudgetExceededError:
            pass
        assert b.is_exceeded
        assert b.state.exceeded == "max_file_reads"


# ===========================================================================
# Determinism
# ===========================================================================

class TestDeterminism:
    def test_two_runs_produce_identical_json(self) -> None:
        """Running build_graph twice on schemas/ must yield identical nodes+edges."""
        cfg = BudgetConfig(
            max_steps=200,
            max_file_reads=200,
            max_total_lines=200_000,
        )
        g1 = build_graph(root=_SCHEMAS_DIR, budgets=Budgets(cfg))
        g2 = build_graph(root=_SCHEMAS_DIR, budgets=Budgets(cfg))

        # Exclude warnings (they may vary if budget hits differ); compare core structure.
        j1 = json.dumps(
            {"edges": g1["edges"], "nodes": g1["nodes"]}, sort_keys=True
        )
        j2 = json.dumps(
            {"edges": g2["edges"], "nodes": g2["nodes"]}, sort_keys=True
        )
        assert j1 == j2, "Graph output is not deterministic across two runs"

    def test_nodes_sorted(self) -> None:
        graph = build_graph(root=_SCHEMAS_DIR, budgets=_budgets(200))
        node_keys = [(n["kind"], n["id"]) for n in graph["nodes"]]
        assert node_keys == sorted(node_keys), "Nodes must be sorted by (kind, id)"

    def test_edges_sorted(self) -> None:
        graph = build_graph(root=_SCHEMAS_DIR, budgets=_budgets(200))
        edge_keys = [
            (e["kind"], e["src"], e["dst"], e["evidence"])
            for e in graph["edges"]
        ]
        assert edge_keys == sorted(edge_keys), (
            "Edges must be sorted by (kind, src, dst, evidence)"
        )

    def test_save_graph_roundtrip(self) -> None:
        """save_graph writes valid JSON that round-trips through json.loads."""
        graph = build_graph(root=_SCHEMAS_DIR, budgets=_budgets(200))
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "graph.json"
            save_graph(graph, out)
            loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["nodes"] == graph["nodes"]
        assert loaded["edges"] == graph["edges"]


# ===========================================================================
# Patch mode guard
# ===========================================================================

class TestPatchModeGuard:
    def test_patch_refused_without_graph(self) -> None:
        """patch mode must return exit code 2 if no graph artifact exists."""
        with tempfile.TemporaryDirectory() as tmp:
            rc = harness_main([
                "patch",
                "--root", str(_REPO_ROOT),
                "--out", tmp,
                "--graph", str(pathlib.Path(tmp) / "nonexistent_graph.json"),
            ])
        assert rc == 2, f"Expected rc=2, got {rc}"

    def test_patch_proceeds_with_valid_graph(self) -> None:
        """patch mode must return 0 when a valid graph artifact is provided."""
        with tempfile.TemporaryDirectory() as tmp:
            # Build a minimal valid graph artifact first.
            graph_path = pathlib.Path(tmp) / "agent_graph.json"
            minimal = {"edges": [], "nodes": [], "warnings": []}
            graph_path.write_text(
                json.dumps(minimal, sort_keys=True) + "\n", encoding="utf-8"
            )
            rc = harness_main([
                "patch",
                "--root", str(_REPO_ROOT),
                "--out", tmp,
                "--graph", str(graph_path),
            ])
        assert rc == 0, f"Expected rc=0, got {rc}"

    def test_patch_refused_on_malformed_json(self) -> None:
        """patch mode must return 2 for a corrupt graph artifact."""
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = pathlib.Path(tmp) / "bad_graph.json"
            graph_path.write_text("not valid json", encoding="utf-8")
            rc = harness_main([
                "patch",
                "--root", str(_REPO_ROOT),
                "--out", tmp,
                "--graph", str(graph_path),
            ])
        assert rc == 2, f"Expected rc=2 for malformed JSON, got {rc}"


# ===========================================================================
# Tracer
# ===========================================================================

class TestTracer:
    def test_writes_ndjson(self) -> None:
        """Tracer must write valid NDJSON: one JSON object per line."""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "trace.ndjson"
            t = Tracer(path)
            t.emit("start", foo="bar")
            t.emit("end", count=42)
            lines = path.read_text(encoding="utf-8").splitlines()

        assert len(lines) == 2
        rec0 = json.loads(lines[0])
        rec1 = json.loads(lines[1])
        assert rec0["event"] == "start" and rec0["foo"] == "bar"
        assert rec1["event"] == "end" and rec1["count"] == 42
        assert rec0["seq"] == 1 and rec1["seq"] == 2

    def test_noop_tracer(self) -> None:
        """Tracer(path=None) must not raise or create files."""
        t = Tracer()   # no-op
        t.emit("hello", x=1)   # must not raise
        assert t.seq == 1

    def test_sorted_keys_in_ndjson(self) -> None:
        """Each NDJSON line must have keys in sorted order (deterministic)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "trace.ndjson"
            t = Tracer(path)
            t.emit("ev", zebra="z", apple="a")
            line = path.read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        keys = list(rec.keys())
        assert keys == sorted(keys), f"Keys not sorted: {keys}"


# ===========================================================================
# BudgetConfig defaults
# ===========================================================================

class TestBudgetConfigDefaults:
    def test_default_values(self) -> None:
        cfg = BudgetConfig()
        assert cfg.max_steps == 40
        assert cfg.max_file_reads == 60
        assert cfg.max_total_lines == 4000
        assert cfg.max_grep_hits == 300
        assert cfg.max_graph_nodes_summary == 200

    def test_summary_keys(self) -> None:
        b = Budgets()
        s = b.summary()
        assert "steps" in s
        assert "file_reads" in s
        assert "total_lines" in s
        assert "grep_hits" in s
        assert "graph_nodes" in s
        assert "exceeded" in s
