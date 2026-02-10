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
        "scene_id": "SCENE.CLI.EDIT.TEST",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "analyze",
        },
        "objects": [
            {
                "object_id": "OBJ.LEAD",
                "stem_id": "STEM.LEAD",
                "label": "Lead",
                "channel_count": 1,
                "intent": {"confidence": 0.5, "locks": []},
                "notes": [],
            }
        ],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {"diffuse": 0.5, "confidence": 0.0, "locks": []},
                "notes": [],
            }
        ],
        "metadata": {},
    }


class TestCliSceneEdit(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _env(self, repo_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return env

    def test_scene_locks_add_writes_expected_scene(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene_path = temp_path / "scene.json"
            out_path = temp_path / "scene.locked.json"
            _write_json(scene_path, _sample_scene(stems_dir=stems_dir))

            result = subprocess.run(
                [
                    self._python_cmd(),
                    "-m",
                    "mmo",
                    "scene",
                    "locks",
                    "add",
                    "--scene",
                    os.fspath(scene_path),
                    "--scope",
                    "object",
                    "--id",
                    "OBJ.LEAD",
                    "--lock",
                    "LOCK.PRESERVE_DYNAMICS",
                    "--out",
                    os.fspath(out_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=repo_root,
                env=self._env(repo_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            objects = payload.get("objects")
            self.assertIsInstance(objects, list)
            if not isinstance(objects, list) or not objects:
                return
            self.assertEqual(
                objects[0].get("intent", {}).get("locks"),
                ["LOCK.PRESERVE_DYNAMICS"],
            )

    def test_scene_intent_set_writes_expected_scene(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene_path = temp_path / "scene.json"
            out_path = temp_path / "scene.intent.json"
            _write_json(scene_path, _sample_scene(stems_dir=stems_dir))

            result = subprocess.run(
                [
                    self._python_cmd(),
                    "-m",
                    "mmo",
                    "scene",
                    "intent",
                    "set",
                    "--scene",
                    os.fspath(scene_path),
                    "--scope",
                    "object",
                    "--id",
                    "OBJ.LEAD",
                    "--key",
                    "width",
                    "--value",
                    "0.25",
                    "--out",
                    os.fspath(out_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=repo_root,
                env=self._env(repo_root),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(out_path.exists())

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            objects = payload.get("objects")
            self.assertIsInstance(objects, list)
            if not isinstance(objects, list) or not objects:
                return
            width = objects[0].get("intent", {}).get("width")
            self.assertIsInstance(width, float)
            if isinstance(width, float):
                self.assertEqual(width, 0.25)

    def test_scene_intent_set_invalid_value_exits_nonzero_with_deterministic_payload(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene_path = temp_path / "scene.json"
            out_path = temp_path / "scene.invalid.json"
            _write_json(scene_path, _sample_scene(stems_dir=stems_dir))

            command = [
                self._python_cmd(),
                "-m",
                "mmo",
                "scene",
                "intent",
                "set",
                "--scene",
                os.fspath(scene_path),
                "--scope",
                "object",
                "--id",
                "OBJ.LEAD",
                "--key",
                "azimuth_deg",
                "--value",
                "999",
                "--out",
                os.fspath(out_path),
            ]
            first = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                cwd=repo_root,
                env=self._env(repo_root),
            )
            second = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                cwd=repo_root,
                env=self._env(repo_root),
            )

            self.assertNotEqual(first.returncode, 0)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(first.stderr, second.stderr)
            self.assertFalse(out_path.exists())

            payload = json.loads(first.stderr)
            self.assertFalse(payload.get("ok"))
            issues = payload.get("issues")
            self.assertIsInstance(issues, list)
            if not isinstance(issues, list) or not issues:
                return
            issue = issues[0]
            self.assertEqual(
                issue.get("issue_id"),
                "ISSUE.VALIDATION.SCENE_INTENT_PARAM_OUT_OF_RANGE",
            )
            target = issue.get("target")
            self.assertIsInstance(target, dict)
            if isinstance(target, dict):
                self.assertEqual(target.get("scope"), "object")
                self.assertEqual(target.get("object_id"), "OBJ.LEAD")
                self.assertEqual(target.get("param_id"), "INTENT.POSITION.AZIMUTH_DEG")


if __name__ == "__main__":
    unittest.main()
