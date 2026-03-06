"""Immersive golden-path fixture test: classify -> bus-plan -> scene -> render-many.

This CI tripwire validates a tiny deterministic session for:
  stems classify -> stems bus-plan -> scene build -> scene template apply
  -> safe-render --render-many (2.0/5.1/7.1/7.1.4/9.1.6)
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import unittest
import wave
from pathlib import Path
from typing import Any

from mmo.cli import main
from mmo.core.downmix import enforce_rendered_surround_similarity_gate

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = _REPO_ROOT / "fixtures" / "golden_path_small"
_EXPECTED_PATH = _FIXTURE_ROOT / "expected_golden_hashes.json"
_PLUGINS_DIR = _REPO_ROOT / "plugins"
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_immersive_golden_path_small" / str(os.getpid())
)


class _MissingTruthMeters(RuntimeError):
    """Raised when rendered similarity checks require unavailable optional deps."""


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_expected_fixture() -> dict[str, Any]:
    payload = json.loads(_EXPECTED_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Fixture payload must be an object: {_EXPECTED_PATH}")
    return payload


def _build_report_from_stems_map(*, stems_map_path: Path, report_path: Path) -> None:
    stems_map_payload = json.loads(stems_map_path.read_text(encoding="utf-8"))
    assignments = stems_map_payload.get("assignments")
    if not isinstance(assignments, list):
        raise ValueError("stems_map assignments must be a list")

    stems: list[dict[str, Any]] = []
    for row in sorted(
        (item for item in assignments if isinstance(item, dict)),
        key=lambda item: str(item.get("rel_path", "")),
    ):
        stem_id = str(row.get("file_id", "")).strip()
        rel_path = str(row.get("rel_path", "")).strip()
        if not stem_id or not rel_path:
            continue
        source_path = _FIXTURE_ROOT / rel_path
        with wave.open(str(source_path), "rb") as handle:
            channel_count = int(handle.getnchannels())
            sample_rate_hz = int(handle.getframerate())
            frame_count = int(handle.getnframes())

        stems.append(
            {
                "stem_id": stem_id,
                "file_path": rel_path,
                "channel_count": channel_count,
                "sample_rate_hz": sample_rate_hz,
                "frame_count": frame_count,
                "measurements": [
                    {
                        "evidence_id": "EVID.METER.CLIP_SAMPLE_COUNT",
                        "unit_id": "UNIT.COUNT",
                        "value": 0,
                    },
                    {
                        "evidence_id": "EVID.METER.PEAK_DBFS",
                        "unit_id": "UNIT.DBFS",
                        "value": -9.0,
                    },
                ],
            }
        )

    report_payload: dict[str, Any] = {
        "schema_version": "0.1.0",
        "report_id": "REPORT.GOLDEN_PATH.SMALL",
        "project_id": "PROJECT.GOLDEN_PATH.SMALL",
        "generated_at": "2026-01-01T00:00:00Z",
        "engine_version": "0.1.0",
        "ontology_version": "0.1.0",
        # Intentionally omit source_layout_id so preflight uses conservative
        # non-blocking behavior for this mixed mono/stereo fixture across all targets.
        "session": {
            "stems_dir": (_FIXTURE_ROOT / "stems").resolve().as_posix(),
            "stems": stems,
        },
        "issues": [],
        "recommendations": [],
        "features": {},
    }
    _write_json(report_path, report_payload)


def _target_slug(layout_id: str) -> str:
    return layout_id.replace(".", "_")


def _run_chain(
    *,
    run_root: Path,
    targets: list[str],
    scene_template_id: str,
) -> dict[str, Any]:
    run_root.mkdir(parents=True, exist_ok=True)
    stems_map_path = run_root / "stems_map.json"
    bus_plan_path = run_root / "bus_plan.json"
    scene_raw_path = run_root / "scene.raw.json"
    scene_path = run_root / "scene.audience.json"
    report_path = run_root / "report.json"
    renders_dir = run_root / "renders"
    receipt_path = run_root / "receipt.json"

    exit_code, _stdout, stderr = _run_main(
        ["stems", "classify", "--root", str(_FIXTURE_ROOT), "--out", str(stems_map_path)]
    )
    if exit_code != 0:
        raise AssertionError(f"stems classify failed:\n{stderr}")

    exit_code, _stdout, stderr = _run_main(
        ["stems", "bus-plan", "--map", str(stems_map_path), "--out", str(bus_plan_path)]
    )
    if exit_code != 0:
        raise AssertionError(f"stems bus-plan failed:\n{stderr}")

    exit_code, _stdout, stderr = _run_main(
        [
            "scene",
            "build",
            "--map",
            str(stems_map_path),
            "--bus",
            str(bus_plan_path),
            "--profile",
            "PROFILE.ASSIST",
            "--out",
            str(scene_raw_path),
        ]
    )
    if exit_code != 0:
        raise AssertionError(f"scene build failed:\n{stderr}")

    exit_code, _stdout, stderr = _run_main(
        [
            "scene",
            "template",
            "apply",
            scene_template_id,
            "--scene",
            str(scene_raw_path),
            "--out",
            str(scene_path),
        ]
    )
    if exit_code != 0:
        raise AssertionError(f"scene template apply failed:\n{stderr}")

    _build_report_from_stems_map(stems_map_path=stems_map_path, report_path=report_path)

    exit_code, _stdout, stderr = _run_main(
        [
            "safe-render",
            "--report",
            str(report_path),
            "--plugins",
            str(_PLUGINS_DIR),
            "--scene",
            str(scene_path),
            "--render-many",
            "--render-many-targets",
            ",".join(targets),
            "--out-dir",
            str(renders_dir),
            "--receipt-out",
            str(receipt_path),
            "--force",
        ]
    )
    if exit_code != 0:
        raise AssertionError(f"safe-render render-many failed:\n{stderr}")

    scene_payload = json.loads(scene_path.read_text(encoding="utf-8"))
    hashes: dict[str, str] = {}
    channel_counts: dict[str, int] = {}
    master_paths: dict[str, Path] = {}
    for layout_id in targets:
        master_path = renders_dir / _target_slug(layout_id) / "master.wav"
        if not master_path.is_file():
            raise AssertionError(f"missing master output for {layout_id}: {master_path}")
        if master_path.stat().st_size <= 44:
            raise AssertionError(f"master output too small for {layout_id}: {master_path}")
        with wave.open(str(master_path), "rb") as handle:
            channel_counts[layout_id] = int(handle.getnchannels())
        hashes[layout_id] = _sha256(master_path)
        master_paths[layout_id] = master_path

    return {
        "scene_payload": scene_payload,
        "hashes": hashes,
        "channel_counts": channel_counts,
        "master_paths": master_paths,
    }


def _assert_rendered_similarity(
    *,
    master_paths: dict[str, Path],
    targets: list[str],
    run_root: Path,
) -> None:
    stereo_path = master_paths["LAYOUT.2_0"]
    for layout_id in targets:
        if layout_id == "LAYOUT.2_0":
            continue
        source_path = master_paths[layout_id]
        slug = _target_slug(layout_id)
        gate_copy_a = run_root / f"similarity.{slug}.a.wav"
        gate_copy_b = run_root / f"similarity.{slug}.b.wav"
        gate_copy_a.write_bytes(source_path.read_bytes())
        gate_copy_b.write_bytes(source_path.read_bytes())

        try:
            result_a = enforce_rendered_surround_similarity_gate(
                stereo_render_file=stereo_path,
                surround_render_file=gate_copy_a,
                source_layout_id=layout_id,
                surround_backoff_db=-24.0,
            )
            result_b = enforce_rendered_surround_similarity_gate(
                stereo_render_file=stereo_path,
                surround_render_file=gate_copy_b,
                source_layout_id=layout_id,
                surround_backoff_db=-24.0,
            )
        except RuntimeError as exc:
            message = str(exc).lower()
            if "numpy" in message or "truth meter" in message:
                raise _MissingTruthMeters(str(exc)) from exc
            raise

        if json.dumps(result_a, sort_keys=True) != json.dumps(result_b, sort_keys=True):
            raise AssertionError(f"similarity gate result drifted for {layout_id}")
        if not bool(result_a.get("passed")):
            raise AssertionError(f"similarity gate did not pass for {layout_id}: {result_a}")

        attempts = result_a.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise AssertionError(f"similarity gate attempts missing for {layout_id}")
        if bool(result_a.get("fallback_applied")):
            if len(attempts) != 2:
                raise AssertionError(f"expected one deterministic retry for {layout_id}")
            if bool(attempts[0].get("passed")):
                raise AssertionError(f"first attempt unexpectedly passed for {layout_id}")
            if not bool(attempts[1].get("passed")):
                raise AssertionError(f"retry attempt failed for {layout_id}")
        else:
            if not bool(attempts[0].get("passed")):
                raise AssertionError(f"first attempt failed without fallback for {layout_id}")


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestCliImmersiveGoldenPathSmall(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = _load_expected_fixture()
        targets = cls.expected.get("targets")
        if not isinstance(targets, list) or not targets:
            raise AssertionError("expected fixture targets must be a non-empty list")
        cls.targets = [str(item) for item in targets]
        cls.scene_template_id = str(cls.expected.get("scene_template_id", "")).strip()
        if not cls.scene_template_id:
            raise AssertionError("expected fixture scene_template_id is required")

        cls.run_a = _run_chain(
            run_root=_SANDBOX / "run_a",
            targets=cls.targets,
            scene_template_id=cls.scene_template_id,
        )
        cls.run_b = _run_chain(
            run_root=_SANDBOX / "run_b",
            targets=cls.targets,
            scene_template_id=cls.scene_template_id,
        )

    def test_scene_template_choice_is_audience(self) -> None:
        perspective_a = (
            self.run_a["scene_payload"].get("intent", {}).get("perspective")
            if isinstance(self.run_a.get("scene_payload"), dict)
            else None
        )
        perspective_b = (
            self.run_b["scene_payload"].get("intent", {}).get("perspective")
            if isinstance(self.run_b.get("scene_payload"), dict)
            else None
        )
        self.assertEqual(perspective_a, "audience")
        self.assertEqual(perspective_b, "audience")

    def test_channel_counts_and_hashes_are_stable(self) -> None:
        expected_channels = self.expected.get("expected_channel_counts")
        expected_hashes = self.expected.get("expected_master_wav_sha256")
        self.assertIsInstance(expected_channels, dict)
        self.assertIsInstance(expected_hashes, dict)
        if not isinstance(expected_channels, dict) or not isinstance(expected_hashes, dict):
            return

        self.assertEqual(self.run_a["channel_counts"], expected_channels)
        self.assertEqual(self.run_b["channel_counts"], expected_channels)
        self.assertEqual(self.run_a["hashes"], self.run_b["hashes"])
        self.assertEqual(self.run_a["hashes"], expected_hashes)

    def test_rendered_similarity_passes_or_deterministic_backoff_then_passes(self) -> None:
        try:
            _assert_rendered_similarity(
                master_paths=self.run_a["master_paths"],
                targets=self.targets,
                run_root=_SANDBOX / "run_a",
            )
            _assert_rendered_similarity(
                master_paths=self.run_b["master_paths"],
                targets=self.targets,
                run_root=_SANDBOX / "run_b",
            )
        except _MissingTruthMeters as exc:
            self.skipTest(f"Rendered similarity gate deps unavailable: {exc}")

