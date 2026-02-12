import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sample_scene(*, stems_dir: Path) -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.CLI.TEMPLATES.PREVIEW.TEST",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "analyze",
        },
        "objects": [
            {
                "object_id": "OBJ.Z_LOCKED",
                "stem_id": "STEM.Z_LOCKED",
                "label": "Lead Vocal Locked",
                "channel_count": 1,
                "intent": {
                    "confidence": 0.2,
                    "locks": ["LOCK.PRESERVE_DYNAMICS"],
                },
                "notes": [],
            },
            {
                "object_id": "OBJ.A_VOX",
                "stem_id": "STEM.A_VOX",
                "label": "Lead Vocal",
                "channel_count": 1,
                "notes": [],
            },
        ],
        "beds": [
            {
                "bed_id": "BED.Z_FIELD",
                "label": "Rear Field",
                "kind": "field",
                "intent": {"confidence": 0.2, "locks": []},
                "notes": [],
            },
            {
                "bed_id": "BED.A_FIELD",
                "label": "Main Field",
                "kind": "field",
                "intent": {"confidence": 0.4, "locks": ["LOCK.NO_STEREO_WIDENING"]},
                "notes": [],
            },
        ],
        "metadata": {},
    }


class TestCliSceneTemplatesPreview(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _env(self, repo_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return env

    def test_scene_template_preview_json_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        env = self._env(repo_root)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene_path = temp_path / "scene.json"
            _write_json(scene_path, _sample_scene(stems_dir=stems_dir))

            command = [
                self._python_cmd(),
                "-m",
                "mmo",
                "scene",
                "template",
                "preview",
                "TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER",
                "--scene",
                os.fspath(scene_path),
                "--format",
                "json",
            ]
            first = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                cwd=repo_root,
                env=env,
            )
            second = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                cwd=repo_root,
                env=env,
            )
            self.assertEqual(first.returncode, 0, msg=first.stderr)
            self.assertEqual(second.returncode, 0, msg=second.stderr)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(first.stderr, second.stderr)

            payload = json.loads(first.stdout)
            self.assertEqual(
                payload.get("template_ids"),
                ["TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER"],
            )
            self.assertEqual(payload.get("force"), False)

            objects = payload.get("objects")
            self.assertIsInstance(objects, list)
            if not isinstance(objects, list):
                return
            object_ids = [
                item.get("object_id")
                for item in objects
                if isinstance(item, dict) and isinstance(item.get("object_id"), str)
            ]
            self.assertEqual(object_ids, sorted(object_ids))

            by_id = {
                item.get("object_id"): item
                for item in objects
                if isinstance(item, dict) and isinstance(item.get("object_id"), str)
            }

            vox_preview = by_id["OBJ.A_VOX"]
            vox_changes = vox_preview.get("changes")
            self.assertIsInstance(vox_changes, list)
            if not isinstance(vox_changes, list):
                return
            vox_change_paths = [
                item.get("path")
                for item in vox_changes
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            ]
            self.assertEqual(vox_change_paths, sorted(vox_change_paths))
            self.assertIn("intent.confidence", vox_change_paths)
            self.assertIn("intent.locks", vox_change_paths)

            locked_preview = by_id["OBJ.Z_LOCKED"]
            self.assertEqual(locked_preview.get("hard_locked"), True)
            self.assertEqual(locked_preview.get("changes"), [])
            self.assertEqual(locked_preview.get("skipped"), [])

    def test_scene_template_preview_text_snapshot(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        env = self._env(repo_root)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene_payload = _sample_scene(stems_dir=stems_dir)
            scene_payload["objects"] = [scene_payload["objects"][1]]
            scene_payload["beds"] = []
            scene_path = temp_path / "scene.json"
            _write_json(scene_path, scene_payload)

            result = subprocess.run(
                [
                    self._python_cmd(),
                    "-m",
                    "mmo",
                    "scene",
                    "template",
                    "preview",
                    "TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER",
                    "--scene",
                    os.fspath(scene_path),
                    "--format",
                    "text",
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=repo_root,
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(result.stderr, "")

            expected_output = (
                "\n".join(
                    [
                        "templates: TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER",
                        "force: false",
                        "scene: hard_locked=false changes=0 skipped=0",
                        "  paths: changes=[(none)] skipped=[(none)]",
                        "objects:",
                        "- OBJ.A_VOX: label=Lead Vocal hard_locked=false changes=6 skipped=3",
                        "  paths: changes=[intent.confidence, intent.depth, intent.locks, intent.loudness_bias, intent.position.azimuth_deg, +1 more] skipped=[intent.depth, intent.loudness_bias, intent.width]",
                        "beds:",
                        "- (none)",
                    ]
                )
                + "\n"
            )
            self.assertEqual(result.stdout, expected_output)


if __name__ == "__main__":
    unittest.main()
