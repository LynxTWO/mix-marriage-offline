"""Tests for ``mmo project save`` and ``mmo project load``."""

import contextlib
import io
import json
import unittest
import wave
from pathlib import Path

from mmo.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = _REPO_ROOT / "sandbox_tmp" / "test_cli_project_load_save"


def _write_tiny_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _init_project(base: Path) -> Path:
    stems_root = base / "stems_root"
    _write_tiny_wav(stems_root / "stems" / "kick.wav")
    _write_tiny_wav(stems_root / "stems" / "snare.wav")

    project_dir = base / "project"
    exit_code, _, stderr = _run_main(
        [
            "project",
            "init",
            "--stems-root",
            str(stems_root),
            "--out-dir",
            str(project_dir),
        ]
    )
    assert exit_code == 0, f"project init failed: {stderr}"
    return project_dir


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil

    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestCliProjectLoadSave(unittest.TestCase):
    def test_project_save_writes_session_payload(self) -> None:
        base = _SANDBOX / "save"
        project_dir = _init_project(base)

        history_path = project_dir / "renders" / "event_log.jsonl"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(
            json.dumps({"event_id": "EVENT.SAVE", "kind": "info"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        receipt_path = project_dir / "renders" / "render_preflight.json"
        receipt_path.write_text(
            json.dumps(
                {"schema_version": "0.1.0", "checks": [], "issues": []},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        exit_code, stdout, stderr = _run_main(
            ["project", "save", str(project_dir), "--format", "json"]
        )
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["history_count"], 1)
        self.assertEqual(payload["receipt_count"], 1)
        self.assertEqual(
            payload["session_path"],
            (project_dir / "project_session.json").resolve().as_posix(),
        )

        session_payload = json.loads((project_dir / "project_session.json").read_text(encoding="utf-8"))
        self.assertEqual(session_payload["schema_version"], "0.1.0")
        self.assertIsInstance(session_payload["scene"], dict)
        self.assertEqual(session_payload["history"], [{"event_id": "EVENT.SAVE", "kind": "info"}])
        self.assertEqual(
            session_payload["receipts"],
            [
                {
                    "path": "renders/render_preflight.json",
                    "payload": {
                        "schema_version": "0.1.0",
                        "checks": [],
                        "issues": [],
                    },
                }
            ],
        )

    def test_project_save_shared_json_redacts_machine_local_paths(self) -> None:
        base = _SANDBOX / "save_shared"
        project_dir = _init_project(base)
        session_path = base / "shared_logs" / "project_session.json"

        history_path = project_dir / "renders" / "event_log.jsonl"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(
            json.dumps({"event_id": "EVENT.SAVE", "kind": "info"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        exit_code, stdout, stderr = _run_main(
            [
                "project",
                "save",
                str(project_dir),
                "--session",
                str(session_path),
                "--format",
                "json-shared",
            ]
        )
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["paths_redacted"])
        self.assertNotIn("project_dir", payload)
        self.assertEqual(payload["scene_path"], "drafts/scene.draft.json")
        self.assertEqual(payload["session_path"], "project_session.json")
        self.assertEqual(payload["written"], ["project_session.json"])
        self.assertNotIn(project_dir.resolve().as_posix(), stdout)
        self.assertNotIn(session_path.resolve().as_posix(), stdout)

    def test_project_save_defaults_to_shared_json(self) -> None:
        base = _SANDBOX / "save_default_shared"
        project_dir = _init_project(base)

        exit_code, stdout, stderr = _run_main(["project", "save", str(project_dir)])
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(stdout)

        self.assertTrue(payload["paths_redacted"])
        self.assertNotIn("project_dir", payload)
        self.assertEqual(payload["scene_path"], "drafts/scene.draft.json")
        self.assertEqual(payload["session_path"], "project_session.json")
        self.assertEqual(payload["written"], ["project_session.json"])

    def test_project_load_restores_artifacts(self) -> None:
        base = _SANDBOX / "load"
        project_dir = _init_project(base)

        scene_path = project_dir / "drafts" / "scene.draft.json"
        original_scene = json.loads(scene_path.read_text(encoding="utf-8"))

        history_path = project_dir / "renders" / "event_log.jsonl"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(
            json.dumps({"event_id": "EVENT.ORIGINAL", "kind": "info"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        original_history = [{"event_id": "EVENT.ORIGINAL", "kind": "info"}]

        receipt_path = project_dir / "renders" / "render_preflight.json"
        receipt_payload = {"schema_version": "0.1.0", "checks": [], "issues": []}
        receipt_path.write_text(
            json.dumps(receipt_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        exit_code, _, stderr = _run_main(["project", "save", str(project_dir), "--format", "json"])
        self.assertEqual(exit_code, 0, msg=stderr)

        scene_path.write_text(
            json.dumps({"schema_version": "0.1.0", "scene_id": "SCENE.MUTATED"}, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        history_path.write_text(
            json.dumps({"event_id": "EVENT.MUTATED", "kind": "warn"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt_path.write_text(
            json.dumps({"schema_version": "0.1.0", "checks": [{"check_id": "MUTATED"}], "issues": []}, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

        exit_code, _, stderr = _run_main(["project", "load", str(project_dir)])
        self.assertEqual(exit_code, 1)
        self.assertIn("use --force", stderr)

        exit_code, stdout, stderr = _run_main(
            ["project", "load", str(project_dir), "--force", "--format", "json"]
        )
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertIn("drafts/scene.draft.json", payload["written"])
        self.assertIn("renders/event_log.jsonl", payload["written"])
        self.assertIn("renders/render_preflight.json", payload["written"])

        restored_scene = json.loads(scene_path.read_text(encoding="utf-8"))
        self.assertEqual(restored_scene, original_scene)

        restored_history_lines = [
            json.loads(line)
            for line in history_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(restored_history_lines, original_history)
        self.assertEqual(json.loads(receipt_path.read_text(encoding="utf-8")), receipt_payload)

    def test_project_load_defaults_to_shared_json(self) -> None:
        base = _SANDBOX / "load_default_shared"
        project_dir = _init_project(base)

        history_path = project_dir / "renders" / "event_log.jsonl"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(
            json.dumps({"event_id": "EVENT.ORIGINAL", "kind": "info"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt_path = project_dir / "renders" / "render_preflight.json"
        receipt_payload = {"schema_version": "0.1.0", "checks": [], "issues": []}
        receipt_path.write_text(
            json.dumps(receipt_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        exit_code, _, stderr = _run_main(["project", "save", str(project_dir), "--format", "json"])
        self.assertEqual(exit_code, 0, msg=stderr)

        exit_code, stdout, stderr = _run_main(["project", "load", str(project_dir), "--force"])
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(stdout)

        self.assertTrue(payload["paths_redacted"])
        self.assertNotIn("project_dir", payload)
        self.assertEqual(payload["session_path"], "project_session.json")
        self.assertIn("drafts/scene.draft.json", payload["written"])
        self.assertIn("renders/event_log.jsonl", payload["written"])
        self.assertIn("renders/render_preflight.json", payload["written"])

    def test_project_load_shared_json_redacts_machine_local_paths(self) -> None:
        base = _SANDBOX / "load_shared"
        project_dir = _init_project(base)

        history_path = project_dir / "renders" / "event_log.jsonl"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(
            json.dumps({"event_id": "EVENT.ORIGINAL", "kind": "info"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        receipt_path = project_dir / "renders" / "render_preflight.json"
        receipt_payload = {"schema_version": "0.1.0", "checks": [], "issues": []}
        receipt_path.write_text(
            json.dumps(receipt_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        exit_code, _, stderr = _run_main(["project", "save", str(project_dir)])
        self.assertEqual(exit_code, 0, msg=stderr)

        exit_code, stdout, stderr = _run_main(
            ["project", "load", str(project_dir), "--force", "--format", "json-shared"]
        )
        self.assertEqual(exit_code, 0, msg=stderr)
        payload = json.loads(stdout)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["paths_redacted"])
        self.assertNotIn("project_dir", payload)
        self.assertEqual(payload["session_path"], "project_session.json")
        self.assertIn("drafts/scene.draft.json", payload["written"])
        self.assertIn("renders/event_log.jsonl", payload["written"])
        self.assertIn("renders/render_preflight.json", payload["written"])
        self.assertNotIn(project_dir.resolve().as_posix(), stdout)


if __name__ == "__main__":
    unittest.main()
