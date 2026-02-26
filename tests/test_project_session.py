import json
import tempfile
import unittest
from pathlib import Path

from mmo.core.config import (
    load_project_session,
    load_project_session_into_project,
    save_project_session,
)


class TestProjectSession(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _read_jsonl(self, path: Path) -> list[dict]:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [json.loads(line) for line in lines]

    def test_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "project"
            scene_path = project_dir / "drafts" / "scene.draft.json"
            history_path = project_dir / "renders" / "event_log.jsonl"
            receipt_path = project_dir / "renders" / "render_preflight.json"

            scene_payload = {
                "schema_version": "0.1.0",
                "scene_id": "SCENE.DRAFT.TEST",
            }
            history_payload = [
                {"event_id": "EVENT.1", "kind": "info"},
                {"event_id": "EVENT.2", "kind": "warn"},
            ]
            receipt_payload = {
                "schema_version": "0.1.0",
                "checks": [],
                "issues": [],
            }

            self._write_json(scene_path, scene_payload)
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history_path.write_text(
                "".join(json.dumps(item, sort_keys=True) + "\n" for item in history_payload),
                encoding="utf-8",
            )
            self._write_json(receipt_path, receipt_payload)

            save_result = save_project_session(project_dir, session_path=None, force=False)
            self.assertTrue(save_result["ok"])
            session_path = project_dir / "project_session.json"
            self.assertEqual(save_result["session_path"], session_path.resolve().as_posix())

            session_payload = load_project_session(session_path)
            self.assertEqual(session_payload["scene"], scene_payload)
            self.assertEqual(session_payload["history"], history_payload)
            self.assertEqual(
                session_payload["receipts"],
                [{"path": "renders/render_preflight.json", "payload": receipt_payload}],
            )

            self._write_json(
                scene_path,
                {
                    "schema_version": "0.1.0",
                    "scene_id": "SCENE.DRAFT.MUTATED",
                },
            )
            history_path.write_text(
                json.dumps({"event_id": "EVENT.MUTATED", "kind": "info"}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self._write_json(
                receipt_path,
                {
                    "schema_version": "0.1.0",
                    "checks": [{"check_id": "MUTATED"}],
                    "issues": [],
                },
            )

            with self.assertRaisesRegex(ValueError, "use --force"):
                load_project_session_into_project(
                    project_dir,
                    session_path=session_path,
                    force=False,
                )

            load_result = load_project_session_into_project(
                project_dir,
                session_path=session_path,
                force=True,
            )
            self.assertTrue(load_result["ok"])
            self.assertIn("drafts/scene.draft.json", load_result["written"])
            self.assertIn("renders/event_log.jsonl", load_result["written"])
            self.assertIn("renders/render_preflight.json", load_result["written"])

            self.assertEqual(json.loads(scene_path.read_text(encoding="utf-8")), scene_payload)
            self.assertEqual(self._read_jsonl(history_path), history_payload)
            self.assertEqual(json.loads(receipt_path.read_text(encoding="utf-8")), receipt_payload)


if __name__ == "__main__":
    unittest.main()
