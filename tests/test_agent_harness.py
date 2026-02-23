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

PR A — contract stamp:
    TestContractStamp.test_stamp_written_after_graph_only_run
    TestContractStamp.test_stamp_determinism
    TestContractStamp.test_validate_detects_graph_sha_mismatch
    TestContractStamp.test_validate_detects_git_sha_mismatch
    TestContractStamp.test_patch_returns_3_on_invalid_stamp
    TestContractStamp.test_patch_returns_0_on_valid_stamp
    TestContractStamp.test_no_contract_stamp_flag_skips_writing

PR B — hot-path index:
    TestAgentIndex.test_index_written_after_graph_only_run
    TestAgentIndex.test_index_is_deterministic
    TestAgentIndex.test_module_to_file_has_entry
    TestAgentIndex.test_id_to_occurrences_has_canonical_id
    TestAgentIndex.test_schema_to_refs_has_refs
    TestAgentIndex.test_no_index_flag_skips_writing
    TestAgentIndex.test_low_budget_warns_on_occurrences

Part 1 — seed-first diff build:
    TestSeedFirstDiffBuild.test_bfs_returns_seeds_as_files
    TestSeedFirstDiffBuild.test_bfs_expands_py_imports
    TestSeedFirstDiffBuild.test_bfs_respects_max_frontier
    TestSeedFirstDiffBuild.test_bfs_respects_max_steps
    TestSeedFirstDiffBuild.test_bfs_deterministic
    TestSeedFirstDiffBuild.test_bfs_parent_map_populated
    TestSeedFirstDiffBuild.test_bfs_missing_seed_skipped
    TestSeedFirstDiffBuild.test_build_graph_from_files_basic
    TestSeedFirstDiffBuild.test_build_graph_from_files_py_import_edge
    TestSeedFirstDiffBuild.test_build_graph_from_files_deterministic
    TestSeedFirstDiffBuild.test_diff_seed_first_flag_accepted_by_cli

Part 2 — explain mode:
    TestExplainMode.test_shortest_path_linear
    TestExplainMode.test_shortest_path_no_path_returns_none
    TestExplainMode.test_shortest_path_same_node_returns_empty
    TestExplainMode.test_shortest_path_tie_breaking_deterministic
    TestExplainMode.test_shortest_path_undirected
    TestExplainMode.test_run_explain_basic
    TestExplainMode.test_run_explain_target_not_in_graph
    TestExplainMode.test_run_explain_from_seed
    TestExplainMode.test_run_explain_no_path
    TestExplainMode.test_run_explain_scope_no_meta
    TestExplainMode.test_run_explain_scope_with_parent_map
    TestExplainMode.test_cli_explain_mode
    TestExplainMode.test_cli_explain_scope_mode

PR C — budget profiles and index skip:
    TestProfileAndIndexSkip.test_profile_code_raises_budget_defaults
    TestProfileAndIndexSkip.test_profile_code_does_not_override_explicit_flags
    TestProfileAndIndexSkip.test_profile_code_sets_default_skip_paths
    TestProfileAndIndexSkip.test_profile_code_does_not_override_explicit_skip_paths
    TestProfileAndIndexSkip.test_no_profile_leaves_defaults_unchanged
    TestProfileAndIndexSkip.test_is_path_skipped_exact_match
    TestProfileAndIndexSkip.test_is_path_skipped_prefix_match
    TestProfileAndIndexSkip.test_is_path_skipped_partial_prefix_no_match
    TestProfileAndIndexSkip.test_is_path_skipped_unrelated_path
    TestProfileAndIndexSkip.test_is_path_skipped_empty_skip_set
    TestProfileAndIndexSkip.test_build_id_occurrences_skips_docs_files
    TestProfileAndIndexSkip.test_build_id_occurrences_no_skip_includes_all
    TestProfileAndIndexSkip.test_cli_profile_code_flag_accepted
    TestProfileAndIndexSkip.test_cli_index_skip_path_flag_accepted
    TestProfileAndIndexSkip.test_cli_profile_code_raises_budget_vs_default
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
from tools.agent.contract_stamp import (  # noqa: E402
    ContractStamp,
    get_git_head_sha,
    make_contract_stamp,
    read_contract_stamp,
    validate_contract_stamp,
    write_contract_stamp,
)
from tools.agent.diff_seed_first import expand_seed_first_bfs  # noqa: E402
from tools.agent.explain import find_shortest_path, run_explain, run_explain_scope  # noqa: E402
from tools.agent.graph_build import (  # noqa: E402
    build_graph,
    build_graph_from_files,
    save_graph,
    top_connected_nodes,
)
from tools.agent.index_build import build_index, save_index  # noqa: E402
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
                "--no-contract-stamp",
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
                "--no-contract-stamp",
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
                "--no-contract-stamp",
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
            "--no-contract-stamp",
            "--no-index",
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
            "--no-contract-stamp",
            "--no-index",
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
            "--no-contract-stamp",
            "--no-index",
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


# ===========================================================================
# PR A: Contract Stamp
# ===========================================================================

