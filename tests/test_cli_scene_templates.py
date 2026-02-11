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
        "scene_id": "SCENE.CLI.TEMPLATES.TEST",
        "source": {
            "stems_dir": stems_dir.resolve().as_posix(),
            "created_from": "analyze",
        },
        "objects": [
            {
                "object_id": "OBJ.GTR",
                "stem_id": "STEM.GTR",
                "label": "Guitar",
                "channel_count": 1,
                "intent": {
                    "width": 0.1,
                    "depth": 0.1,
                    "loudness_bias": "back",
                    "confidence": 0.2,
                    "locks": [],
                },
                "notes": [],
            },
            {
                "object_id": "OBJ.LEAD",
                "stem_id": "STEM.LEAD",
                "label": "Lead Vocal",
                "channel_count": 1,
                "intent": {
                    "width": 0.9,
                    "confidence": 0.5,
                    "locks": ["LOCK.NO_EXTRA_BASS"],
                },
                "notes": [],
            },
        ],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {"diffuse": 0.4, "confidence": 0.0, "locks": []},
                "notes": [],
            }
        ],
        "metadata": {},
    }


class TestCliSceneTemplates(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _env(self, repo_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        return env

    def test_scene_template_list_and_show(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        base_command = [self._python_cmd(), "-m", "mmo", "scene", "template"]
        env = self._env(repo_root)

        list_json = subprocess.run(
            [*base_command, "list", "--format", "json"],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=env,
        )
        self.assertEqual(list_json.returncode, 0, msg=list_json.stderr)
        payload = json.loads(list_json.stdout)
        template_ids = [
            item.get("template_id")
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("template_id"), str)
        ]
        self.assertEqual(template_ids, sorted(template_ids))
        self.assertEqual(
            template_ids,
            [
                "TEMPLATE.SCENE.LIVE.YOU_ARE_THERE",
                "TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER",
                "TEMPLATE.SCENE.SURROUND.FRONT_STAGE_CLEAR_REAR_FIELD",
            ],
        )

        list_text = subprocess.run(
            [*base_command, "list", "--format", "text"],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=env,
        )
        self.assertEqual(list_text.returncode, 0, msg=list_text.stderr)
        self.assertIn("TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER", list_text.stdout)
        self.assertIn("Band: wide, vocal center", list_text.stdout)

        show_json = subprocess.run(
            [
                *base_command,
                "show",
                "TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=env,
        )
        self.assertEqual(show_json.returncode, 0, msg=show_json.stderr)
        shown_payload = json.loads(show_json.stdout)
        self.assertEqual(len(shown_payload), 1)
        self.assertEqual(
            shown_payload[0].get("template_id"),
            "TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER",
        )

        show_text = subprocess.run(
            [
                *base_command,
                "show",
                "TEMPLATE.SCENE.LIVE.YOU_ARE_THERE",
                "TEMPLATE.SCENE.SURROUND.FRONT_STAGE_CLEAR_REAR_FIELD",
                "--format",
                "text",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=env,
        )
        self.assertEqual(show_text.returncode, 0, msg=show_text.stderr)
        self.assertIn("TEMPLATE.SCENE.LIVE.YOU_ARE_THERE", show_text.stdout)
        self.assertIn("TEMPLATE.SCENE.SURROUND.FRONT_STAGE_CLEAR_REAR_FIELD", show_text.stdout)

    def test_scene_template_apply_missing_only_and_output_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        env = self._env(repo_root)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene_path = temp_path / "scene.json"
            out_a = temp_path / "scene.out_a.json"
            out_b = temp_path / "scene.out_b.json"
            _write_json(scene_path, _sample_scene(stems_dir=stems_dir))

            command = [
                self._python_cmd(),
                "-m",
                "mmo",
                "scene",
                "template",
                "apply",
                "TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER",
                "--scene",
                os.fspath(scene_path),
                "--out",
            ]
            first = subprocess.run(
                [*command, os.fspath(out_a)],
                check=False,
                capture_output=True,
                text=True,
                cwd=repo_root,
                env=env,
            )
            second = subprocess.run(
                [*command, os.fspath(out_b)],
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
            self.assertEqual(
                out_a.read_text(encoding="utf-8"),
                out_b.read_text(encoding="utf-8"),
            )

            payload = json.loads(out_a.read_text(encoding="utf-8"))
            objects = payload.get("objects")
            self.assertIsInstance(objects, list)
            if not isinstance(objects, list):
                return
            self.assertEqual([item.get("object_id") for item in objects], ["OBJ.GTR", "OBJ.LEAD"])
            by_id = {
                item.get("object_id"): item
                for item in objects
                if isinstance(item, dict) and isinstance(item.get("object_id"), str)
            }

            lead_intent = by_id["OBJ.LEAD"]["intent"]
            self.assertEqual(lead_intent.get("width"), 0.9)
            self.assertEqual(lead_intent.get("depth"), 0.2)
            self.assertEqual(lead_intent.get("loudness_bias"), "forward")
            self.assertEqual(lead_intent.get("position"), {"azimuth_deg": 0.0})
            self.assertEqual(lead_intent.get("locks"), ["LOCK.NO_EXTRA_BASS"])

            gtr_intent = by_id["OBJ.GTR"]["intent"]
            self.assertEqual(gtr_intent.get("width"), 0.1)
            self.assertEqual(gtr_intent.get("depth"), 0.1)
            self.assertEqual(gtr_intent.get("loudness_bias"), "back")
            self.assertEqual(gtr_intent.get("locks"), [])

    def test_scene_template_apply_force_still_skips_scene_hard_lock(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        env = self._env(repo_root)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)
            scene_path = temp_path / "scene.json"
            out_path = temp_path / "scene.out.json"
            scene_payload = _sample_scene(stems_dir=stems_dir)
            scene_payload["intent"] = {
                "confidence": 0.2,
                "locks": ["LOCK.NO_STEREO_WIDENING"],
                "width": 0.25,
            }
            _write_json(scene_path, scene_payload)

            result = subprocess.run(
                [
                    self._python_cmd(),
                    "-m",
                    "mmo",
                    "scene",
                    "template",
                    "apply",
                    "TEMPLATE.SCENE.SURROUND.FRONT_STAGE_CLEAR_REAR_FIELD",
                    "--scene",
                    os.fspath(scene_path),
                    "--out",
                    os.fspath(out_path),
                    "--force",
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=repo_root,
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            payload = json.loads(out_path.read_text(encoding="utf-8"))
            objects = payload.get("objects")
            self.assertIsInstance(objects, list)
            if not isinstance(objects, list):
                return
            by_id = {
                item.get("object_id"): item
                for item in objects
                if isinstance(item, dict) and isinstance(item.get("object_id"), str)
            }
            self.assertEqual(by_id["OBJ.GTR"]["intent"].get("depth"), 0.1)
            self.assertEqual(by_id["OBJ.GTR"]["intent"].get("loudness_bias"), "back")
            self.assertEqual(by_id["OBJ.LEAD"]["intent"].get("depth"), None)
            self.assertEqual(by_id["OBJ.LEAD"]["intent"].get("loudness_bias"), None)
            self.assertEqual(by_id["OBJ.LEAD"]["intent"].get("locks"), ["LOCK.NO_EXTRA_BASS"])

            beds = payload.get("beds")
            self.assertIsInstance(beds, list)
            if not isinstance(beds, list) or not beds:
                return
            self.assertEqual(beds[0].get("intent", {}).get("diffuse"), 0.4)
            scene_intent = payload.get("intent")
            self.assertIsInstance(scene_intent, dict)
            if isinstance(scene_intent, dict):
                self.assertEqual(scene_intent.get("locks"), ["LOCK.NO_STEREO_WIDENING"])

    def test_scene_template_show_unknown_id_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command = [
            self._python_cmd(),
            "-m",
            "mmo",
            "scene",
            "template",
            "show",
            "TEMPLATE.SCENE.DOES_NOT_EXIST",
            "--format",
            "json",
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
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, second.stderr)
        self.assertIn("Unknown template_id", first.stderr)


if __name__ == "__main__":
    unittest.main()
