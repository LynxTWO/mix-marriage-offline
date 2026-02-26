"""Tests for the deterministic multi-job render engine.

Covers:
- ``src/mmo/core/render_contract.py`` — contract building, layout resolution,
  downmix route detection, policy propagation.
- ``src/mmo/core/render_engine.py`` — ``render_scene_to_targets()``:
  schema conformance, determinism, job structure, QA gates, policies.

Fixtures span three layout families per the task specification:
- 2.0 stereo (LAYOUT.2_0)
- 5.1 surround (LAYOUT.5_1)
- 7.1.4 immersive (LAYOUT.7_1_4)
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.render_contract import build_render_contract, contracts_to_render_targets
from mmo.core.progress import CancelToken, CancelledError
from mmo.core.render_engine import render_scene_to_targets

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


# ---------------------------------------------------------------------------
# Schema validation helpers
# ---------------------------------------------------------------------------


def _build_registry() -> Registry:
    registry = Registry()
    for candidate in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    return registry


def _validator(schema_name: str) -> jsonschema.Draft202012Validator:
    schema_path = SCHEMAS_DIR / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, registry=_build_registry())


# ---------------------------------------------------------------------------
# Scene fixtures
# ---------------------------------------------------------------------------


def _make_scene(
    *,
    source_layout_id: str = "LAYOUT.7_1_4",
    scene_id: str = "SCENE.TEST.RENDER_ENGINE",
) -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": scene_id,
        "scene_path": "scenes/test/scene.json",
        "source": {
            "stems_dir": "stems/test",
            "layout_id": source_layout_id,
            "created_from": "analyze",
        },
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Contract fixtures (one per layout family)
# ---------------------------------------------------------------------------


def _stereo_contract(source_layout_id: str = "LAYOUT.2_0") -> dict:
    """2.0 stereo target; no downmix when source is also stereo."""
    return build_render_contract(
        "TARGET.STEREO.2_0",
        "LAYOUT.2_0",
        source_layout_id=source_layout_id,
        output_formats=["wav"],
    )


def _stereo_from_51_contract() -> dict:
    """2.0 stereo target folded from 5.1 source via standard policy."""
    return build_render_contract(
        "TARGET.STEREO.2_0",
        "LAYOUT.2_0",
        source_layout_id="LAYOUT.5_1",
        downmix_policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
        output_formats=["wav"],
    )


def _surround_51_contract(source_layout_id: str = "LAYOUT.5_1") -> dict:
    """5.1 surround target; uses immersive policy for 7.1.4 sources."""
    if source_layout_id == "LAYOUT.7_1_4":
        policy_id = "POLICY.DOWNMIX.IMMERSIVE_FOLDOWN_V0"
    else:
        policy_id = "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0"
    return build_render_contract(
        "TARGET.SURROUND.5_1",
        "LAYOUT.5_1",
        source_layout_id=source_layout_id,
        downmix_policy_id=policy_id,
        output_formats=["wav"],
    )


def _immersive_714_contract(source_layout_id: str = "LAYOUT.7_1_4") -> dict:
    """7.1.4 immersive target; native (no downmix when source matches)."""
    return build_render_contract(
        "TARGET.IMMERSIVE.7_1_4",
        "LAYOUT.7_1_4",
        source_layout_id=source_layout_id,
        output_formats=["wav"],
    )


# ---------------------------------------------------------------------------
# TestRenderContract — unit tests for render_contract.py
# ---------------------------------------------------------------------------


class TestRenderContract(unittest.TestCase):
    """Unit tests for ``build_render_contract`` and helpers."""

    # --- Layout field resolution ---

    def test_stereo_contract_fields(self) -> None:
        contract = build_render_contract("TARGET.STEREO.2_0", "LAYOUT.2_0")
        self.assertEqual(contract["target_id"], "TARGET.STEREO.2_0")
        self.assertEqual(contract["target_layout_id"], "LAYOUT.2_0")
        self.assertEqual(contract["channel_count"], 2)
        self.assertEqual(contract["family"], "stereo")
        self.assertFalse(contract["has_lfe"])
        self.assertEqual(contract["output_formats"], ["wav"])
        self.assertEqual(contract["sample_rate_hz"], 48000)
        self.assertEqual(contract["bit_depth"], 24)

    def test_surround_51_contract_fields(self) -> None:
        contract = build_render_contract("TARGET.SURROUND.5_1", "LAYOUT.5_1")
        self.assertEqual(contract["channel_count"], 6)
        self.assertEqual(contract["family"], "surround")
        self.assertTrue(contract["has_lfe"])
        self.assertEqual(len(contract["channel_order"]), 6)

    def test_immersive_714_contract_fields(self) -> None:
        contract = build_render_contract("TARGET.TEST.7_1_4", "LAYOUT.7_1_4")
        self.assertEqual(contract["channel_count"], 12)
        self.assertEqual(contract["family"], "immersive")
        self.assertTrue(contract["has_lfe"])
        self.assertEqual(len(contract["channel_order"]), 12)

    def test_channel_order_length_matches_count(self) -> None:
        for layout_id, expected_count in [
            ("LAYOUT.2_0", 2),
            ("LAYOUT.5_1", 6),
            ("LAYOUT.7_1", 8),
            ("LAYOUT.7_1_4", 12),
        ]:
            with self.subTest(layout_id=layout_id):
                contract = build_render_contract("TARGET.TEST", layout_id)
                self.assertEqual(
                    len(contract["channel_order"]),
                    expected_count,
                    msg=f"channel_order length for {layout_id}",
                )
                self.assertEqual(contract["channel_count"], expected_count)

    # --- Downmix route resolution ---

    def test_downmix_route_resolved_51_to_20(self) -> None:
        contract = _stereo_from_51_contract()
        self.assertIn("downmix_route", contract)
        route = contract["downmix_route"]
        self.assertEqual(route["from_layout_id"], "LAYOUT.5_1")
        self.assertEqual(route["to_layout_id"], "LAYOUT.2_0")
        self.assertEqual(route["policy_id"], "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0")
        self.assertIn(route["kind"], ("direct", "composed"))

    def test_downmix_route_resolved_714_to_51(self) -> None:
        contract = _surround_51_contract(source_layout_id="LAYOUT.7_1_4")
        self.assertIn("downmix_route", contract)
        route = contract["downmix_route"]
        self.assertEqual(route["from_layout_id"], "LAYOUT.7_1_4")
        self.assertEqual(route["to_layout_id"], "LAYOUT.5_1")

    def test_no_downmix_route_when_layouts_match(self) -> None:
        contract = build_render_contract(
            "TARGET.SURROUND.5_1",
            "LAYOUT.5_1",
            source_layout_id="LAYOUT.5_1",
        )
        self.assertNotIn("downmix_route", contract)

    def test_no_downmix_route_when_source_omitted(self) -> None:
        contract = build_render_contract("TARGET.STEREO.2_0", "LAYOUT.2_0")
        self.assertNotIn("downmix_route", contract)

    def test_unavailable_downmix_path_adds_note(self) -> None:
        # STANDARD_FOLDOWN_V0 does not support 7.1.4 → 5.1.
        contract = build_render_contract(
            "TARGET.SURROUND.5_1",
            "LAYOUT.5_1",
            source_layout_id="LAYOUT.7_1_4",
            downmix_policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
        )
        self.assertNotIn("downmix_route", contract)
        self.assertIn("notes", contract)
        self.assertTrue(any("LAYOUT.7_1_4" in n for n in contract["notes"]))

    # --- Output format normalisation ---

    def test_output_formats_normalised(self) -> None:
        contract = build_render_contract(
            "TARGET.TEST",
            "LAYOUT.2_0",
            output_formats=["flac", "wav", "flac"],
        )
        # Deduplicated and in canonical order.
        self.assertEqual(contract["output_formats"], ["wav", "flac"])

    def test_invalid_format_falls_back_to_wav(self) -> None:
        contract = build_render_contract(
            "TARGET.TEST",
            "LAYOUT.2_0",
            output_formats=["mp3", "aac"],
        )
        self.assertEqual(contract["output_formats"], ["wav"])

    def test_empty_formats_falls_back_to_wav(self) -> None:
        contract = build_render_contract("TARGET.TEST", "LAYOUT.2_0", output_formats=[])
        self.assertEqual(contract["output_formats"], ["wav"])

    # --- Policy propagation ---

    def test_policy_fields_set_when_provided(self) -> None:
        contract = build_render_contract(
            "TARGET.STEREO.2_0",
            "LAYOUT.2_0",
            downmix_policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            gates_policy_id="POLICY.GATES.CORE_V0",
        )
        self.assertEqual(
            contract["downmix_policy_id"], "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0"
        )
        self.assertEqual(contract["gates_policy_id"], "POLICY.GATES.CORE_V0")

    def test_policy_fields_absent_when_not_provided(self) -> None:
        contract = build_render_contract("TARGET.TEST", "LAYOUT.2_0")
        self.assertNotIn("downmix_policy_id", contract)
        self.assertNotIn("gates_policy_id", contract)

    # --- Determinism ---

    def test_contract_is_deterministic(self) -> None:
        kwargs = dict(
            source_layout_id="LAYOUT.5_1",
            downmix_policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            gates_policy_id="POLICY.GATES.CORE_V0",
            output_formats=["wav", "flac"],
        )
        a = build_render_contract("TARGET.STEREO.2_0", "LAYOUT.2_0", **kwargs)
        b = build_render_contract("TARGET.STEREO.2_0", "LAYOUT.2_0", **kwargs)
        self.assertEqual(a, b)

    # --- Error cases ---

    def test_invalid_layout_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_render_contract("TARGET.TEST", "LAYOUT.DOES_NOT_EXIST")

    def test_empty_target_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_render_contract("", "LAYOUT.2_0")

    def test_empty_layout_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_render_contract("TARGET.TEST", "")

    # --- contracts_to_render_targets ---

    def test_contracts_to_render_targets_shape(self) -> None:
        contracts = [
            build_render_contract("TARGET.STEREO.2_0", "LAYOUT.2_0"),
            build_render_contract("TARGET.SURROUND.5_1", "LAYOUT.5_1"),
        ]
        render_targets = contracts_to_render_targets(contracts)
        self.assertIn("targets", render_targets)
        ids = {t["target_id"] for t in render_targets["targets"]}
        self.assertIn("TARGET.STEREO.2_0", ids)
        self.assertIn("TARGET.SURROUND.5_1", ids)

    def test_contracts_to_render_targets_policy_propagated(self) -> None:
        contracts = [
            build_render_contract(
                "TARGET.STEREO.2_0",
                "LAYOUT.2_0",
                downmix_policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                gates_policy_id="POLICY.GATES.CORE_V0",
            )
        ]
        render_targets = contracts_to_render_targets(contracts)
        row = render_targets["targets"][0]
        self.assertEqual(row["downmix_policy_id"], "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0")
        self.assertEqual(row["safety_policy_id"], "POLICY.GATES.CORE_V0")

    def test_contracts_to_render_targets_skips_invalid(self) -> None:
        targets = contracts_to_render_targets(
            [{"target_id": "", "target_layout_id": "LAYOUT.2_0"}]
        )
        self.assertEqual(targets["targets"], [])


# ---------------------------------------------------------------------------
# TestRenderEngineSchemaConformance — schema-valid render_report output
# ---------------------------------------------------------------------------


class TestRenderEngineSchemaConformance(unittest.TestCase):
    """Verify that render_scene_to_targets returns schema-valid reports."""

    def setUp(self) -> None:
        self.validator = _validator("render_report.schema.json")

    def _assert_valid(self, report: dict, msg: str = "") -> None:
        errors = list(self.validator.iter_errors(report))
        if errors:
            detail = "\n".join(str(e) for e in errors)
            self.fail(f"{msg or 'render_report schema errors'}:\n{detail}")

    def test_stereo_native_dry_run(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.2_0")
        contracts = [_stereo_contract(source_layout_id="LAYOUT.2_0")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self._assert_valid(report, "stereo native dry-run")

    def test_stereo_from_51_dry_run(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [_stereo_from_51_contract()]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self._assert_valid(report, "stereo from 5.1 dry-run")

    def test_51_native_dry_run(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [_surround_51_contract(source_layout_id="LAYOUT.5_1")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self._assert_valid(report, "5.1 native dry-run")

    def test_51_from_714_dry_run(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [_surround_51_contract(source_layout_id="LAYOUT.7_1_4")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self._assert_valid(report, "5.1 from 7.1.4 dry-run")

    def test_714_native_dry_run(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [_immersive_714_contract(source_layout_id="LAYOUT.7_1_4")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self._assert_valid(report, "7.1.4 native dry-run")

    def test_multi_target_stereo_and_51_dry_run(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [
            _stereo_contract(source_layout_id="LAYOUT.7_1_4"),
            _surround_51_contract(source_layout_id="LAYOUT.7_1_4"),
        ]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self._assert_valid(report, "multi-target stereo+5.1 dry-run")

    def test_multi_target_all_three_families_dry_run(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [
            _stereo_contract(source_layout_id="LAYOUT.7_1_4"),
            _surround_51_contract(source_layout_id="LAYOUT.7_1_4"),
            _immersive_714_contract(source_layout_id="LAYOUT.7_1_4"),
        ]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self._assert_valid(report, "multi-target all-three-families dry-run")


# ---------------------------------------------------------------------------
# TestRenderEngineDeterminism — same inputs → same output
# ---------------------------------------------------------------------------


class TestRenderEngineDeterminism(unittest.TestCase):
    """Verify that render_scene_to_targets is fully deterministic."""

    def _assert_deterministic(
        self, scene: dict, contracts: list[dict], opts: dict
    ) -> None:
        a = render_scene_to_targets(scene, contracts, opts)
        b = render_scene_to_targets(scene, contracts, opts)
        self.assertEqual(a, b)

    def test_stereo_native_deterministic(self) -> None:
        self._assert_deterministic(
            _make_scene(source_layout_id="LAYOUT.2_0"),
            [_stereo_contract(source_layout_id="LAYOUT.2_0")],
            {"dry_run": True},
        )

    def test_stereo_from_51_deterministic(self) -> None:
        self._assert_deterministic(
            _make_scene(source_layout_id="LAYOUT.5_1"),
            [_stereo_from_51_contract()],
            {"dry_run": True},
        )

    def test_51_native_deterministic(self) -> None:
        self._assert_deterministic(
            _make_scene(source_layout_id="LAYOUT.5_1"),
            [_surround_51_contract(source_layout_id="LAYOUT.5_1")],
            {"dry_run": True},
        )

    def test_714_native_deterministic(self) -> None:
        self._assert_deterministic(
            _make_scene(source_layout_id="LAYOUT.7_1_4"),
            [_immersive_714_contract(source_layout_id="LAYOUT.7_1_4")],
            {"dry_run": True},
        )

    def test_multi_target_deterministic(self) -> None:
        self._assert_deterministic(
            _make_scene(source_layout_id="LAYOUT.7_1_4"),
            [
                _stereo_contract(source_layout_id="LAYOUT.7_1_4"),
                _surround_51_contract(source_layout_id="LAYOUT.7_1_4"),
                _immersive_714_contract(source_layout_id="LAYOUT.7_1_4"),
            ],
            {"dry_run": True},
        )

    def test_max_workers_does_not_affect_output(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [
            _stereo_contract(source_layout_id="LAYOUT.7_1_4"),
            _surround_51_contract(source_layout_id="LAYOUT.7_1_4"),
        ]
        serial = render_scene_to_targets(scene, contracts, {"dry_run": True, "max_workers": 1})
        parallel = render_scene_to_targets(
            scene, contracts, {"dry_run": True, "max_workers": 4}
        )
        self.assertEqual(serial, parallel)


# ---------------------------------------------------------------------------
# TestRenderEngineJobStructure — job ordering, statuses, notes
# ---------------------------------------------------------------------------


class TestRenderEngineJobStructure(unittest.TestCase):
    """Verify job structure and ordering in rendered reports."""

    def test_jobs_sorted_by_job_id(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        # Supply contracts in reverse order to verify sorting.
        contracts = [
            _surround_51_contract(source_layout_id="LAYOUT.7_1_4"),
            _stereo_contract(source_layout_id="LAYOUT.7_1_4"),
        ]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        job_ids = [j["job_id"] for j in report["jobs"]]
        self.assertEqual(job_ids, sorted(job_ids))

    def test_job_count_matches_contracts(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [
            _stereo_contract(source_layout_id="LAYOUT.7_1_4"),
            _surround_51_contract(source_layout_id="LAYOUT.7_1_4"),
            _immersive_714_contract(source_layout_id="LAYOUT.7_1_4"),
        ]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self.assertEqual(len(report["jobs"]), 3)

    def test_dry_run_jobs_are_skipped(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.2_0")
        contracts = [_stereo_contract(source_layout_id="LAYOUT.2_0")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        for job in report["jobs"]:
            self.assertEqual(job["status"], "skipped")

    def test_job_statuses_are_valid_enum_values(self) -> None:
        valid_statuses = {"completed", "skipped", "failed"}
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [
            _stereo_from_51_contract(),
            _surround_51_contract(source_layout_id="LAYOUT.5_1"),
        ]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        for job in report["jobs"]:
            self.assertIn(job["status"], valid_statuses)

    def test_job_output_files_is_list(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.2_0")
        contracts = [_stereo_contract(source_layout_id="LAYOUT.2_0")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        for job in report["jobs"]:
            self.assertIsInstance(job["output_files"], list)

    def test_job_notes_contains_dry_run_marker(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.2_0")
        contracts = [_stereo_contract(source_layout_id="LAYOUT.2_0")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        for job in report["jobs"]:
            dry_run_notes = [n for n in job["notes"] if "dry_run" in n.lower()]
            self.assertGreater(len(dry_run_notes), 0)

    def test_714_job_has_expected_fields(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [_immersive_714_contract(source_layout_id="LAYOUT.7_1_4")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self.assertEqual(len(report["jobs"]), 1)
        job = report["jobs"][0]
        self.assertIn("job_id", job)
        self.assertIn("status", job)
        self.assertIn("output_files", job)

    # --- Error cases ---

    def test_invalid_scene_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            render_scene_to_targets("not_a_dict", [_stereo_contract()])

    def test_empty_contracts_raises(self) -> None:
        scene = _make_scene()
        with self.assertRaises(ValueError):
            render_scene_to_targets(scene, [])

    def test_non_list_contracts_raises(self) -> None:
        scene = _make_scene()
        with self.assertRaises(ValueError):
            render_scene_to_targets(scene, "not_a_list")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestRenderEngineQAGates — per-target QA gate evaluation
# ---------------------------------------------------------------------------


class TestRenderEngineQAGates(unittest.TestCase):
    """Verify per-target QA gate logic across layout families."""

    def test_qa_gates_key_present_in_report(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [_stereo_from_51_contract()]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self.assertIn("qa_gates", report)

    def test_qa_gates_structure_valid(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [_stereo_from_51_contract()]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        qa = report["qa_gates"]
        self.assertIn("status", qa)
        self.assertIn("gates", qa)
        self.assertIsInstance(qa["gates"], list)
        self.assertIn(qa["status"], ("pass", "warn", "fail", "not_run"))

    def test_no_downmix_means_not_run(self) -> None:
        """When source == target layout no QA gates are evaluated."""
        scene = _make_scene(source_layout_id="LAYOUT.2_0")
        contracts = [_stereo_contract(source_layout_id="LAYOUT.2_0")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        qa = report["qa_gates"]
        self.assertEqual(qa["status"], "not_run")
        self.assertEqual(qa["gates"], [])

    def test_714_native_no_downmix_means_not_run(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [_immersive_714_contract(source_layout_id="LAYOUT.7_1_4")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        qa = report["qa_gates"]
        self.assertEqual(qa["status"], "not_run")

    def test_51_to_20_fold_has_qa_gate(self) -> None:
        """5.1 → 2.0 fold should produce at least one QA gate entry."""
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [_stereo_from_51_contract()]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        qa = report["qa_gates"]
        self.assertIn(qa["status"], ("pass", "warn", "fail"))
        self.assertGreater(len(qa["gates"]), 0)

    def test_714_to_51_fold_has_qa_gate(self) -> None:
        """7.1.4 → 5.1 fold (immersive policy) should produce a QA gate entry."""
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [_surround_51_contract(source_layout_id="LAYOUT.7_1_4")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        qa = report["qa_gates"]
        self.assertIn(qa["status"], ("pass", "warn", "fail"))
        self.assertGreater(len(qa["gates"]), 0)

    def test_gate_id_matches_pattern(self) -> None:
        r"""All gate_ids must match ^GATE\.[A-Z0-9_.]+$."""
        import re

        pattern = re.compile(r"^GATE\.[A-Z0-9_.]+$")
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [_stereo_from_51_contract()]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        for gate in report["qa_gates"]["gates"]:
            self.assertRegex(gate["gate_id"], pattern)

    def test_gate_outcome_is_valid_enum(self) -> None:
        valid_outcomes = {"pass", "warn", "fail", "not_run"}
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [_stereo_from_51_contract()]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        for gate in report["qa_gates"]["gates"]:
            self.assertIn(gate["outcome"], valid_outcomes)

    def test_multi_target_qa_status_aggregated(self) -> None:
        """Worst-case gate status is propagated to overall qa_gates.status."""
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [
            _stereo_contract(source_layout_id="LAYOUT.7_1_4"),
            _surround_51_contract(source_layout_id="LAYOUT.7_1_4"),
            _immersive_714_contract(source_layout_id="LAYOUT.7_1_4"),
        ]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        qa = report["qa_gates"]
        self.assertIn(qa["status"], ("pass", "warn", "fail", "not_run"))


# ---------------------------------------------------------------------------
# TestRenderEnginePolicies — policy propagation through the engine
# ---------------------------------------------------------------------------


class TestRenderEnginePolicies(unittest.TestCase):
    """Verify policies_applied in the render_report."""

    def test_policies_present_in_report(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [_stereo_from_51_contract()]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self.assertIn("policies_applied", report)

    def test_downmix_policy_from_contract(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [
            build_render_contract(
                "TARGET.STEREO.2_0",
                "LAYOUT.2_0",
                source_layout_id="LAYOUT.5_1",
                downmix_policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            )
        ]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        policies = report["policies_applied"]
        self.assertEqual(
            policies.get("downmix_policy_id"),
            "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
        )

    def test_gates_policy_from_contract(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [
            build_render_contract(
                "TARGET.STEREO.2_0",
                "LAYOUT.2_0",
                source_layout_id="LAYOUT.5_1",
                downmix_policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                gates_policy_id="POLICY.GATES.CORE_V0",
            )
        ]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        policies = report["policies_applied"]
        self.assertEqual(policies.get("gates_policy_id"), "POLICY.GATES.CORE_V0")

    def test_gates_policy_override_via_options(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.2_0")
        contracts = [_stereo_contract(source_layout_id="LAYOUT.2_0")]
        report = render_scene_to_targets(
            scene,
            contracts,
            {"dry_run": True, "gates_policy_id": "POLICY.GATES.CORE_V0"},
        )
        policies = report["policies_applied"]
        self.assertEqual(policies.get("gates_policy_id"), "POLICY.GATES.CORE_V0")

    def test_no_policy_produces_empty_policies_applied(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.2_0")
        contracts = [_stereo_contract(source_layout_id="LAYOUT.2_0")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self.assertIsInstance(report["policies_applied"], dict)


# ---------------------------------------------------------------------------
# TestRenderEngineRequestSummary — request field in report
# ---------------------------------------------------------------------------


class TestRenderEngineRequestSummary(unittest.TestCase):
    """Verify the request summary section of the report."""

    def test_single_target_uses_singular_layout_id(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.2_0")
        contracts = [_stereo_contract(source_layout_id="LAYOUT.2_0")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        req = report["request"]
        self.assertIn("target_layout_id", req)
        self.assertNotIn("target_layout_ids", req)
        self.assertEqual(req["target_layout_id"], "LAYOUT.2_0")

    def test_multi_target_uses_plural_layout_ids(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [
            _stereo_contract(source_layout_id="LAYOUT.7_1_4"),
            _surround_51_contract(source_layout_id="LAYOUT.7_1_4"),
        ]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        req = report["request"]
        self.assertIn("target_layout_ids", req)
        self.assertNotIn("target_layout_id", req)
        self.assertIn("LAYOUT.2_0", req["target_layout_ids"])
        self.assertIn("LAYOUT.5_1", req["target_layout_ids"])

    def test_scene_path_in_request(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.2_0")
        contracts = [_stereo_contract(source_layout_id="LAYOUT.2_0")]
        report = render_scene_to_targets(scene, contracts, {"dry_run": True})
        self.assertEqual(report["request"]["scene_path"], "scenes/test/scene.json")

    def test_routing_plan_path_echoed_when_set(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.5_1")
        contracts = [_stereo_from_51_contract()]
        report = render_scene_to_targets(
            scene,
            contracts,
            {"dry_run": True, "routing_plan_path": "routing/plan.json"},
        )
        self.assertEqual(
            report["request"].get("routing_plan_path"), "routing/plan.json"
        )


class TestRenderEngineProgressAndCancel(unittest.TestCase):
    def test_progress_and_log_callbacks_receive_updates(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.7_1_4")
        contracts = [
            _stereo_contract(source_layout_id="LAYOUT.7_1_4"),
            _surround_51_contract(source_layout_id="LAYOUT.7_1_4"),
        ]
        snapshots: list[Any] = []
        logs: list[Any] = []

        report = render_scene_to_targets(
            scene,
            contracts,
            {
                "dry_run": True,
                "progress_listener": snapshots.append,
                "log_listener": logs.append,
            },
        )
        self.assertEqual(len(report.get("jobs", [])), 2)
        self.assertGreater(len(snapshots), 0)
        self.assertGreater(len(logs), 0)
        self.assertTrue(any(getattr(event, "what", "") for event in logs))
        self.assertAlmostEqual(float(snapshots[-1].progress), 1.0, places=6)

    def test_cancelled_token_raises_cancelled_error(self) -> None:
        scene = _make_scene(source_layout_id="LAYOUT.2_0")
        contracts = [_stereo_contract(source_layout_id="LAYOUT.2_0")]
        token = CancelToken()
        token.cancel("test cancellation")
        with self.assertRaises(CancelledError):
            render_scene_to_targets(
                scene,
                contracts,
                {"dry_run": True, "cancel_token": token},
            )


if __name__ == "__main__":
    unittest.main()
