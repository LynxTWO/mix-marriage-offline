"""Full-pipeline determinism harness using a public 7.1.4 session fixture."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import unittest
from pathlib import Path

import jsonschema

from mmo.cli import main
from mmo.cli_commands._renderers import _run_safe_render_command

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGINS_DIR = _REPO_ROOT / "plugins"
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_FIXTURE_PATH = _REPO_ROOT / "fixtures" / "public_session" / "report.7_1_4.json"
_SANDBOX = _REPO_ROOT / "sandbox_tmp" / "test_full_determinism" / str(os.getpid())
_STANDARDS = ("SMPTE", "FILM")


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _run_safe_render(
    *,
    standard: str,
    receipt_path: Path,
    manifest_path: Path,
) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = _run_safe_render_command(
            repo_root=_REPO_ROOT,
            report_path=_FIXTURE_PATH,
            plugins_dir=_PLUGINS_DIR,
            out_dir=None,
            out_manifest_path=manifest_path,
            receipt_out_path=receipt_path,
            qa_out_path=None,
            profile_id="PROFILE.ASSIST",
            target="7.1.4",
            dry_run=True,
            approve=None,
            output_formats=None,
            run_config=None,
            force=False,
            user_profile=None,
            render_many_targets=None,
            layout_standard=standard,
        )
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_schema(name: str) -> dict:
    return _load_json(_SCHEMAS_DIR / name)


def _validate_with_schema(payload: dict, schema_name: str) -> None:
    schema = _load_schema(schema_name)
    jsonschema.Draft202012Validator(schema).validate(payload)


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestFullDeterminism(unittest.TestCase):
    """Byte-stability checks across the safe-render + bundle pipeline."""

    def _run_pipeline_once(
        self, run_root: Path,
    ) -> tuple[dict[str, str], dict[str, str]]:
        run_root.mkdir(parents=True, exist_ok=True)
        artifact_hashes: dict[str, str] = {}
        stream_snapshots: dict[str, str] = {}

        for standard in _STANDARDS:
            standard_dir = run_root / standard
            standard_dir.mkdir(parents=True, exist_ok=True)

            receipt_path = standard_dir / "receipt.json"
            manifest_path = standard_dir / "render_manifest.json"
            bundle_path = standard_dir / "ui_bundle.json"

            exit_safe_render, stdout_safe_render, stderr_safe_render = _run_safe_render(
                standard=standard,
                receipt_path=receipt_path,
                manifest_path=manifest_path,
            )
            self.assertEqual(
                exit_safe_render, 0, msg=f"safe-render failed ({standard}): {stderr_safe_render}",
            )

            exit_bundle, stdout_bundle, stderr_bundle = _run_main(
                [
                    "bundle",
                    "--report", str(_FIXTURE_PATH),
                    "--render-manifest", str(manifest_path),
                    "--out", str(bundle_path),
                ]
            )
            self.assertEqual(
                exit_bundle, 0, msg=f"bundle failed ({standard}): {stderr_bundle}",
            )

            receipt_payload = _load_json(receipt_path)
            manifest_payload = _load_json(manifest_path)
            bundle_payload = _load_json(bundle_path)

            _validate_with_schema(receipt_payload, "safe_render_receipt.schema.json")
            _validate_with_schema(manifest_payload, "render_manifest.schema.json")
            self.assertIsInstance(bundle_payload, dict)
            self.assertIn("report", bundle_payload)

            notes = receipt_payload.get("notes")
            self.assertIsInstance(notes, list)
            self.assertTrue(
                any(
                    isinstance(note, str) and f"layout_standard={standard}" in note
                    for note in notes
                ),
                msg=f"Receipt notes missing layout_standard={standard}",
            )

            for artifact in (receipt_path, manifest_path, bundle_path):
                key = artifact.relative_to(run_root).as_posix()
                artifact_hashes[key] = _sha256(artifact)

            stream_snapshots[f"{standard}.safe_render.stdout"] = stdout_safe_render
            stream_snapshots[f"{standard}.safe_render.stderr"] = stderr_safe_render
            stream_snapshots[f"{standard}.bundle.stdout"] = stdout_bundle
            stream_snapshots[f"{standard}.bundle.stderr"] = stderr_bundle

        return artifact_hashes, stream_snapshots

    def test_public_fixture_is_schema_valid(self) -> None:
        payload = _load_json(_FIXTURE_PATH)
        _validate_with_schema(payload, "report.schema.json")

        session = payload.get("session", {})
        stems = session.get("stems", [])
        stem_ids = {stem.get("stem_id") for stem in stems if isinstance(stem, dict)}
        self.assertIn("bed_7_1_4_smpte", stem_ids)
        self.assertIn("bed_7_1_4_film", stem_ids)

    def test_pipeline_artifacts_are_byte_stable(self) -> None:
        hashes_a, streams_a = self._run_pipeline_once(_SANDBOX / "run_a")
        hashes_b, streams_b = self._run_pipeline_once(_SANDBOX / "run_b")

        self.assertGreater(len(hashes_a), 0, "No artifacts were produced")
        self.assertEqual(streams_a, streams_b, "CLI output changed across identical runs")
        self.assertEqual(hashes_a, hashes_b, "Artifact bytes changed across identical runs")


if __name__ == "__main__":
    unittest.main()