class TestContractStamp:
    """Tests for tools/agent/contract_stamp.py and its integration in run.py."""

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _minimal_graph() -> dict:
        return {
            "edges": [
                {
                    "dst": "b.py",
                    "evidence": "mypkg",
                    "kind": "py_import_file",
                    "source_file": "a.py",
                    "src": "a.py",
                }
            ],
            "nodes": [{"id": "a.py", "kind": "file"}, {"id": "b.py", "kind": "file"}],
            "warnings": [],
        }

    @staticmethod
    def _write_minimal_graph(path: pathlib.Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(TestContractStamp._minimal_graph(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _make_stamp(
        tmp_path: pathlib.Path,
        graph_path: pathlib.Path,
        git_sha: str = "abc123def456abc123def456abc123def456abc1",
        git_available: bool = True,
    ) -> ContractStamp:
        return make_contract_stamp(
            repo_root=tmp_path,
            git_sha=git_sha,
            git_available=git_available,
            graph_path=graph_path,
            trace_path=tmp_path / "agent_trace.ndjson",
            graph=TestContractStamp._minimal_graph(),
            run_mode="graph-only",
            scope={
                "diff": False,
                "diff_cap": 50,
                "id_allowlist": True,
                "preset": None,
                "scope_paths": [],
            },
            budgets_config={
                "max_file_reads": 60,
                "max_graph_nodes_summary": 200,
                "max_grep_hits": 300,
                "max_steps": 40,
                "max_total_lines": 4000,
            },
        )

    # -----------------------------------------------------------------------
    # Unit: make / write / read round-trip
    # -----------------------------------------------------------------------

    def test_stamp_written_after_graph_only_run(self, tmp_path: pathlib.Path) -> None:
        """graph-only run must write a contract stamp file."""
        stamp_path = tmp_path / "stamp.json"
        out_dir = tmp_path / "out"
        rc = harness_main([
            "graph-only",
            "--root", str(_REPO_ROOT),
            "--out", str(out_dir),
            "--contract-stamp-path", str(stamp_path),
            "--no-index",
            "--max-file-reads", "200",
            "--max-total-lines", "100000",
            "--max-steps", "200",
            "--preset", "schemas",
        ])
        assert rc in (0, 1), f"Expected 0 or 1, got {rc}"
        assert stamp_path.exists(), "Contract stamp must be written after graph-only run"
        stamp_raw = json.loads(stamp_path.read_text(encoding="utf-8"))
        assert stamp_raw["version"] == 1
        assert "graph_sha256" in stamp_raw
        assert "git_sha" in stamp_raw
        assert "budgets" in stamp_raw
        assert "scope" in stamp_raw
        assert stamp_raw["run_mode"] == "graph-only"

    def test_stamp_determinism(self, tmp_path: pathlib.Path) -> None:
        """Writing the same stamp twice must produce byte-identical JSON."""
        graph_path = tmp_path / "graph.json"
        self._write_minimal_graph(graph_path)

        stamp = self._make_stamp(tmp_path, graph_path)

        out1 = tmp_path / "stamp1.json"
        out2 = tmp_path / "stamp2.json"
        write_contract_stamp(out1, stamp)
        write_contract_stamp(out2, stamp)

        assert out1.read_bytes() == out2.read_bytes(), (
            "Contract stamp must be deterministic: identical bytes on repeated writes"
        )

    def test_read_roundtrip(self, tmp_path: pathlib.Path) -> None:
        """write then read must produce equal ContractStamp objects."""
        graph_path = tmp_path / "graph.json"
        self._write_minimal_graph(graph_path)
        stamp = self._make_stamp(tmp_path, graph_path)

        stamp_path = tmp_path / "stamp.json"
        write_contract_stamp(stamp_path, stamp)
        loaded = read_contract_stamp(stamp_path)

        assert loaded.version == stamp.version
        assert loaded.graph_sha256 == stamp.graph_sha256
        assert loaded.git_sha == stamp.git_sha
        assert loaded.graph_node_count == stamp.graph_node_count
        assert loaded.graph_edge_count == stamp.graph_edge_count
        assert loaded.run_mode == stamp.run_mode

    # -----------------------------------------------------------------------
    # Unit: validate_contract_stamp
    # -----------------------------------------------------------------------

    def test_validate_valid_stamp_returns_no_errors(self, tmp_path: pathlib.Path) -> None:
        """A correctly built stamp must pass validation."""
        graph_path = tmp_path / "graph.json"
        self._write_minimal_graph(graph_path)
        sha = get_git_head_sha(_REPO_ROOT)
        stamp = self._make_stamp(
            tmp_path,
            graph_path,
            git_sha=sha,
            git_available=(sha != "unknown"),
        )
        # Override repo_root to match tmp_path for this test
        import dataclasses as _dc
        stamp_here = _dc.replace(stamp, repo_root=str(tmp_path.resolve()))

        errors = validate_contract_stamp(stamp_here, tmp_path, graph_path)
        # The only expected errors here are git sha related (if sha is "unknown"
        # on this machine the git check is skipped).  The graph sha should match.
        sha_errors = [e for e in errors if "graph_sha256" in e]
        assert not sha_errors, f"Graph SHA should match. Errors: {errors}"

    def test_validate_detects_graph_sha_mismatch(self, tmp_path: pathlib.Path) -> None:
        """validate_contract_stamp must report an error when graph file has changed."""
        graph_path = tmp_path / "graph.json"
        self._write_minimal_graph(graph_path)
        stamp = self._make_stamp(tmp_path, graph_path)
        import dataclasses as _dc
        stamp_bad = _dc.replace(
            stamp,
            repo_root=str(tmp_path.resolve()),
            graph_sha256="0" * 64,   # Wrong SHA
        )

        errors = validate_contract_stamp(stamp_bad, tmp_path, graph_path)
        sha_errors = [e for e in errors if "graph_sha256" in e]
        assert sha_errors, (
            "Expected a graph_sha256 mismatch error. "
            f"All errors: {errors}"
        )

    def test_validate_detects_git_sha_mismatch(self, tmp_path: pathlib.Path) -> None:
        """validate_contract_stamp must report an error when git SHA differs."""
        # Only run this check when git is actually available
        current_sha = get_git_head_sha(_REPO_ROOT)
        if current_sha == "unknown":
            pytest.skip("git not available in this environment")

        graph_path = tmp_path / "graph.json"
        self._write_minimal_graph(graph_path)

        # Build stamp with wrong SHA, but with repo_root pointing to the real
        # repo so that validate_contract_stamp can call git successfully.
        import dataclasses as _dc
        stamp = self._make_stamp(
            tmp_path,
            graph_path,
            git_sha="0000000000000000000000000000000000000000",
            git_available=True,
        )
        # Override repo_root to the real repo so the git check runs
        stamp_bad = _dc.replace(stamp, repo_root=str(_REPO_ROOT.resolve()))

        errors = validate_contract_stamp(stamp_bad, _REPO_ROOT, graph_path)
        git_errors = [e for e in errors if "git_sha" in e]
        assert git_errors, (
            "Expected a git_sha mismatch error. "
            f"All errors: {errors}"
        )

    def test_validate_detects_missing_graph_file(self, tmp_path: pathlib.Path) -> None:
        """validate_contract_stamp must report an error if graph file is absent."""
        graph_path = tmp_path / "nonexistent.json"
        # Stamp references a file that does not exist
        stamp = self._make_stamp(tmp_path, tmp_path / "graph.json")
        import dataclasses as _dc
        stamp_bad = _dc.replace(
            stamp,
            repo_root=str(tmp_path.resolve()),
            graph_sha256="a" * 64,
        )

        errors = validate_contract_stamp(stamp_bad, tmp_path, graph_path)
        missing_errors = [e for e in errors if "does not exist" in e]
        assert missing_errors, f"Expected a missing-file error. All errors: {errors}"

    # -----------------------------------------------------------------------
    # Integration: patch mode with stamp
    # -----------------------------------------------------------------------

    def test_patch_returns_3_on_invalid_stamp(self, tmp_path: pathlib.Path) -> None:
        """patch mode must return exit code 3 when the contract stamp is invalid."""
        # Build a valid graph artifact
        graph_path = tmp_path / "agent_graph.json"
        self._write_minimal_graph(graph_path)

        # Write a stamp with a wrong graph SHA
        stamp = self._make_stamp(tmp_path, graph_path)
        import dataclasses as _dc
        bad_stamp = _dc.replace(
            stamp,
            repo_root=str(tmp_path.resolve()),
            graph_sha256="0" * 64,
            git_available=False,  # skip git check
        )
        stamp_path = tmp_path / "stamp.json"
        write_contract_stamp(stamp_path, bad_stamp)

        rc = harness_main([
            "patch",
            "--root", str(tmp_path),
            "--out", str(tmp_path),
            "--graph", str(graph_path),
            "--contract-stamp-path", str(stamp_path),
            "--no-index",
        ])
        assert rc == 3, f"Expected rc=3 for invalid stamp, got {rc}"

    def test_patch_returns_0_with_valid_stamp(self, tmp_path: pathlib.Path) -> None:
        """patch mode must return 0 when the contract stamp is valid."""
        graph_path = tmp_path / "agent_graph.json"
        self._write_minimal_graph(graph_path)

        sha = get_git_head_sha(_REPO_ROOT)
        stamp = make_contract_stamp(
            repo_root=tmp_path,
            git_sha=sha,
            git_available=False,   # skip git sha check
            graph_path=graph_path,
            trace_path=tmp_path / "agent_trace.ndjson",
            graph=self._minimal_graph(),
            run_mode="graph-only",
            scope={
                "diff": False, "diff_cap": 50, "id_allowlist": True,
                "preset": None, "scope_paths": [],
            },
            budgets_config={
                "max_file_reads": 60, "max_graph_nodes_summary": 200,
                "max_grep_hits": 300, "max_steps": 40, "max_total_lines": 4000,
            },
        )
        import dataclasses as _dc
        stamp = _dc.replace(stamp, repo_root=str(tmp_path.resolve()))
        stamp_path = tmp_path / "stamp.json"
        write_contract_stamp(stamp_path, stamp)

        rc = harness_main([
            "patch",
            "--root", str(tmp_path),
            "--out", str(tmp_path),
            "--graph", str(graph_path),
            "--contract-stamp-path", str(stamp_path),
            "--no-index",
        ])
        assert rc == 0, f"Expected rc=0 with valid stamp, got {rc}"

    def test_no_contract_stamp_flag_skips_writing(self, tmp_path: pathlib.Path) -> None:
        """--no-contract-stamp must prevent stamp creation."""
        stamp_path = tmp_path / "stamp.json"
        out_dir = tmp_path / "out"
        harness_main([
            "graph-only",
            "--root", str(_SCHEMAS_DIR),
            "--out", str(out_dir),
            "--contract-stamp-path", str(stamp_path),
            "--no-contract-stamp",
            "--no-index",
            "--max-file-reads", "100",
            "--max-total-lines", "50000",
            "--max-steps", "100",
        ])
        assert not stamp_path.exists(), (
            "--no-contract-stamp must prevent stamp file creation"
        )

    def test_stamp_contains_scope_and_budgets(self, tmp_path: pathlib.Path) -> None:
        """The written stamp must include scope and budgets fields."""
        stamp_path = tmp_path / "stamp.json"
        out_dir = tmp_path / "out"
        harness_main([
            "graph-only",
            "--root", str(_SCHEMAS_DIR),
            "--out", str(out_dir),
            "--contract-stamp-path", str(stamp_path),
            "--no-index",
            "--max-file-reads", "100",
            "--max-total-lines", "50000",
            "--max-steps", "100",
        ])
        if not stamp_path.exists():
            pytest.skip("Stamp not written (possibly budget exceeded before graph)")
        raw = json.loads(stamp_path.read_text(encoding="utf-8"))
        assert "scope" in raw, "Stamp must contain a 'scope' key"
        assert "budgets" in raw, "Stamp must contain a 'budgets' key"
        scope = raw["scope"]
        assert "preset" in scope
        assert "scope_paths" in scope
        assert "diff" in scope
        assert "id_allowlist" in scope
        budgets = raw["budgets"]
        assert "max_file_reads" in budgets
        assert "max_steps" in budgets


# ===========================================================================
# PR B: Hot-Path Index
# ===========================================================================

class TestAgentIndex:
    """Tests for tools/agent/index_build.py and its integration in run.py."""

    @staticmethod
    def _run_graph_only_with_index(
        root: pathlib.Path,
        out_dir: pathlib.Path,
        index_path: pathlib.Path,
        max_file_reads: int = 200,
        max_total_lines: int = 100_000,
        max_steps: int = 200,
    ) -> int:
        return harness_main([
            "graph-only",
            "--root", str(root),
            "--out", str(out_dir),
            "--index-path", str(index_path),
            "--no-contract-stamp",
            "--max-file-reads", str(max_file_reads),
            "--max-total-lines", str(max_total_lines),
            "--max-steps", str(max_steps),
        ])

    # -----------------------------------------------------------------------
    # Integration: index is written by run.py
    # -----------------------------------------------------------------------

    def test_index_written_after_graph_only_run(self, tmp_path: pathlib.Path) -> None:
        """graph-only run must write an index file."""
        index_path = tmp_path / "index.json"
        out_dir = tmp_path / "out"
        rc = self._run_graph_only_with_index(
            _SCHEMAS_DIR, out_dir, index_path,
            max_file_reads=200, max_total_lines=200_000,
        )
        assert rc in (0, 1), f"Expected 0 or 1, got {rc}"
        assert index_path.exists(), "Index file must be written after graph-only run"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert index["version"] == 1
        assert "graph_sha256" in index
        assert "module_to_file" in index
        assert "id_to_occurrences" in index
        assert "schema_to_refs" in index
        assert "file_summary" in index

    def test_index_is_deterministic(self, tmp_path: pathlib.Path) -> None:
        """Two index builds on the same graph must produce identical JSON bytes."""
        index_path_1 = tmp_path / "index1.json"
        index_path_2 = tmp_path / "index2.json"
        out_dir = tmp_path / "out"

        self._run_graph_only_with_index(
            _SCHEMAS_DIR, out_dir, index_path_1,
            max_file_reads=200, max_total_lines=200_000,
        )
        self._run_graph_only_with_index(
            _SCHEMAS_DIR, out_dir, index_path_2,
            max_file_reads=200, max_total_lines=200_000,
        )

        if not index_path_1.exists() or not index_path_2.exists():
            pytest.skip("Index not written (budget exceeded before completion)")

        assert index_path_1.read_bytes() == index_path_2.read_bytes(), (
            "Index must be byte-identical for identical runs"
        )

    def test_module_to_file_has_entry(self, tmp_path: pathlib.Path) -> None:
        """module_to_file must contain at least one in-repo module when scanning src/."""
        index_path = tmp_path / "index.json"
        out_dir = tmp_path / "out"
        self._run_graph_only_with_index(
            _REPO_ROOT, out_dir, index_path,
            max_file_reads=300, max_total_lines=300_000,
            max_steps=300,
        )
        if not index_path.exists():
            pytest.skip("Index not written")
        index = json.loads(index_path.read_text(encoding="utf-8"))
        m2f = index.get("module_to_file", {})
        assert m2f, (
            "module_to_file must be non-empty when scanning a repo with Python modules"
        )
        # At least one resolved path must exist
        for module, path in m2f.items():
            assert isinstance(module, str) and "." in module or module  # dotted or single
            assert isinstance(path, str)

    def test_id_to_occurrences_has_canonical_id(self, tmp_path: pathlib.Path) -> None:
        """id_to_occurrences must contain at least one canonical MMO ID."""
        index_path = tmp_path / "index.json"
        out_dir = tmp_path / "out"
        self._run_graph_only_with_index(
            _ONTOLOGY_DIR, out_dir, index_path,
            max_file_reads=200, max_total_lines=200_000,
        )
        if not index_path.exists():
            pytest.skip("Index not written")
        index = json.loads(index_path.read_text(encoding="utf-8"))
        id2occ = index.get("id_to_occurrences", {})
        assert id2occ, (
            "id_to_occurrences must be non-empty when scanning ontology/"
        )
        canonical_prefixes = (
            "ACTION.", "PARAM.", "ROLE.", "GATE.", "ISSUE.", "LAYOUT.",
        )
        has_canonical = any(
            k.startswith(pfx) for k in id2occ for pfx in canonical_prefixes
        )
        assert has_canonical, (
            f"Expected a canonical ID in occurrences. "
            f"Sample keys: {sorted(id2occ.keys())[:5]}"
        )
        # Each occurrence must have path, line, evidence
        for id_key, occs in id2occ.items():
            for occ in occs:
                assert "path" in occ, f"Occurrence missing 'path': {occ}"
                assert "line" in occ, f"Occurrence missing 'line': {occ}"
                assert "evidence" in occ, f"Occurrence missing 'evidence': {occ}"
                assert isinstance(occ["line"], int) and occ["line"] >= 1

    def test_schema_to_refs_has_refs(self, tmp_path: pathlib.Path) -> None:
        """schema_to_refs must contain at least one entry when scanning schemas/."""
        index_path = tmp_path / "index.json"
        out_dir = tmp_path / "out"
        self._run_graph_only_with_index(
            _SCHEMAS_DIR, out_dir, index_path,
            max_file_reads=200, max_total_lines=200_000,
        )
        if not index_path.exists():
            pytest.skip("Index not written")
        index = json.loads(index_path.read_text(encoding="utf-8"))
        s2r = index.get("schema_to_refs", {})
        assert s2r, (
            "schema_to_refs must be non-empty when scanning schemas/"
        )
        for schema_file, refs in s2r.items():
            assert isinstance(schema_file, str)
            for r in refs:
                assert "ref" in r
                assert "evidence" in r

    def test_no_index_flag_skips_writing(self, tmp_path: pathlib.Path) -> None:
        """--no-index must prevent index file creation."""
        index_path = tmp_path / "index.json"
        harness_main([
            "graph-only",
            "--root", str(_SCHEMAS_DIR),
            "--out", str(tmp_path / "out"),
            "--index-path", str(index_path),
            "--no-index",
            "--no-contract-stamp",
            "--max-file-reads", "100",
            "--max-total-lines", "50000",
            "--max-steps", "100",
        ])
        assert not index_path.exists(), (
            "--no-index must prevent index file creation"
        )

    def test_low_budget_warns_on_occurrences(self, tmp_path: pathlib.Path) -> None:
        """When the budget is exhausted, the index warnings list must be non-empty."""
        # Build a graph first with generous budgets
        out_dir = tmp_path / "out"
        out_dir.mkdir(parents=True)
        cfg = BudgetConfig(
            max_steps=500, max_file_reads=200,
            max_total_lines=200_000, max_grep_hits=5000,
        )
        graph = build_graph(root=_ONTOLOGY_DIR, budgets=Budgets(cfg))
        save_graph(graph, out_dir / "agent_graph.json")

        # Now build index with nearly-zero budget so id_occurrences is skipped
        tiny_budgets = Budgets(BudgetConfig(
            max_steps=500, max_file_reads=1,
            max_total_lines=10, max_grep_hits=5000,
        ))
        index = build_index(
            graph=graph,
            repo_root=_REPO_ROOT,
            budgets=tiny_budgets,
            tracer=Tracer(),
            git_sha="unknown",
            git_available=False,
            graph_sha256="a" * 64,
        )
        # Either budgets exceeded OR warnings is non-empty; partial results OK
        assert tiny_budgets.is_exceeded or index.get("warnings"), (
            "Low-budget index build must either set is_exceeded or emit warnings"
        )

    # -----------------------------------------------------------------------
    # Unit: build_index from a synthetic graph
    # -----------------------------------------------------------------------

    def test_build_index_module_to_file_from_graph(
        self, tmp_path: pathlib.Path
    ) -> None:
        """build_index extracts module_to_file correctly from py_import_file edges."""
        graph: dict = {
            "edges": [
                {
                    "dst": "src/mmo/core/render_plan.py",
                    "evidence": "mmo.core.render_plan",
                    "kind": "py_import_file",
                    "source_file": "src/mmo/cli.py",
                    "src": "src/mmo/cli.py",
                },
                {
                    "dst": "b.py",
                    "evidence": "mmo.other",
                    "kind": "py_import_file",
                    "source_file": "a.py",
                    "src": "a.py",
                },
            ],
            "nodes": [],
            "warnings": [],
        }
        index = build_index(
            graph=graph,
            repo_root=tmp_path,
            budgets=_budgets(200),
            tracer=Tracer(),
            git_sha="unknown",
            git_available=False,
            graph_sha256="a" * 64,
        )
        m2f = index["module_to_file"]
        assert "mmo.core.render_plan" in m2f
        assert m2f["mmo.core.render_plan"] == "src/mmo/core/render_plan.py"
        assert "mmo.other" in m2f
        # Keys are sorted
        assert list(m2f.keys()) == sorted(m2f.keys())

    def test_build_index_schema_to_refs_from_graph(
        self, tmp_path: pathlib.Path
    ) -> None:
        """build_index extracts schema_to_refs from schema_ref edges."""
        graph: dict = {
            "edges": [
                {
                    "dst": "schemas/render_request.schema.json#layout_id",
                    "evidence": "#/$defs/layout_id",
                    "kind": "schema_ref",
                    "source_file": "schemas/render_request.schema.json",
                    "src": "schemas/render_request.schema.json",
                },
            ],
            "nodes": [],
            "warnings": [],
        }
        index = build_index(
            graph=graph,
            repo_root=tmp_path,
            budgets=_budgets(200),
            tracer=Tracer(),
            git_sha="unknown",
            git_available=False,
            graph_sha256="b" * 64,
        )
        s2r = index["schema_to_refs"]
        assert "schemas/render_request.schema.json" in s2r
        refs = s2r["schemas/render_request.schema.json"]
        assert len(refs) == 1
        assert refs[0]["ref"] == "schemas/render_request.schema.json#layout_id"

    def test_build_index_file_summary_counts_edge_types(
        self, tmp_path: pathlib.Path
    ) -> None:
        """file_summary counts py_import, id_ref, schema_ref per source file."""
        graph: dict = {
            "edges": [
                {"kind": "py_import", "src": "a.py", "dst": "os",
                 "evidence": "ast_import", "source_file": "a.py"},
                {"kind": "py_import", "src": "a.py", "dst": "sys",
                 "evidence": "ast_import", "source_file": "a.py"},
                {"kind": "id_ref", "src": "a.py", "dst": "ACTION.EQ.BELL_CUT",
                 "evidence": "x", "source_file": "a.py"},
                {"kind": "schema_ref", "src": "b.json", "dst": "c.json#foo",
                 "evidence": "#/$defs/foo", "source_file": "b.json"},
            ],
            "nodes": [],
            "warnings": [],
        }
        index = build_index(
            graph=graph,
            repo_root=tmp_path,
            budgets=_budgets(200),
            tracer=Tracer(),
            git_sha="unknown",
            git_available=False,
            graph_sha256="c" * 64,
        )
        fs = index["file_summary"]
        assert fs["a.py"]["py_imports_count"] == 2
        assert fs["a.py"]["id_refs_count"] == 1
        assert fs["a.py"]["schema_refs_count"] == 0
        assert fs["b.json"]["schema_refs_count"] == 1


# ===========================================================================
# Part 1: Seed-first diff build
# ===========================================================================

class TestSeedFirstDiffBuild:
    """Tests for tools/agent/diff_seed_first.py and build_graph_from_files."""

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _make_mini_repo(root: pathlib.Path) -> None:
        """Create a tiny synthetic repo with Python files for BFS testing.

        Structure::

            root/
              a.py       imports b (from mypkg import b)
              mypkg/
                __init__.py
                b.py     imports c (from mypkg import c)
                c.py     (leaf)
                d.py     (unreachable from a)
        """
        (root / "a.py").write_text(
            "from mypkg import b\n", encoding="utf-8"
        )
        pkg = root / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "b.py").write_text(
            "from mypkg import c\n", encoding="utf-8"
        )
        (pkg / "c.py").write_text("x = 1\n", encoding="utf-8")
        (pkg / "d.py").write_text("y = 2\n", encoding="utf-8")

    @staticmethod
    def _budgets(
        max_file_reads: int = 200,
        max_total_lines: int = 50_000,
    ) -> Budgets:
        return Budgets(
            BudgetConfig(
                max_steps=500,
                max_file_reads=max_file_reads,
                max_total_lines=max_total_lines,
                max_grep_hits=5000,
                max_graph_nodes_summary=5000,
            )
        )

    # -----------------------------------------------------------------------
    # expand_seed_first_bfs unit tests
    # -----------------------------------------------------------------------

    def test_bfs_returns_seeds_as_files(self, tmp_path: pathlib.Path) -> None:
        """Seeds that exist on disk appear in the result file list."""
        self._make_mini_repo(tmp_path)
        file_list, _ = expand_seed_first_bfs(
            seeds=["a.py"],
            repo_root=tmp_path,
            max_frontier=50,
            max_steps=1,
            budgets=self._budgets(),
            tracer=Tracer(),
        )
        posix_rels = [f.relative_to(tmp_path).as_posix() for f in file_list]
        assert "a.py" in posix_rels, f"seed a.py must be in file_list: {posix_rels}"

    def test_bfs_expands_py_imports(self, tmp_path: pathlib.Path) -> None:
        """BFS follows Python import edges to reach b.py from a.py."""
        self._make_mini_repo(tmp_path)
        file_list, _ = expand_seed_first_bfs(
            seeds=["a.py"],
            repo_root=tmp_path,
            max_frontier=50,
            max_steps=3,
            budgets=self._budgets(),
            tracer=Tracer(),
        )
        posix_rels = {f.relative_to(tmp_path).as_posix() for f in file_list}
        assert "a.py" in posix_rels
        # a.py imports mypkg → mypkg/__init__.py or mypkg/b.py should be reachable
        assert any("mypkg" in r for r in posix_rels), (
            f"Expected mypkg files to be reachable. Got: {sorted(posix_rels)}"
        )

    def test_bfs_respects_max_frontier(self, tmp_path: pathlib.Path) -> None:
        """BFS stops adding files when max_frontier is reached."""
        self._make_mini_repo(tmp_path)
        file_list, _ = expand_seed_first_bfs(
            seeds=["a.py"],
            repo_root=tmp_path,
            max_frontier=2,     # only 2 files allowed
            max_steps=10,
            budgets=self._budgets(),
            tracer=Tracer(),
        )
        assert len(file_list) <= 2, (
            f"Expected at most 2 files (max_frontier=2). Got: {len(file_list)}"
        )

    def test_bfs_respects_max_steps(self, tmp_path: pathlib.Path) -> None:
        """BFS stops expanding at max_steps depth."""
        self._make_mini_repo(tmp_path)
        # With max_steps=1: only a.py + its direct import (mypkg/__init__ or b)
        # With max_steps=0: only seeds
        file_list_0, _ = expand_seed_first_bfs(
            seeds=["a.py"],
            repo_root=tmp_path,
            max_frontier=50,
            max_steps=0,
            budgets=self._budgets(),
            tracer=Tracer(),
        )
        file_list_3, _ = expand_seed_first_bfs(
            seeds=["a.py"],
            repo_root=tmp_path,
            max_frontier=50,
            max_steps=3,
            budgets=self._budgets(),
            tracer=Tracer(),
        )
        # More steps → more or equal files
        assert len(file_list_3) >= len(file_list_0), (
            "More BFS steps should include at least as many files"
        )

    def test_bfs_deterministic(self, tmp_path: pathlib.Path) -> None:
        """Two identical calls produce identical file_list and parent_map."""
        self._make_mini_repo(tmp_path)
        fl1, pm1 = expand_seed_first_bfs(
            seeds=["a.py"],
            repo_root=tmp_path,
            max_frontier=50,
            max_steps=3,
            budgets=self._budgets(),
            tracer=Tracer(),
        )
        fl2, pm2 = expand_seed_first_bfs(
            seeds=["a.py"],
            repo_root=tmp_path,
            max_frontier=50,
            max_steps=3,
            budgets=self._budgets(),
            tracer=Tracer(),
        )
        rels1 = sorted(f.relative_to(tmp_path).as_posix() for f in fl1)
        rels2 = sorted(f.relative_to(tmp_path).as_posix() for f in fl2)
        assert rels1 == rels2, "File list must be deterministic"
        assert pm1 == pm2, "Parent map must be deterministic"

    def test_bfs_parent_map_populated(self, tmp_path: pathlib.Path) -> None:
        """Non-seed files in the result have a parent_map entry."""
        self._make_mini_repo(tmp_path)
        _, parent_map = expand_seed_first_bfs(
            seeds=["a.py"],
            repo_root=tmp_path,
            max_frontier=50,
            max_steps=3,
            budgets=self._budgets(),
            tracer=Tracer(),
        )
        # Seeds should NOT be in parent_map (they are roots)
        assert "a.py" not in parent_map, "Seeds must not have parent_map entries"
        # Non-seed files should have complete entries
        for child, info in parent_map.items():
            assert "parent" in info, f"Missing 'parent' in parent_map[{child}]"
            assert "edge_kind" in info, f"Missing 'edge_kind' in parent_map[{child}]"
            assert "evidence" in info, f"Missing 'evidence' in parent_map[{child}]"

    def test_bfs_missing_seed_skipped(self, tmp_path: pathlib.Path) -> None:
        """Seeds that do not exist on disk are silently skipped."""
        self._make_mini_repo(tmp_path)
        file_list, _ = expand_seed_first_bfs(
            seeds=["does_not_exist.py", "a.py"],
            repo_root=tmp_path,
            max_frontier=50,
            max_steps=1,
            budgets=self._budgets(),
            tracer=Tracer(),
        )
        posix_rels = {f.relative_to(tmp_path).as_posix() for f in file_list}
        assert "a.py" in posix_rels
        assert "does_not_exist.py" not in posix_rels

    # -----------------------------------------------------------------------
    # build_graph_from_files unit/integration tests
    # -----------------------------------------------------------------------

    def test_build_graph_from_files_basic(self, tmp_path: pathlib.Path) -> None:
        """build_graph_from_files returns nodes/edges/warnings dict."""
        self._make_mini_repo(tmp_path)
        files = [tmp_path / "a.py", tmp_path / "mypkg" / "b.py"]
        graph = build_graph_from_files(
            files=files,
            root=tmp_path,
            repo_root=tmp_path,
            budgets=self._budgets(),
            tracer=Tracer(),
        )
        assert "nodes" in graph
        assert "edges" in graph
        assert "warnings" in graph
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "a.py" in node_ids, f"Expected a.py in nodes. Got: {sorted(node_ids)}"

    def test_build_graph_from_files_py_import_edge(
        self, tmp_path: pathlib.Path
    ) -> None:
        """build_graph_from_files emits py_import_file edges for resolvable imports."""
        self._make_mini_repo(tmp_path)
        files = [
            tmp_path / "a.py",
            tmp_path / "mypkg" / "__init__.py",
            tmp_path / "mypkg" / "b.py",
            tmp_path / "mypkg" / "c.py",
        ]
        graph = build_graph_from_files(
            files=files,
            root=tmp_path,
            repo_root=tmp_path,
            budgets=self._budgets(),
            tracer=Tracer(),
        )
        pif_edges = [e for e in graph["edges"] if e["kind"] == "py_import_file"]
        assert pif_edges, (
            "Expected at least one py_import_file edge. "
            f"Edge kinds: {[e['kind'] for e in graph['edges']]}"
        )
        srcs = {e["src"] for e in pif_edges}
        assert "a.py" in srcs, f"Expected a.py as src. Srcs: {srcs}"

    def test_build_graph_from_files_deterministic(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Two calls with identical file list produce identical JSON."""
        self._make_mini_repo(tmp_path)
        files = sorted(tmp_path.rglob("*.py"))
        cfg = BudgetConfig(
            max_steps=500,
            max_file_reads=200,
            max_total_lines=50_000,
        )
        g1 = build_graph_from_files(
            files=files, root=tmp_path, repo_root=tmp_path, budgets=Budgets(cfg)
        )
        g2 = build_graph_from_files(
            files=files, root=tmp_path, repo_root=tmp_path, budgets=Budgets(cfg)
        )
        j1 = json.dumps({"edges": g1["edges"], "nodes": g1["nodes"]}, sort_keys=True)
        j2 = json.dumps({"edges": g2["edges"], "nodes": g2["nodes"]}, sort_keys=True)
        assert j1 == j2, "build_graph_from_files must be deterministic"

    def test_diff_seed_first_flag_accepted_by_cli(
        self, tmp_path: pathlib.Path
    ) -> None:
        """--diff-seed-first flag is accepted by the CLI without error.

        This test does NOT require git; it verifies that the flag is parsed and
        that when no seeds are found the harness gracefully falls back to the
        normal build path.
        """
        # Create a minimal repo structure so graph-only can complete.
        (tmp_path / "dummy.py").write_text("import os\n", encoding="utf-8")
        out_dir = tmp_path / "out"
        # --diff-seed-first without --diff should be a no-op (flag only matters
        # when combined with --diff).  Run without --diff to test flag parsing.
        rc = harness_main([
            "graph-only",
            "--root", str(tmp_path),
            "--out", str(out_dir),
            "--diff-seed-first",
            "--diff-max-frontier", "50",
            "--diff-max-steps", "3",
            "--no-contract-stamp",
            "--no-index",
            "--max-file-reads", "50",
            "--max-total-lines", "10000",
            "--max-steps", "50",
        ])
        assert rc in (0, 1), f"Expected 0 or 1, got {rc}"


# ===========================================================================
# Part 2: Explain mode
# ===========================================================================

class TestExplainMode:
    """Tests for tools/agent/explain.py and the explain/explain-scope CLI modes."""

    # -----------------------------------------------------------------------
    # Minimal graph fixtures
    # -----------------------------------------------------------------------

    @staticmethod
    def _linear_graph() -> dict:
        """a→b→c linear chain."""
        return {
            "edges": [
                {
                    "dst": "b.py",
                    "evidence": "mypkg.b",
                    "kind": "py_import_file",
                    "source_file": "a.py",
                    "src": "a.py",
                },
                {
                    "dst": "c.py",
                    "evidence": "mypkg.c",
                    "kind": "py_import_file",
                    "source_file": "b.py",
                    "src": "b.py",
                },
            ],
            "nodes": [
                {"id": "a.py", "kind": "file"},
                {"id": "b.py", "kind": "file"},
                {"id": "c.py", "kind": "file"},
            ],
            "warnings": [],
        }

    @staticmethod
    def _diamond_graph() -> dict:
        """Diamond: a→b, a→c, b→d, c→d (two shortest paths to d)."""
        return {
            "edges": [
                {
                    "dst": "b.py",
                    "evidence": "mypkg.b",
                    "kind": "py_import_file",
                    "source_file": "a.py",
                    "src": "a.py",
                },
                {
                    "dst": "c.py",
                    "evidence": "mypkg.c",
                    "kind": "py_import_file",
                    "source_file": "a.py",
                    "src": "a.py",
                },
                {
                    "dst": "d.py",
                    "evidence": "mypkg.d",
                    "kind": "py_import_file",
                    "source_file": "b.py",
                    "src": "b.py",
                },
                {
                    "dst": "d.py",
                    "evidence": "mypkg.d",
                    "kind": "schema_ref",
                    "source_file": "c.py",
                    "src": "c.py",
                },
            ],
            "nodes": [
                {"id": "a.py", "kind": "file"},
                {"id": "b.py", "kind": "file"},
                {"id": "c.py", "kind": "file"},
                {"id": "d.py", "kind": "file"},
            ],
            "warnings": [],
        }

    # -----------------------------------------------------------------------
    # find_shortest_path unit tests
    # -----------------------------------------------------------------------

    def test_shortest_path_linear(self) -> None:
        """find_shortest_path returns 2-hop path in a→b→c chain."""
        graph = self._linear_graph()
        path = find_shortest_path(graph, "a.py", "c.py", directed=True)
        assert path is not None, "Expected a path"
        assert len(path) == 2, f"Expected 2-hop path, got {len(path)}"
        assert path[0]["src"] == "a.py" and path[0]["dst"] == "b.py"
        assert path[1]["src"] == "b.py" and path[1]["dst"] == "c.py"

    def test_shortest_path_no_path_returns_none(self) -> None:
        """find_shortest_path returns None when target is unreachable."""
        graph = self._linear_graph()
        result = find_shortest_path(graph, "c.py", "a.py", directed=True)
        assert result is None, "Expected None for unreachable node in directed graph"

    def test_shortest_path_same_node_returns_empty(self) -> None:
        """find_shortest_path returns [] when from == to."""
        graph = self._linear_graph()
        result = find_shortest_path(graph, "a.py", "a.py")
        assert result == [], f"Expected [], got {result}"

    def test_shortest_path_tie_breaking_deterministic(self) -> None:
        """Tie-breaking is deterministic: lex-min (kind, src, dst, evidence) wins."""
        graph = self._diamond_graph()
        # Both paths a→b→d and a→c→d have length 2.
        # Tie-break: compare edge sequences lex.
        # Path via b: [("py_import_file","a.py","b.py","mypkg.b"),
        #               ("py_import_file","b.py","d.py","mypkg.d")]
        # Path via c: [("py_import_file","a.py","c.py","mypkg.c"),
        #               ("schema_ref","c.py","d.py","mypkg.d")]
        # Lex comparison at hop 0:
        #   ("py_import_file","a.py","b.py","mypkg.b") vs
        #   ("py_import_file","a.py","c.py","mypkg.c")
        # "b.py" < "c.py" → via-b path wins.
        path1 = find_shortest_path(graph, "a.py", "d.py", directed=True)
        path2 = find_shortest_path(graph, "a.py", "d.py", directed=True)
        assert path1 == path2, "Tie-breaking must be deterministic"
        assert path1 is not None
        assert len(path1) == 2
        assert path1[0]["dst"] == "b.py", (
            f"Expected path via b.py (lex-min), got via {path1[0]['dst']}"
        )

    def test_shortest_path_undirected(self) -> None:
        """Undirected mode can traverse edges in reverse direction."""
        graph = self._linear_graph()
        # In directed mode c→a is unreachable; in undirected it is reachable.
        directed_result = find_shortest_path(graph, "c.py", "a.py", directed=True)
        undirected_result = find_shortest_path(graph, "c.py", "a.py", directed=False)
        assert directed_result is None
        assert undirected_result is not None
        assert len(undirected_result) == 2

    # -----------------------------------------------------------------------
    # run_explain unit tests (captures stdout)
    # -----------------------------------------------------------------------

    def test_run_explain_basic(self, capsys: pytest.CaptureFixture) -> None:
        """run_explain prints target, from, hops for a known linear graph."""
        graph = self._linear_graph()
        graph["meta"] = {"seeds": ["a.py"]}
        rc = run_explain(
            graph=graph,
            target="c.py",
            from_seed=None,
            max_hops=10,
            directed=True,
        )
        out = capsys.readouterr().out
        assert rc == 0, f"Expected rc=0, got {rc}"
        assert "target" in out
        assert "c.py" in out
        assert "hops" in out

    def test_run_explain_target_not_in_graph(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """run_explain returns 1 when target is not in graph."""
        graph = self._linear_graph()
        rc = run_explain(
            graph=graph,
            target="nonexistent.py",
            from_seed=None,
            max_hops=10,
            directed=True,
        )
        assert rc == 1

    def test_run_explain_from_seed(self, capsys: pytest.CaptureFixture) -> None:
        """run_explain uses explicit --from-seed when provided."""
        graph = self._linear_graph()
        rc = run_explain(
            graph=graph,
            target="c.py",
            from_seed="a.py",
            max_hops=10,
            directed=True,
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "a.py" in out  # from line
        assert "c.py" in out  # target line

    def test_run_explain_no_path(self, capsys: pytest.CaptureFixture) -> None:
        """run_explain returns 1 and prints error when no path exists."""
        graph = self._linear_graph()
        rc = run_explain(
            graph=graph,
            target="a.py",
            from_seed="c.py",
            max_hops=10,
            directed=True,
        )
        assert rc == 1

    # -----------------------------------------------------------------------
    # run_explain_scope unit tests
    # -----------------------------------------------------------------------

    def test_run_explain_scope_no_meta(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """run_explain_scope prints info message when graph has no meta."""
        graph: dict = {
            "edges": [],
            "nodes": [{"id": "a.py", "kind": "file"}],
            "warnings": [],
        }
        rc = run_explain_scope(graph=graph)
        out = capsys.readouterr().out
        assert rc == 0
        assert "INFO" in out

    def test_run_explain_scope_with_parent_map(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """run_explain_scope prints seeds and non-seed first-hop justifications."""
        graph: dict = {
            "edges": [],
            "nodes": [
                {"id": "a.py", "kind": "file"},
                {"id": "b.py", "kind": "file"},
            ],
            "warnings": [],
            "meta": {
                "seed_first": True,
                "seeds": ["a.py"],
                "parent_map": {
                    "b.py": {
                        "edge_kind": "py_import_file",
                        "evidence": "mypkg.b",
                        "parent": "a.py",
                    }
                },
            },
        }
        rc = run_explain_scope(graph=graph)
        out = capsys.readouterr().out
        assert rc == 0
        assert "a.py" in out  # seed printed
        assert "b.py" in out  # non-seed printed
        assert "py_import_file" in out  # edge kind shown

    def test_run_explain_scope_deterministic_ordering(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """run_explain_scope output is the same on two calls."""
        graph: dict = {
            "edges": [],
            "nodes": [],
            "warnings": [],
            "meta": {
                "seed_first": True,
                "seeds": ["z.py", "a.py"],  # deliberately unsorted
                "parent_map": {
                    "c.py": {"edge_kind": "py_import_file", "evidence": "x", "parent": "a.py"},
                    "b.py": {"edge_kind": "py_import_file", "evidence": "y", "parent": "a.py"},
                },
            },
        }
        run_explain_scope(graph=graph)
        out1 = capsys.readouterr().out
        run_explain_scope(graph=graph)
        out2 = capsys.readouterr().out
        assert out1 == out2, "explain-scope output must be deterministic"

    # -----------------------------------------------------------------------
    # CLI integration tests for explain and explain-scope
    # -----------------------------------------------------------------------

    def test_cli_explain_mode(self, tmp_path: pathlib.Path) -> None:
        """explain mode loads graph and returns 0 for a reachable target."""
        graph_path = tmp_path / "agent_graph.json"
        graph = self._linear_graph()
        graph["meta"] = {"seeds": ["a.py"]}
        save_graph(graph, graph_path)

        out_dir = tmp_path / "out"
        rc = harness_main([
            "explain",
            "--root", str(tmp_path),
            "--out", str(out_dir),
            "--graph", str(graph_path),
            "--target", "c.py",
            "--no-contract-stamp",
            "--no-index",
        ])
        assert rc == 0, f"Expected rc=0 for reachable target, got {rc}"

    def test_cli_explain_target_missing_returns_1(
        self, tmp_path: pathlib.Path
    ) -> None:
        """explain mode returns 1 when --target is absent."""
        graph_path = tmp_path / "agent_graph.json"
        save_graph(self._linear_graph(), graph_path)
        out_dir = tmp_path / "out"
        rc = harness_main([
            "explain",
            "--root", str(tmp_path),
            "--out", str(out_dir),
            "--graph", str(graph_path),
            # no --target
            "--no-contract-stamp",
            "--no-index",
        ])
        assert rc == 1, f"Expected rc=1 when --target absent, got {rc}"

    def test_cli_explain_scope_mode(self, tmp_path: pathlib.Path) -> None:
        """explain-scope mode loads graph and returns 0."""
        graph_path = tmp_path / "agent_graph.json"
        graph = self._linear_graph()
        graph["meta"] = {
            "seed_first": True,
            "seeds": ["a.py"],
            "parent_map": {
                "b.py": {"edge_kind": "py_import_file", "evidence": "mypkg.b", "parent": "a.py"}
            },
        }
        save_graph(graph, graph_path)
        out_dir = tmp_path / "out"
        rc = harness_main([
            "explain-scope",
            "--root", str(tmp_path),
            "--out", str(out_dir),
            "--graph", str(graph_path),
            "--no-contract-stamp",
            "--no-index",
        ])
        assert rc == 0, f"Expected rc=0, got {rc}"

    def test_cli_explain_no_graph_returns_1(self, tmp_path: pathlib.Path) -> None:
        """explain mode returns 1 when no graph artifact exists."""
        out_dir = tmp_path / "out"
        rc = harness_main([
            "explain",
            "--root", str(tmp_path),
            "--out", str(out_dir),
            "--target", "a.py",
            "--no-contract-stamp",
            "--no-index",
        ])
        assert rc == 1, f"Expected rc=1 when graph missing, got {rc}"


# ===========================================================================
# Budget profiles and --index-skip-path (PR C)
# ===========================================================================

class TestProfileAndIndexSkip:
    """Tests for --profile code and --index-skip-path features."""

    # -----------------------------------------------------------------------
    # Unit: _apply_profile
    # -----------------------------------------------------------------------

    def test_profile_code_raises_budget_defaults(self) -> None:
        """--profile code raises max_file_reads and max_total_lines from defaults."""
        from tools.agent.run import _apply_profile, _BUDGET_DEFAULTS, _PROFILE_CODE_BUDGETS
        import argparse

        args = argparse.Namespace(
            profile="code",
            max_file_reads=_BUDGET_DEFAULTS["max_file_reads"],
            max_total_lines=_BUDGET_DEFAULTS["max_total_lines"],
            max_steps=_BUDGET_DEFAULTS["max_steps"],
            max_grep_hits=_BUDGET_DEFAULTS["max_grep_hits"],
            max_graph_nodes_summary=_BUDGET_DEFAULTS["max_graph_nodes_summary"],
            index_skip_path=[],
        )
        _apply_profile(args)

        assert args.max_file_reads == _PROFILE_CODE_BUDGETS["max_file_reads"]
        assert args.max_total_lines == _PROFILE_CODE_BUDGETS["max_total_lines"]
        # Unchanged budgets stay at default
        assert args.max_steps == _BUDGET_DEFAULTS["max_steps"]

    def test_profile_code_does_not_override_explicit_flags(self) -> None:
        """Explicit CLI budget values must not be overridden by --profile code."""
        from tools.agent.run import _apply_profile, _BUDGET_DEFAULTS

        import argparse
        args = argparse.Namespace(
            profile="code",
            max_file_reads=120,          # explicit — must not change
            max_total_lines=_BUDGET_DEFAULTS["max_total_lines"],
            max_steps=_BUDGET_DEFAULTS["max_steps"],
            max_grep_hits=_BUDGET_DEFAULTS["max_grep_hits"],
            max_graph_nodes_summary=_BUDGET_DEFAULTS["max_graph_nodes_summary"],
            index_skip_path=[],
        )
        _apply_profile(args)

        assert args.max_file_reads == 120, (
            "Explicit --max-file-reads must not be overridden by profile"
        )

    def test_profile_code_sets_default_skip_paths(self) -> None:
        """--profile code sets index_skip_path to ['docs'] when not already set."""
        from tools.agent.run import _apply_profile, _BUDGET_DEFAULTS, _PROFILE_CODE_SKIP_PATHS

        import argparse
        args = argparse.Namespace(
            profile="code",
            max_file_reads=_BUDGET_DEFAULTS["max_file_reads"],
            max_total_lines=_BUDGET_DEFAULTS["max_total_lines"],
            max_steps=_BUDGET_DEFAULTS["max_steps"],
            max_grep_hits=_BUDGET_DEFAULTS["max_grep_hits"],
            max_graph_nodes_summary=_BUDGET_DEFAULTS["max_graph_nodes_summary"],
            index_skip_path=[],
        )
        _apply_profile(args)

        assert args.index_skip_path == _PROFILE_CODE_SKIP_PATHS

    def test_profile_code_does_not_override_explicit_skip_paths(self) -> None:
        """Explicit --index-skip-path values are not overridden by --profile code."""
        from tools.agent.run import _apply_profile, _BUDGET_DEFAULTS

        import argparse
        args = argparse.Namespace(
            profile="code",
            max_file_reads=_BUDGET_DEFAULTS["max_file_reads"],
            max_total_lines=_BUDGET_DEFAULTS["max_total_lines"],
            max_steps=_BUDGET_DEFAULTS["max_steps"],
            max_grep_hits=_BUDGET_DEFAULTS["max_grep_hits"],
            max_graph_nodes_summary=_BUDGET_DEFAULTS["max_graph_nodes_summary"],
            index_skip_path=["tools"],  # explicit — must not change
        )
        _apply_profile(args)

        assert args.index_skip_path == ["tools"], (
            "Explicit --index-skip-path must not be overridden by profile"
        )

    def test_no_profile_leaves_defaults_unchanged(self) -> None:
        """With profile=None, _apply_profile must not mutate anything."""
        from tools.agent.run import _apply_profile, _BUDGET_DEFAULTS

        import argparse
        args = argparse.Namespace(
            profile=None,
            max_file_reads=_BUDGET_DEFAULTS["max_file_reads"],
            max_total_lines=_BUDGET_DEFAULTS["max_total_lines"],
            max_steps=_BUDGET_DEFAULTS["max_steps"],
            max_grep_hits=_BUDGET_DEFAULTS["max_grep_hits"],
            max_graph_nodes_summary=_BUDGET_DEFAULTS["max_graph_nodes_summary"],
            index_skip_path=[],
        )
        _apply_profile(args)

        assert args.max_file_reads == _BUDGET_DEFAULTS["max_file_reads"]
        assert args.max_total_lines == _BUDGET_DEFAULTS["max_total_lines"]
        assert args.index_skip_path == []

    # -----------------------------------------------------------------------
    # Unit: _is_path_skipped
    # -----------------------------------------------------------------------

    def test_is_path_skipped_exact_match(self) -> None:
        """Exact path match returns True."""
        from tools.agent.index_build import _is_path_skipped
        assert _is_path_skipped("docs", frozenset({"docs"}))

    def test_is_path_skipped_prefix_match(self) -> None:
        """Path under a skipped prefix returns True."""
        from tools.agent.index_build import _is_path_skipped
        assert _is_path_skipped("docs/agent_repl_harness.md", frozenset({"docs"}))

    def test_is_path_skipped_partial_prefix_no_match(self) -> None:
        """Partial directory name must NOT match (e.g. 'doc' should not match 'docs/')."""
        from tools.agent.index_build import _is_path_skipped
        assert not _is_path_skipped("docs/foo.md", frozenset({"doc"}))

    def test_is_path_skipped_unrelated_path(self) -> None:
        """Unrelated path returns False."""
        from tools.agent.index_build import _is_path_skipped
        assert not _is_path_skipped("src/mmo/cli.py", frozenset({"docs"}))

    def test_is_path_skipped_empty_skip_set(self) -> None:
        """Empty skip set: nothing is skipped."""
        from tools.agent.index_build import _is_path_skipped
        assert not _is_path_skipped("docs/foo.md", frozenset())

    # -----------------------------------------------------------------------
    # Unit: _build_id_occurrences with skip_paths
    # -----------------------------------------------------------------------

    def test_build_id_occurrences_skips_docs_files(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Files under a skipped prefix are excluded from id_to_occurrences."""
        from tools.agent.index_build import _build_id_occurrences

        # Create a real file so the scanner could read it if not skipped
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        doc_file = docs_dir / "guide.md"
        doc_file.write_text("ACTION.EQ.BELL_CUT is mentioned here.\n", encoding="utf-8")

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        src_file = src_dir / "module.py"
        src_file.write_text('action = "ACTION.EQ.BELL_CUT"\n', encoding="utf-8")

        graph: dict = {
            "edges": [
                {
                    "kind": "id_ref",
                    "src": "docs/guide.md",
                    "dst": "ACTION.EQ.BELL_CUT",
                    "evidence": "docs/guide.md",
                    "source_file": "docs/guide.md",
                },
                {
                    "kind": "id_ref",
                    "src": "src/module.py",
                    "dst": "ACTION.EQ.BELL_CUT",
                    "evidence": "src/module.py",
                    "source_file": "src/module.py",
                },
            ],
            "nodes": [],
            "warnings": [],
        }

        result, warnings = _build_id_occurrences(
            graph=graph,
            root=tmp_path,
            budgets=_budgets(),
            tracer=Tracer(),
            skip_paths=frozenset({"docs"}),
        )

        # All occurrences of ACTION.EQ.BELL_CUT must come from src/, not docs/
        for id_key, occs in result.items():
            for occ in occs:
                assert not occ["path"].startswith("docs/"), (
                    f"docs/ file must be skipped. Found occurrence: {occ}"
                )

    def test_build_id_occurrences_no_skip_includes_all(
        self, tmp_path: pathlib.Path
    ) -> None:
        """With empty skip_paths all files are scanned."""
        from tools.agent.index_build import _build_id_occurrences

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        doc_file = docs_dir / "guide.md"
        doc_file.write_text("ACTION.EQ.BELL_CUT mentioned.\n", encoding="utf-8")

        graph: dict = {
            "edges": [
                {
                    "kind": "id_ref",
                    "src": "docs/guide.md",
                    "dst": "ACTION.EQ.BELL_CUT",
                    "evidence": "docs/guide.md",
                    "source_file": "docs/guide.md",
                },
            ],
            "nodes": [],
            "warnings": [],
        }

        result, _ = _build_id_occurrences(
            graph=graph,
            root=tmp_path,
            budgets=_budgets(),
            tracer=Tracer(),
            skip_paths=frozenset(),
        )

        # docs/guide.md must appear in occurrences when skip_paths is empty
        all_paths = {occ["path"] for occs in result.values() for occ in occs}
        assert any(p.startswith("docs/") for p in all_paths), (
            f"Expected docs/ occurrence when skip_paths is empty. Paths: {all_paths}"
        )

    # -----------------------------------------------------------------------
    # Integration: CLI flags --profile and --index-skip-path
    # -----------------------------------------------------------------------

    def test_cli_profile_code_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """--profile code is accepted by the CLI and completes without error."""
        rc = harness_main([
            "graph-only",
            "--root", str(_SCHEMAS_DIR),
            "--out", str(tmp_path / "out"),
            "--profile", "code",
            "--no-contract-stamp",
            "--no-index",
            "--max-steps", "100",
        ])
        assert rc in (0, 1), f"Expected 0 or 1, got {rc}"

    def test_cli_index_skip_path_flag_accepted(self, tmp_path: pathlib.Path) -> None:
        """--index-skip-path flag is accepted and excludes the path from occurrences."""
        index_path = tmp_path / "index.json"
        out_dir = tmp_path / "out"
        rc = harness_main([
            "graph-only",
            "--root", str(_ONTOLOGY_DIR),
            "--out", str(out_dir),
            "--index-path", str(index_path),
            "--index-skip-path", "docs",
            "--no-contract-stamp",
            "--max-file-reads", "200",
            "--max-total-lines", "200000",
            "--max-steps", "200",
        ])
        assert rc in (0, 1), f"Expected 0 or 1, got {rc}"
        # If index was written, verify no docs/ paths in id_to_occurrences
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            for id_key, occs in index.get("id_to_occurrences", {}).items():
                for occ in occs:
                    assert not occ["path"].startswith("docs/"), (
                        f"docs/ path found in id_to_occurrences despite --index-skip-path docs: "
                        f"{occ}"
                    )

    def test_cli_profile_code_raises_budget_vs_default(
        self, tmp_path: pathlib.Path
    ) -> None:
        """--profile code produces a config with higher budget than the default."""
        from tools.agent.run import _parse_args, _apply_profile
        from tools.agent.budgets import BudgetConfig

        # Simulate what main() does
        args_default = _parse_args(["graph-only", "--root", "."])
        args_code = _parse_args(["graph-only", "--root", ".", "--profile", "code"])
        _apply_profile(args_code)

        assert args_code.max_file_reads > args_default.max_file_reads
        assert args_code.max_total_lines > args_default.max_total_lines
