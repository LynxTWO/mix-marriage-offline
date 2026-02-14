import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main
from mmo.core.listen_pack import index_stems_auditions


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(schema_path.parent.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _valid_manifest() -> dict[str, Any]:
    return {
        "segment_seconds": 30.0,
        "stems_dir": "/test/stems",
        "groups": [
            {
                "bus_group_id": "DRUMS",
                "output_wav": "drums.wav",
                "stems_included": ["drums/kick.wav", "drums/snare.wav"],
                "stems_missing": [],
                "stems_skipped_mismatch": [],
            },
            {
                "bus_group_id": "BASS",
                "output_wav": "bass.wav",
                "stems_included": ["bass/bass.wav"],
                "stems_missing": ["bass/sub.wav"],
                "stems_skipped_mismatch": [],
            },
            {
                "bus_group_id": "VOCALS",
                "output_wav": "",
                "stems_included": [],
                "stems_missing": ["vocals/lead.wav"],
                "stems_skipped_mismatch": [],
            },
        ],
        "warnings": [
            "Missing file: bass/sub.wav (group BASS)",
            "Missing file: vocals/lead.wav (group VOCALS)",
        ],
        "rendered_groups_count": 2,
        "attempted_groups_count": 3,
    }


def _variant_steps_payload() -> dict[str, Any]:
    return {
        "analyze": True,
        "routing": False,
        "downmix_qa": False,
        "export_pdf": False,
        "export_csv": False,
        "apply": False,
        "render": False,
        "bundle": True,
    }


def _build_fake_variant_result(temp_path: Path) -> dict[str, Any]:
    out_root = temp_path / "variants_out"
    stems_dir = temp_path / "stems"
    variant_dir = out_root / "VARIANT.001__warm"
    report_path = variant_dir / "report.json"
    bundle_path = variant_dir / "ui_bundle.json"

    _write_json(report_path, {
        "run_config": {
            "schema_version": "0.1.0",
            "profile_id": "PROFILE.ASSIST",
            "preset_id": "PRESET.VIBE.WARM_INTIMATE",
        },
        "vibe_signals": {
            "density_level": "low",
            "masking_level": "low",
            "translation_risk": "low",
            "notes": [],
        },
    })
    _write_json(bundle_path, {
        "dashboard": {
            "profile_id": "PROFILE.ASSIST",
            "vibe_signals": {
                "density_level": "low",
                "masking_level": "low",
                "translation_risk": "low",
                "notes": [],
            },
        }
    })

    return {
        "schema_version": "0.1.0",
        "plan": {
            "schema_version": "0.1.0",
            "stems_dir": stems_dir.resolve().as_posix(),
            "base_run_config": {
                "schema_version": "0.1.0",
                "profile_id": "PROFILE.ASSIST",
            },
            "variants": [
                {
                    "variant_id": "VARIANT.001",
                    "variant_slug": "warm",
                    "label": "PRESET.VIBE.WARM_INTIMATE",
                    "preset_id": "PRESET.VIBE.WARM_INTIMATE",
                    "steps": _variant_steps_payload(),
                },
            ],
        },
        "results": [
            {
                "variant_id": "VARIANT.001",
                "out_dir": variant_dir.resolve().as_posix(),
                "report_path": report_path.resolve().as_posix(),
                "bundle_path": bundle_path.resolve().as_posix(),
                "ok": True,
                "errors": [],
            },
        ],
    }


class TestIndexStemsAuditions(unittest.TestCase):
    def test_valid_manifest_indexed_deterministically(self) -> None:
        """Valid manifest produces present=True with correct counts."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            _write_json(manifest_path, _valid_manifest())

            result1 = index_stems_auditions(manifest_path)
            result2 = index_stems_auditions(manifest_path)

            self.assertTrue(result1["present"])
            self.assertEqual(result1["rendered_groups_count"], 2)
            self.assertEqual(result1["attempted_groups_count"], 3)
            self.assertEqual(result1["missing_files_count"], 2)
            self.assertEqual(result1["warnings_count"], 2)
            self.assertEqual(len(result1["groups"]), 3)
            # Determinism
            self.assertEqual(result1, result2)

    def test_groups_sorted_by_bus_group_id(self) -> None:
        """Groups summary must be sorted by bus_group_id."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            _write_json(manifest_path, _valid_manifest())

            result = index_stems_auditions(manifest_path)
            group_ids = [g["bus_group_id"] for g in result["groups"]]
            self.assertEqual(group_ids, ["BASS", "DRUMS", "VOCALS"])

    def test_missing_manifest_returns_present_false(self) -> None:
        """Missing manifest file results in present=False, no crash."""
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "nonexistent" / "manifest.json"
            result = index_stems_auditions(missing_path)

            self.assertFalse(result["present"])
            self.assertIn("warning", result)
            self.assertIn("not found", result["warning"])

    def test_invalid_manifest_yields_present_false_with_warning(self) -> None:
        """Invalid JSON manifest results in present=False + warning."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest_path.write_text("not valid json {{{", encoding="utf-8")

            result = index_stems_auditions(manifest_path)
            self.assertFalse(result["present"])
            self.assertIn("warning", result)
            self.assertIn("unreadable", result["warning"].lower())

    def test_manifest_not_dict_yields_present_false(self) -> None:
        """Manifest that is a JSON array (not object) yields present=False."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            manifest_path.write_text("[1, 2, 3]", encoding="utf-8")

            result = index_stems_auditions(manifest_path)
            self.assertFalse(result["present"])
            self.assertIn("not a JSON object", result["warning"])

    def test_output_wav_null_for_unrendered_group(self) -> None:
        """A group with empty output_wav maps to null in summary."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            _write_json(manifest_path, _valid_manifest())

            result = index_stems_auditions(manifest_path)
            vocals_group = [
                g for g in result["groups"] if g["bus_group_id"] == "VOCALS"
            ]
            self.assertEqual(len(vocals_group), 1)
            self.assertIsNone(vocals_group[0]["output_wav"])

    def test_forward_slash_manifest_path(self) -> None:
        """manifest_path should use forward slashes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            _write_json(manifest_path, _valid_manifest())

            result = index_stems_auditions(manifest_path)
            self.assertNotIn("\\", result["manifest_path"])

    def test_groups_capped_at_50(self) -> None:
        """Groups summary must be capped to 50 entries."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = _valid_manifest()
            manifest["groups"] = [
                {
                    "bus_group_id": f"GROUP_{i:03d}",
                    "output_wav": f"group_{i:03d}.wav",
                    "stems_included": [],
                    "stems_missing": [],
                    "stems_skipped_mismatch": [],
                }
                for i in range(60)
            ]
            manifest_path = Path(temp_dir) / "manifest.json"
            _write_json(manifest_path, manifest)

            result = index_stems_auditions(manifest_path)
            self.assertEqual(len(result["groups"]), 50)


class TestCliListenPackStemsAuditions(unittest.TestCase):
    def _run_main(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(args)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_cli_with_stems_auditions_manifest(self) -> None:
        """CLI with --stems-auditions-manifest produces valid listen-pack."""
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(
            repo_root / "schemas" / "listen_pack.schema.json"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            variant_result = _build_fake_variant_result(temp_path)
            vr_path = temp_path / "variant_result.json"
            out_path = temp_path / "listen_pack.json"
            manifest_path = temp_path / "manifest.json"

            _write_json(vr_path, variant_result)
            _write_json(manifest_path, _valid_manifest())

            exit_code, _, stderr = self._run_main([
                "variants", "listen-pack",
                "--variant-result", str(vr_path),
                "--out", str(out_path),
                "--stems-auditions-manifest", str(manifest_path),
            ])
            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            stems_aud = payload.get("stems_auditions")
            self.assertIsNotNone(stems_aud)
            self.assertTrue(stems_aud["present"])
            self.assertEqual(stems_aud["rendered_groups_count"], 2)
            group_ids = [g["bus_group_id"] for g in stems_aud["groups"]]
            self.assertEqual(group_ids, ["BASS", "DRUMS", "VOCALS"])

    def test_cli_without_stems_auditions_flag(self) -> None:
        """CLI without --stems-auditions-manifest omits the block entirely."""
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(
            repo_root / "schemas" / "listen_pack.schema.json"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            variant_result = _build_fake_variant_result(temp_path)
            vr_path = temp_path / "variant_result.json"
            out_path = temp_path / "listen_pack.json"

            _write_json(vr_path, variant_result)

            exit_code, _, stderr = self._run_main([
                "variants", "listen-pack",
                "--variant-result", str(vr_path),
                "--out", str(out_path),
            ])
            self.assertEqual(exit_code, 0, msg=stderr)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)
            self.assertNotIn("stems_auditions", payload)

    def test_cli_with_missing_manifest_still_succeeds(self) -> None:
        """Missing manifest produces present=False but command still exits 0."""
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(
            repo_root / "schemas" / "listen_pack.schema.json"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            variant_result = _build_fake_variant_result(temp_path)
            vr_path = temp_path / "variant_result.json"
            out_path = temp_path / "listen_pack.json"
            missing_manifest = temp_path / "no_such" / "manifest.json"

            _write_json(vr_path, variant_result)

            exit_code, _, stderr = self._run_main([
                "variants", "listen-pack",
                "--variant-result", str(vr_path),
                "--out", str(out_path),
                "--stems-auditions-manifest", str(missing_manifest),
            ])
            self.assertEqual(exit_code, 0, msg=stderr)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            validator.validate(payload)

            stems_aud = payload.get("stems_auditions")
            self.assertIsNotNone(stems_aud)
            self.assertFalse(stems_aud["present"])
            self.assertIn("warning", stems_aud)


if __name__ == "__main__":
    unittest.main()
