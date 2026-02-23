"""Tests for the agent REPL harness (tools/agent/).

Adds the repo root to sys.path so ``tools.agent.*`` is importable without
modifying conftest.py or pyproject.toml.

Test matrix:
    test_scan_schema_refs_finds_ref          schema_ref edges from a real schema file
    test_parse_py_imports_finds_import       py_import edges from a real .py file
    test_scan_id_refs_finds_canonical_id     id_ref scan finds canonical MMO IDs
    test_build_graph_finds_schema_ref        graph builder: >=1 schema_ref edge
    test_build_graph_finds_py_import         graph builder: >=1 py_import edge
    test_build_graph_finds_id_ref            graph builder: >=1 id_ref edge
    test_budget_exceeded_file_reads          max_file_reads=1 stops with exceeded flag
    test_deterministic_output                two identical runs produce identical JSON
    test_patch_mode_refused_without_graph    patch mode returns 2 without artifact
    test_trace_writes_ndjson                 tracer emits valid NDJSON records
    test_budget_config_defaults              BudgetConfig has expected default values
    test_py_import_file_in_repo_gets_edge    Upgrade 1: known import resolves to file
    test_stdlib_import_no_py_import_file     Upgrade 1: stdlib not resolved
    test_allowlist_reduces_noise             Upgrade 2: allowlist fewer edges than regex
    test_known_id_detected_in_allowlist_mode Upgrade 2: real ontology ID is kept
    test_preset_schemas_limits_scope         Upgrade 3: --preset schemas
    test_scope_ontology_only                 Upgrade 3: --scope ontology
    test_expand_diff_scope_deterministic     Upgrade 3: BFS expansion is deterministic
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
    build_id_allowlist,
    parse_py_imports,
    resolve_module_to_path,
    scan_id_refs,
    scan_schema_refs,
)
from tools.agent.run import main as harness_main  # noqa: E402
from tools.agent.scoping import (  # noqa: E402
    expand_diff_scope,
    filter_graph_to_scope,
)
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


# ===========================================================================
# Upgrade 1: py_import_file edges
# ===========================================================================

class TestPyImportFile:
    """Verify resolve_module_to_path and py_import_file graph edges."""

    def test_in_repo_module_resolves_to_file(self, tmp_path: pathlib.Path) -> None:
        """A known in-repo module gets resolved to its .py file path."""
        # Create a minimal package under tmp_path
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        mod = pkg / "utils.py"
        mod.write_text("x = 1\n", encoding="utf-8")

        resolved = resolve_module_to_path("mypkg.utils", tmp_path)
        assert resolved is not None, "Expected resolution for mypkg.utils"
        assert resolved == "mypkg/utils.py", f"Got: {resolved}"

    def test_package_init_resolves_when_no_py_file(self, tmp_path: pathlib.Path) -> None:
        """A package-level import resolves to __init__.py."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")

        resolved = resolve_module_to_path("mypkg", tmp_path)
        assert resolved is not None, "Expected resolution for mypkg"
        assert resolved == "mypkg/__init__.py", f"Got: {resolved}"

    def test_py_preferred_over_init(self, tmp_path: pathlib.Path) -> None:
        """.py file is preferred over __init__.py at the same priority level."""
        # Create both: mypkg.py and mypkg/__init__.py
        (tmp_path / "mypkg.py").write_text("", encoding="utf-8")
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")

        resolved = resolve_module_to_path("mypkg", tmp_path)
        assert resolved == "mypkg.py", (
            "Direct .py file should be preferred over __init__.py"
        )

    def test_stdlib_import_not_resolved(self, tmp_path: pathlib.Path) -> None:
        """Standard library modules (os, json, sys, …) must NOT resolve."""
        for module in ("os", "json", "sys", "pathlib", "re", "ast"):
            result = resolve_module_to_path(module, tmp_path)
            assert result is None, (
                f"Stdlib module '{module}' should not resolve, got: {result}"
            )

    def test_third_party_import_not_resolved(self, tmp_path: pathlib.Path) -> None:
        """Third-party modules not present under root must return None."""
        result = resolve_module_to_path("numpy", tmp_path)
        assert result is None

    def test_src_layout_resolution(self, tmp_path: pathlib.Path) -> None:
        """Modules under src/ are found via the 'src' prefix search."""
        src = tmp_path / "src"
        pkg = src / "myapp" / "core"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "engine.py").write_text("", encoding="utf-8")

        resolved = resolve_module_to_path("myapp.core.engine", tmp_path)
        assert resolved is not None, "Expected src-layout resolution"
        assert resolved == "src/myapp/core/engine.py", f"Got: {resolved}"

    def test_graph_emits_py_import_file_edges(self, tmp_path: pathlib.Path) -> None:
        """build_graph must emit py_import_file edges for resolvable imports."""
        # Create a tiny in-repo package
        pkg = tmp_path / "mymod"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        # importer.py imports from mymod
        (tmp_path / "importer.py").write_text(
            "from mymod import helper\n", encoding="utf-8"
        )
        (pkg / "helper.py").write_text("def f(): pass\n", encoding="utf-8")

        graph = build_graph(
            root=tmp_path,
            budgets=_budgets(50, 50_000),
            repo_root=tmp_path,
        )
        pif_edges = [e for e in graph["edges"] if e["kind"] == "py_import_file"]
        assert pif_edges, (
            "Expected at least one py_import_file edge. "
            f"All edges: {[e['kind'] for e in graph['edges']]}"
        )
        srcs = {e["src"] for e in pif_edges}
        dsts = {e["dst"] for e in pif_edges}
        assert "importer.py" in srcs
        assert any("mymod" in d for d in dsts), f"No mymod dst. dsts={dsts}"

    def test_py_import_file_edge_structure(self, tmp_path: pathlib.Path) -> None:
        """py_import_file edges must have kind, src, dst, evidence, source_file."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "main.py").write_text("import pkg\n", encoding="utf-8")

        graph = build_graph(root=tmp_path, budgets=_budgets(50, 50_000),
                            repo_root=tmp_path)
        pif_edges = [e for e in graph["edges"] if e["kind"] == "py_import_file"]
        for e in pif_edges:
            assert "kind" in e
            assert "src" in e
            assert "dst" in e
            assert "evidence" in e
            assert "source_file" in e
            assert e["kind"] == "py_import_file"
            # evidence must be the dotted module string
            assert "." not in e["dst"] or "/" in e["dst"], (
                f"dst should be a file path, got: {e['dst']}"
            )

    def test_graph_build_with_real_repo_has_py_import_file(self) -> None:
        """Real graph build on src/mmo/core must produce py_import_file edges."""
        assert _CORE_DIR.exists(), f"Test fixture missing: {_CORE_DIR}"
        graph = build_graph(
            root=_REPO_ROOT,
            budgets=_budgets(300, 300_000),
            repo_root=_REPO_ROOT,
            scope_paths=[_CORE_DIR],
        )
        pif_edges = [e for e in graph["edges"] if e["kind"] == "py_import_file"]
        assert pif_edges, (
            "Expected py_import_file edges in real core/ scan. "
            f"warnings={graph['warnings']}"
        )


# ===========================================================================
# Upgrade 2: Ontology allowlist for id_ref edges
# ===========================================================================

class TestIdAllowlist:
    """Verify allowlist mode reduces id_ref noise and keeps real IDs."""

    def _make_ontology(self, root: pathlib.Path, content: str) -> pathlib.Path:
        """Helper: create ontology/ dir with a single YAML file."""
        ont = root / "ontology"
        ont.mkdir(exist_ok=True)
        (ont / "test.yaml").write_text(content, encoding="utf-8")
        return ont

    def test_allowlist_built_from_yaml_keys(self, tmp_path: pathlib.Path) -> None:
        """build_id_allowlist extracts canonical IDs that appear as YAML keys."""
        ont = self._make_ontology(
            tmp_path,
            "actions:\n  ACTION.UTILITY.GAIN:\n    label: Gain\n",
        )
        result = build_id_allowlist(ont, _budgets(), Tracer())
        assert "ACTION.UTILITY.GAIN" in result

    def test_allowlist_includes_ids_from_values(self, tmp_path: pathlib.Path) -> None:
        """build_id_allowlist also picks up IDs that appear as YAML values."""
        ont = self._make_ontology(
            tmp_path,
            "required_params:\n  - PARAM.GAIN.DB\n",
        )
        result = build_id_allowlist(ont, _budgets(), Tracer())
        assert "PARAM.GAIN.DB" in result

    def test_allowlist_mode_reduces_noise(self, tmp_path: pathlib.Path) -> None:
        """Allowlist mode emits fewer id_ref edges than regex mode on same file.

        The test file contains one real canonical ID plus one snake-case alias
        (e.g. ``action_type = "drums"``) that regex mode would pick up but
        the allowlist would suppress.
        """
        ont = self._make_ontology(
            tmp_path,
            "actions:\n  ACTION.UTILITY.GAIN:\n    label: Gain\n",
        )
        # File with both a real canonical ID and a snake-case regex hit
        sample = tmp_path / "sample.py"
        sample.write_text(
            'x = "ACTION.UTILITY.GAIN"\n'
            'action_type = "drums"\n',   # regex false-positive (snake-case alias)
            encoding="utf-8",
        )

        b = _budgets()
        allowlist = build_id_allowlist(ont, b, Tracer())
        assert allowlist, "Allowlist must be non-empty"

        edges_regex = scan_id_refs(sample, tmp_path, _budgets(), Tracer(),
                                   allowlist=None)
        edges_allow = scan_id_refs(sample, tmp_path, _budgets(), Tracer(),
                                   allowlist=allowlist)

        assert len(edges_allow) < len(edges_regex), (
            f"Allowlist mode should produce fewer edges than regex mode. "
            f"regex={len(edges_regex)}, allowlist={len(edges_allow)}"
        )

    def test_known_real_id_detected_in_allowlist_mode(
        self, tmp_path: pathlib.Path
    ) -> None:
        """A real ontology ID is detected when allowlist mode is enabled."""
        ont = self._make_ontology(
            tmp_path,
            "roles:\n  ROLE.DRUMS.KICK:\n    label: Kick\n",
        )
        sample = tmp_path / "ref.py"
        sample.write_text('role = "ROLE.DRUMS.KICK"\n', encoding="utf-8")

        allowlist = build_id_allowlist(ont, _budgets(), Tracer())
        assert "ROLE.DRUMS.KICK" in allowlist

        edges = scan_id_refs(sample, tmp_path, _budgets(), Tracer(),
                             allowlist=allowlist)
        dsts = {e.dst for e in edges}
        assert "ROLE.DRUMS.KICK" in dsts, (
            f"Real ID ROLE.DRUMS.KICK must be detected. Got: {dsts}"
        )

    def test_id_not_in_allowlist_is_suppressed(self, tmp_path: pathlib.Path) -> None:
        """An ID not in the allowlist is suppressed in allowlist mode."""
        ont = self._make_ontology(
            tmp_path,
            "actions:\n  ACTION.UTILITY.GAIN:\n    label: Gain\n",
        )
        sample = tmp_path / "sample.py"
        sample.write_text(
            'a = "ACTION.UTILITY.GAIN"\n'   # in allowlist
            'b = "FEATURE.LFE.DETECT"\n',   # NOT in this allowlist
            encoding="utf-8",
        )
        allowlist = build_id_allowlist(ont, _budgets(), Tracer())
        edges = scan_id_refs(sample, tmp_path, _budgets(), Tracer(),
                             allowlist=allowlist)
        dsts = {e.dst for e in edges}
        assert "ACTION.UTILITY.GAIN" in dsts
        assert "FEATURE.LFE.DETECT" not in dsts

    def test_empty_allowlist_falls_back_to_regex(self, tmp_path: pathlib.Path) -> None:
        """When allowlist=frozenset() (empty), scan_id_refs uses full regex mode."""
        sample = tmp_path / "sample.py"
        sample.write_text('action_type = "drums"\n', encoding="utf-8")

        # Empty allowlist → should behave like no allowlist
        edges_none = scan_id_refs(sample, tmp_path, _budgets(), Tracer(),
                                  allowlist=None)
        edges_empty = scan_id_refs(sample, tmp_path, _budgets(), Tracer(),
                                   allowlist=frozenset())
        assert edges_none == edges_empty, (
            "Empty frozenset allowlist must be identical to None (regex mode)"
        )

    def test_allowlist_from_real_ontology_is_nonempty(self) -> None:
        """build_id_allowlist on the real ontology/ must return canonical IDs."""
        assert _ONTOLOGY_DIR.exists(), f"Ontology dir missing: {_ONTOLOGY_DIR}"
        result = build_id_allowlist(_ONTOLOGY_DIR, _budgets(200, 200_000), Tracer())
        assert len(result) > 0, "Expected IDs from real ontology"
        # Spot-check some expected canonical prefixes
        prefixes = ("ACTION.", "PARAM.", "ROLE.", "GATE.", "LAYOUT.", "ISSUE.")
        found = [p for p in prefixes if any(i.startswith(p) for i in result)]
        assert len(found) >= 3, (
            f"Expected multiple canonical prefixes, found: {found}"
        )

    def test_graph_allowlist_mode_on_real_ontology(self) -> None:
        """build_graph with allowlist enabled on ontology/ must find id_ref edges."""
        graph = build_graph(
            root=_ONTOLOGY_DIR,
            budgets=_budgets(200, 200_000),
            repo_root=_REPO_ROOT,
            use_id_allowlist=True,
        )
        id_edges = [e for e in graph["edges"] if e["kind"] == "id_ref"]
        assert len(id_edges) > 0, (
            f"Expected id_ref edges with allowlist. warnings={graph['warnings']}"
        )

    def test_graph_no_allowlist_more_edges_than_allowlist(self) -> None:
        """Regex mode (no allowlist) produces >= edges than allowlist mode on ontology."""
        budgets_a = _budgets(200, 200_000)
        budgets_b = _budgets(200, 200_000)
        g_allow = build_graph(
            root=_ONTOLOGY_DIR, budgets=budgets_a, repo_root=_REPO_ROOT,
            use_id_allowlist=True,
        )
        g_regex = build_graph(
            root=_ONTOLOGY_DIR, budgets=budgets_b, repo_root=_REPO_ROOT,
            use_id_allowlist=False,
        )
        id_allow = sum(1 for e in g_allow["edges"] if e["kind"] == "id_ref")
        id_regex = sum(1 for e in g_regex["edges"] if e["kind"] == "id_ref")
        assert id_allow <= id_regex, (
            f"Allowlist mode should not produce MORE id_ref edges than regex mode. "
            f"allowlist={id_allow}, regex={id_regex}"
        )


# ===========================================================================
# Upgrade 3: Scoped graph presets and diff-focused mode
# ===========================================================================

class TestScoping:
    """Verify --scope, --preset, and diff-mode BFS expansion."""

    def test_preset_schemas_limits_to_schemas_dir(self, tmp_path: pathlib.Path) -> None:
        """scope_paths for 'schemas' preset restricts file scanning to schemas/."""
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        (schemas_dir / "test.schema.json").write_text(
            '{"$schema": "http://json-schema.org/draft-07/schema"}',
            encoding="utf-8",
        )
        other_dir = tmp_path / "src"
        other_dir.mkdir()
        (other_dir / "module.py").write_text("import os\n", encoding="utf-8")

        graph = build_graph(
            root=tmp_path,
            budgets=_budgets(50, 50_000),
            repo_root=tmp_path,
            scope_paths=[schemas_dir],
        )
        # All scanned file nodes must be under schemas/
        file_nodes = [n for n in graph["nodes"] if "/" in n["id"]]
        outside = [n for n in file_nodes if not n["id"].startswith("schemas/")]
        assert not outside, (
            f"Nodes outside schemas/ found: {[n['id'] for n in outside]}"
        )

    def test_scope_ontology_only(self, tmp_path: pathlib.Path) -> None:
        """scope_paths restricted to ontology/ does not scan other dirs."""
        ont_dir = tmp_path / "ontology"
        ont_dir.mkdir()
        (ont_dir / "test.yaml").write_text(
            "actions:\n  ACTION.TEST:\n    label: T\n", encoding="utf-8"
        )
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "ignored.py").write_text("import os\n", encoding="utf-8")

        graph = build_graph(
            root=tmp_path,
            budgets=_budgets(50, 50_000),
            repo_root=tmp_path,
            scope_paths=[ont_dir],
        )
        # No .py file nodes; only ontology path nodes
        py_file_nodes = [
            n for n in graph["nodes"] if n["id"].endswith(".py")
        ]
        assert not py_file_nodes, (
            f"Expected no .py file nodes under ontology scope. Got: {py_file_nodes}"
        )

    def test_scope_filters_edges_to_included_files(self, tmp_path: pathlib.Path) -> None:
        """Edges whose src is outside scope are not emitted."""
        a_dir = tmp_path / "a"
        a_dir.mkdir()
        b_dir = tmp_path / "b"
        b_dir.mkdir()
        (a_dir / "file.py").write_text("import os\n", encoding="utf-8")
        (b_dir / "other.py").write_text("import sys\n", encoding="utf-8")

        # Only scope to a/
        graph_a = build_graph(
            root=tmp_path,
            budgets=_budgets(50, 50_000),
            repo_root=tmp_path,
            scope_paths=[a_dir],
        )
        graph_full = build_graph(
            root=tmp_path,
            budgets=_budgets(50, 50_000),
            repo_root=tmp_path,
        )
        # Scoped graph must have equal or fewer nodes than full graph
        assert len(graph_a["nodes"]) <= len(graph_full["nodes"])

    # -----------------------------------------------------------------------
    # expand_diff_scope (unit-testable without git)
    # -----------------------------------------------------------------------

    def test_expand_diff_scope_includes_seeds(self) -> None:
        """Seeds always appear in the result."""
        graph: dict = {"edges": [], "nodes": []}
        result = expand_diff_scope(["a.py", "b.py"], graph, cap=10)
        assert "a.py" in result
        assert "b.py" in result

    def test_expand_diff_scope_adds_neighbours(self) -> None:
        """Direct neighbours of seeds are included."""
        graph: dict = {
            "edges": [
                {"src": "a.py", "dst": "b.py", "kind": "py_import",
                 "evidence": "x", "source_file": "a.py"},
                {"src": "b.py", "dst": "c.py", "kind": "py_import",
                 "evidence": "y", "source_file": "b.py"},
            ],
            "nodes": [
                {"id": "a.py", "kind": "file"},
                {"id": "b.py", "kind": "file"},
                {"id": "c.py", "kind": "file"},
            ],
        }
        result = expand_diff_scope(["a.py"], graph, cap=10)
        # a.py → b.py (direct neighbour)
        assert "a.py" in result
        assert "b.py" in result

    def test_expand_diff_scope_respects_cap(self) -> None:
        """BFS stops when cap is reached."""
        # Chain: a→b→c→d→e→f
        edges = []
        nodes = []
        chain = ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"]
        for i, name in enumerate(chain):
            nodes.append({"id": name, "kind": "file"})
            if i < len(chain) - 1:
                edges.append({
                    "src": chain[i], "dst": chain[i + 1],
                    "kind": "py_import", "evidence": "x",
                    "source_file": chain[i],
                })
        graph: dict = {"edges": edges, "nodes": nodes}
        result = expand_diff_scope(["a.py"], graph, cap=3)
        assert len(result) <= 3

    def test_expand_diff_scope_is_deterministic(self) -> None:
        """Two calls with identical inputs produce identical frozensets."""
        graph: dict = {
            "edges": [
                {"src": "x.py", "dst": "y.py", "kind": "py_import",
                 "evidence": "e", "source_file": "x.py"},
                {"src": "x.py", "dst": "z.py", "kind": "schema_ref",
                 "evidence": "e", "source_file": "x.py"},
            ],
            "nodes": [
                {"id": "x.py", "kind": "file"},
                {"id": "y.py", "kind": "file"},
                {"id": "z.py", "kind": "file"},
            ],
        }
        r1 = expand_diff_scope(["x.py"], graph, cap=10)
        r2 = expand_diff_scope(["x.py"], graph, cap=10)
        assert r1 == r2

    def test_filter_graph_to_scope_keeps_only_scope_nodes(self) -> None:
        """filter_graph_to_scope removes nodes/edges outside scope."""
        graph: dict = {
            "edges": [
                {"src": "a.py", "dst": "b.py", "kind": "py_import",
                 "evidence": "e", "source_file": "a.py"},
                {"src": "b.py", "dst": "c.py", "kind": "py_import",
                 "evidence": "e", "source_file": "b.py"},
            ],
            "nodes": [
                {"id": "a.py", "kind": "file"},
                {"id": "b.py", "kind": "file"},
                {"id": "c.py", "kind": "file"},
            ],
            "warnings": [],
        }
        scope = frozenset({"a.py", "b.py"})
        filtered = filter_graph_to_scope(graph, scope)
        node_ids = {n["id"] for n in filtered["nodes"]}
        assert "c.py" not in node_ids
        assert "a.py" in node_ids
        assert "b.py" in node_ids
        # Edge b→c must be removed (c not in scope)
        for e in filtered["edges"]:
            assert e["src"] in scope and e["dst"] in scope

    def test_cli_preset_schemas_flag(self, tmp_path: pathlib.Path) -> None:
        """--preset schemas CLI flag runs without error."""
        rc = harness_main([
            "graph-only",
            "--root", str(_REPO_ROOT),
            "--out", str(tmp_path),
            "--preset", "schemas",
            "--max-file-reads", "200",
            "--max-total-lines", "100000",
            "--max-steps", "200",
        ])
        assert rc in (0, 1), f"Expected 0 or 1, got {rc}"

    def test_cli_scope_flag(self, tmp_path: pathlib.Path) -> None:
        """--scope ontology CLI flag runs without error."""
        rc = harness_main([
            "graph-only",
            "--root", str(_REPO_ROOT),
            "--out", str(tmp_path),
            "--scope", "ontology",
            "--max-file-reads", "200",
            "--max-total-lines", "100000",
            "--max-steps", "200",
        ])
        assert rc in (0, 1), f"Expected 0 or 1, got {rc}"

    def test_cli_no_id_allowlist_flag(self, tmp_path: pathlib.Path) -> None:
        """--no-id-allowlist CLI flag runs and graph still has id_ref edges."""
        rc = harness_main([
            "graph-only",
            "--root", str(_ONTOLOGY_DIR),
            "--out", str(tmp_path),
            "--no-id-allowlist",
            "--max-file-reads", "200",
            "--max-total-lines", "200000",
            "--max-steps", "200",
        ])
        assert rc in (0, 1), f"Expected 0 or 1, got {rc}"
        graph_path = tmp_path / "agent_graph.json"
        assert graph_path.exists()
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        id_edges = [e for e in graph["edges"] if e["kind"] == "id_ref"]
        assert id_edges, "Expected id_ref edges with --no-id-allowlist"
