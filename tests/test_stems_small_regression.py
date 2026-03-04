from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

import jsonschema

from mmo.core.bus_plan import build_bus_plan
from mmo.core.preflight import evaluate_preflight
from mmo.core.registries.render_targets_registry import load_render_targets_registry
from mmo.core.render_plan import build_render_plan
from mmo.core.roles import load_roles
from mmo.core.scene_builder import build_scene_from_bus_plan
from mmo.core.stems_classifier import classify_stems
from mmo.core.stems_index import build_stems_index

_SOURCE_LAYOUT_ID = "LAYOUT.9_1_6"
_RENDER_TARGET_IDS = [
    "TARGET.STEREO.2_0",
    "TARGET.SURROUND.5_1",
    "TARGET.SURROUND.7_1",
    "TARGET.IMMERSIVE.7_1_4",
    "TARGET.IMMERSIVE.9_1_6",
]
_DOWNMIX_TARGET_TOKENS = ["stereo", "5.1", "7.1", "7.1.4"]
_DOWNMIX_GATE_OPTIONS = {
    "warn_on_composed_path": False,
    "lfe_boost_warn_db": 12.0,
    "lfe_boost_error_db": 18.0,
    "predicted_lufs_delta_warn_abs": 12.0,
    "predicted_lufs_delta_error_abs": 18.0,
}

_EXPECTED_BUS_PLAN_SHA256 = {
    "immersive_7_1_4_catalog": "711289fdb4dac9a2b4f89873728b97ba4bd1a711bfaecaf242f7eb8e329a12e0",
    "immersive_9_1_6_catalog": "a06f6f098bf681949bfa21b35f69ef1eae66c8bba0aecac0d9c36ec0936f615e",
    "stereo_catalog": "1660c7085adf5960c71dbb8691cc5b8fbdf70bafbd94230139ef01223de3b9a5",
    "surround_5_1_catalog": "e5919d9c0aaf9921d7fedc1afc18a49ef03d67a28e5c8a54d0238ffd917ca0fc",
    "surround_7_1_catalog": "9aedc80b901f0629e82d590487358fff202a252e1b3a37aaa51c0416fcc02edf",
}
_EXPECTED_SCENE_SHA256 = {
    "immersive_7_1_4_catalog": "f00bcb6720cc1891058fad9a0782d9ba8aed7123c9589a707d573b01a9157aa7",
    "immersive_9_1_6_catalog": "4b5598aea9c8715f7fa8700947b8089ee0b012251ebfdc7b563407be7b1ebf82",
    "stereo_catalog": "3b730c4bfec9014234f0d3779fa6882ed05a426f60560415294aeb4ffa601121",
    "surround_5_1_catalog": "8aa49be7b671399655edd865ad792042f493616e1ca34056061984ea403e90bf",
    "surround_7_1_catalog": "0a1307d8c89b9f100e6dfc58865409af8580694ef07bcf8472569069718e0120",
}
_EXPECTED_RENDER_PLAN_SHA256 = {
    "immersive_7_1_4_catalog": "602e7a05c9905202f23294df4e2d4d0c8c79f494b66fbcf96bd6b1bb8feba72c",
    "immersive_9_1_6_catalog": "53e09a894c19a88342453050a48ee4b37fc55460600094367544e78831be96b5",
    "stereo_catalog": "4315812cfe7ee1d35f2695dc7864dda6f56a6e4f8b045bb28c309c3a165c2436",
    "surround_5_1_catalog": "cbddc68f11d2f1db153b652b97482a58f342787065ef875e773012531e225072",
    "surround_7_1_catalog": "78de1fd7ff52dffac415dd4a5dbd4419b176da23aa6c48d26a2dbf67cbf9b7af",
}


def _canonical_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


class TestStemsSmallRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._repo_root = Path(__file__).resolve().parents[1]
        cls._fixtures_root = cls._repo_root / "fixtures"
        cls._sessions_root = cls._fixtures_root / "stems_small"
        cls._roles = load_roles(cls._repo_root / "ontology" / "roles.yaml")

        cls._expected_bus = json.loads(
            (cls._fixtures_root / "expected_bus_plan.json").read_text(encoding="utf-8")
        )
        cls._expected_scene = json.loads(
            (cls._fixtures_root / "expected_scene.json").read_text(encoding="utf-8")
        )

        cls._bus_validator = _schema_validator(
            cls._repo_root / "schemas" / "bus_plan.schema.json"
        )
        cls._scene_validator = _schema_validator(
            cls._repo_root / "schemas" / "scene.schema.json"
        )

        registry = load_render_targets_registry(cls._repo_root / "ontology" / "render_targets.yaml")
        cls._render_targets = {
            "targets": [registry.get_target(target_id) for target_id in _RENDER_TARGET_IDS]
        }

    def _session_names(self) -> list[str]:
        return sorted(
            [
                item.name
                for item in self._sessions_root.iterdir()
                if item.is_dir()
            ]
        )

    def _build_outputs(self, session_name: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        session_dir = self._sessions_root / session_name
        fixture_prefix = f"fixtures/stems_small/{session_name}"

        stems_index = build_stems_index(session_dir, root_dir=fixture_prefix)
        stems_map = classify_stems(
            stems_index,
            self._roles,
            stems_index_ref=f"{fixture_prefix}/stems_index.json",
            roles_ref="ontology/roles.yaml",
        )
        stems_map["stems_map_ref"] = f"{fixture_prefix}/stems_map.json"

        bus_plan = build_bus_plan(stems_map, self._roles)
        scene = build_scene_from_bus_plan(
            stems_map,
            bus_plan,
            profile_id="PROFILE.ASSIST",
            stems_map_ref=f"{fixture_prefix}/stems_map.json",
            bus_plan_ref=f"{fixture_prefix}/bus_plan.json",
        )

        scene_for_plan = copy.deepcopy(scene)
        metadata = scene_for_plan.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["source_layout_id"] = _SOURCE_LAYOUT_ID
        render_plan = build_render_plan(
            scene_for_plan,
            self._render_targets,
            routing_plan_path=None,
            output_formats=["wav"],
            contexts=["render"],
            policies={},
        )
        return bus_plan, scene, render_plan

    def test_expected_sessions_and_hash_maps_are_complete(self) -> None:
        sessions = self._session_names()
        self.assertEqual(sessions, sorted(self._expected_bus.get("sessions", {}).keys()))
        self.assertEqual(sessions, sorted(self._expected_scene.get("sessions", {}).keys()))
        self.assertEqual(sessions, sorted(_EXPECTED_BUS_PLAN_SHA256.keys()))
        self.assertEqual(sessions, sorted(_EXPECTED_SCENE_SHA256.keys()))
        self.assertEqual(sessions, sorted(_EXPECTED_RENDER_PLAN_SHA256.keys()))

    def test_snapshots_and_hashes_are_stable(self) -> None:
        expected_bus_sessions = self._expected_bus["sessions"]
        expected_scene_sessions = self._expected_scene["sessions"]

        for session_name in self._session_names():
            bus_a, scene_a, _ = self._build_outputs(session_name)
            bus_b, scene_b, _ = self._build_outputs(session_name)

            self.assertEqual(bus_a, bus_b)
            self.assertEqual(scene_a, scene_b)

            self._bus_validator.validate(bus_a)
            self._scene_validator.validate(scene_a)

            self.assertEqual(bus_a, expected_bus_sessions[session_name])
            self.assertEqual(scene_a, expected_scene_sessions[session_name])

            self.assertEqual(_canonical_sha256(bus_a), _EXPECTED_BUS_PLAN_SHA256[session_name])
            self.assertEqual(_canonical_sha256(scene_a), _EXPECTED_SCENE_SHA256[session_name])

    def test_render_chain_targets_are_present_and_deterministic(self) -> None:
        expected_target_ids = sorted(_RENDER_TARGET_IDS)
        expected_layout_ids = sorted(
            ["LAYOUT.2_0", "LAYOUT.5_1", "LAYOUT.7_1", "LAYOUT.7_1_4", "LAYOUT.9_1_6"]
        )

        for session_name in self._session_names():
            _, _, render_plan_a = self._build_outputs(session_name)
            _, _, render_plan_b = self._build_outputs(session_name)

            self.assertEqual(render_plan_a, render_plan_b)
            self.assertEqual(
                _canonical_sha256(render_plan_a),
                _EXPECTED_RENDER_PLAN_SHA256[session_name],
            )

            jobs = render_plan_a.get("jobs")
            self.assertIsInstance(jobs, list)
            if not isinstance(jobs, list):
                continue
            target_ids = [
                job.get("target_id")
                for job in jobs
                if isinstance(job, dict) and isinstance(job.get("target_id"), str)
            ]
            layout_ids = [
                job.get("target_layout_id")
                for job in jobs
                if isinstance(job, dict) and isinstance(job.get("target_layout_id"), str)
            ]
            self.assertEqual(target_ids, expected_target_ids)
            self.assertEqual(sorted(layout_ids), expected_layout_ids)

    def test_downmix_gates_pass_for_downmix_chain(self) -> None:
        for session_name in self._session_names():
            _, scene, _ = self._build_outputs(session_name)

            for target_token in _DOWNMIX_TARGET_TOKENS:
                receipt = evaluate_preflight(
                    session={"source_layout_id": _SOURCE_LAYOUT_ID},
                    scene=scene,
                    target_layout=target_token,
                    options=dict(_DOWNMIX_GATE_OPTIONS),
                )
                gates = {
                    row.get("gate_id"): row.get("outcome")
                    for row in receipt.get("gates_evaluated", [])
                    if isinstance(row, dict)
                }
                self.assertEqual(
                    gates.get("GATE.LAYOUT_NEGOTIATION"),
                    "pass",
                    msg=f"{session_name} target={target_token} layout gate failed: {gates}",
                )
                self.assertEqual(
                    gates.get("GATE.DOWNMIX_SIMILARITY"),
                    "pass",
                    msg=f"{session_name} target={target_token} downmix gate failed: {gates}",
                )
                self.assertNotEqual(
                    receipt.get("final_decision"),
                    "block",
                    msg=f"{session_name} target={target_token} produced a blocking receipt",
                )


if __name__ == "__main__":
    unittest.main()
