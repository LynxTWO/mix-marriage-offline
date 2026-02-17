import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


class TestValidateMilestones(unittest.TestCase):
    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _validator_script(self) -> Path:
        return self._repo_root() / "tools" / "validate_milestones.py"

    def test_validate_milestones_current_repo_is_ok(self) -> None:
        result = subprocess.run(
            [self._python_cmd(), os.fspath(self._validator_script())],
            check=False,
            capture_output=True,
            text=True,
            cwd=self._repo_root(),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("errors"), [])

        milestone_ids = payload.get("milestone_ids")
        self.assertIsInstance(milestone_ids, list)
        if not isinstance(milestone_ids, list):
            return
        self.assertEqual(milestone_ids, sorted(milestone_ids))
        self.assertIn("MVP.CLI", milestone_ids)
        self.assertIn("MVP.GUI", milestone_ids)
        self.assertIn("DSP.PHASE1", milestone_ids)

    def test_validate_milestones_error_order_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            docs_dir = temp_root / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "STATUS.md").write_text("# Status\n", encoding="utf-8")

            milestones_payload = {
                "milestones": [
                    {
                        "id": "MVP.GUI",
                        "state": "doing",
                        "links": ["docs/missing.md#later"],
                    },
                    {
                        "id": "MVP.GUI",
                        "state": "planned",
                        "links": ["docs/STATUS.md"],
                    },
                    {
                        "state": "done",
                        "links": ["docs/STATUS.md#mvp-cli"],
                    },
                    {
                        "id": "DSP.PHASE1",
                        "state": "blocked",
                        "links": [],
                    },
                ]
            }
            (docs_dir / "milestones.yaml").write_text(
                yaml.safe_dump(milestones_payload, sort_keys=False),
                encoding="utf-8",
            )

            command = [
                self._python_cmd(),
                os.fspath(self._validator_script()),
                "--repo-root",
                os.fspath(temp_root),
            ]
            first = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                cwd=self._repo_root(),
            )
            second = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                cwd=self._repo_root(),
            )

        self.assertNotEqual(first.returncode, 0, msg=first.stdout)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, second.stderr)

        payload = json.loads(first.stdout)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(
            payload.get("errors"),
            [
                "Duplicate milestone id: MVP.GUI.",
                "milestones[0] ('MVP.GUI').links[0] references missing docs file: docs/missing.md",
                "milestones[0] ('MVP.GUI').state must be one of [blocked, done, in_progress, planned]; got 'doing'.",
                "milestones[1] ('MVP.GUI').links[0] must include a '#<section>' anchor.",
                "milestones[2].id must be a non-empty string.",
                "milestones[3] ('DSP.PHASE1').links must be a non-empty list.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
