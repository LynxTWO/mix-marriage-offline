"""Golden artifact regressions for packaged desktop smoke render truth."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES_ROOT = _REPO_ROOT / "fixtures" / "golden"
_PASSING_FIXTURES = (
    "packaged_smoke_full_success",
    "packaged_smoke_partial_multi_layout",
    "packaged_smoke_uniform_rate_44100",
)
_FAILING_FIXTURES = (
    "packaged_smoke_zero_decoded_failure",
    "packaged_smoke_silent_invalid",
)


def _load_module():
    module_path = _REPO_ROOT / "tools" / "smoke_packaged_desktop.py"
    spec = importlib.util.spec_from_file_location("smoke_packaged_desktop", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load smoke_packaged_desktop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _artifact_paths(fixture_root: Path) -> dict[str, str]:
    return {
        "renderManifestPath": (fixture_root / "render_manifest.json").as_posix(),
        "renderQaPath": (fixture_root / "render_qa.json").as_posix(),
        "renderReceiptPath": (fixture_root / "safe_render_receipt.json").as_posix(),
        "workspaceDir": fixture_root.as_posix(),
    }


def _normalize_payload(payload: Any, *, fixture_root: Path) -> Any:
    replacement = fixture_root.resolve().as_posix()
    if isinstance(payload, dict):
        return {
            key: _normalize_payload(value, fixture_root=fixture_root)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_normalize_payload(item, fixture_root=fixture_root) for item in payload]
    if isinstance(payload, str):
        return payload.replace("\\", "/").replace(replacement, "<FIXTURE_ROOT>")
    return payload


class TestPackagedSmokeGoldens(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()

    def test_expected_smoke_truth_snapshots_match(self) -> None:
        for fixture_id in (*_PASSING_FIXTURES, *_FAILING_FIXTURES):
            fixture_root = _FIXTURES_ROOT / fixture_id
            with self.subTest(fixture=fixture_id):
                actual = self.module.summarize_workspace_render_truth(
                    artifact_paths=_artifact_paths(fixture_root)
                )
                expected = json.loads(
                    (fixture_root / "expected_smoke_truth.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    _normalize_payload(actual, fixture_root=fixture_root),
                    _normalize_payload(expected, fixture_root=fixture_root),
                )

    def test_workspace_render_truth_validation_passes_for_success_and_partial(self) -> None:
        for fixture_id in _PASSING_FIXTURES:
            fixture_root = _FIXTURES_ROOT / fixture_id
            with self.subTest(fixture=fixture_id):
                truth = self.module._validate_workspace_render_truth(
                    artifact_paths=_artifact_paths(fixture_root)
                )
                self.assertTrue(truth.get("has_valid_master_audio_output"))

    def test_workspace_render_truth_validation_rejects_invalid_outputs(self) -> None:
        for fixture_id in _FAILING_FIXTURES:
            fixture_root = _FIXTURES_ROOT / fixture_id
            with self.subTest(fixture=fixture_id):
                with self.assertRaises(self.module.SmokeError):
                    self.module._validate_workspace_render_truth(
                        artifact_paths=_artifact_paths(fixture_root)
                    )


if __name__ == "__main__":
    unittest.main()
