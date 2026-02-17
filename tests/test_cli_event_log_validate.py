"""Tests for ``mmo event-log validate``."""

import contextlib
import io
import json
import os
import unittest
from pathlib import Path

from mmo.cli import main
from mmo.core.event_log import new_event_id, write_event_log

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = (
    _REPO_ROOT / "sandbox_tmp" / "test_cli_event_log_validate" / str(os.getpid())
)


def _run_main(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _valid_event(*, code: str, what: str) -> dict:
    event = {
        "kind": "info",
        "scope": "render",
        "what": what,
        "why": "Deterministic render event.",
        "where": ["renders/render_plan.json"],
        "evidence": {
            "codes": [code],
            "paths": ["renders/render_plan.json"],
        },
    }
    event["event_id"] = new_event_id(event)
    return event


def _write_valid_event_log(path: Path) -> None:
    events = [
        _valid_event(code="RENDER.RUN.STARTED", what="render-run started"),
        _valid_event(code="RENDER.RUN.COMPLETED", what="render-run completed"),
    ]
    write_event_log(events, path, force=True)


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    import shutil
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestEventLogValidateHappyPath(unittest.TestCase):

    def test_valid_event_log_returns_zero_and_empty_issues(self) -> None:
        base = _SANDBOX / "happy"
        base.mkdir(parents=True, exist_ok=True)
        in_path = base / "event_log.jsonl"
        _write_valid_event_log(in_path)

        exit_code, stdout, stderr = _run_main([
            "event-log", "validate",
            "--in", str(in_path),
        ])
        self.assertEqual(exit_code, 0, msg=stderr)
        result = json.loads(stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["in_path"], in_path.resolve().as_posix())
        self.assertNotIn("\\", stdout)


class TestEventLogValidateErrors(unittest.TestCase):

    def test_invalid_event_log_reports_line_issue_and_message(self) -> None:
        base = _SANDBOX / "errors"
        base.mkdir(parents=True, exist_ok=True)
        in_path = base / "event_log.jsonl"
        in_path.write_text(
            (
                '{"kind":"info","scope":"render"\n'
                '["not-an-object"]\n'
                '{"event_id":"EVT.aaaaaaaaaaaa","kind":"info","scope":"render","what":"ok","why":"ok","where":["bad\\\\path"],"evidence":{"codes":["X"],"paths":["bad\\\\path"]}}\n'
            ),
            encoding="utf-8",
        )

        exit_code_a, stdout_a, stderr_a = _run_main([
            "event-log", "validate",
            "--in", str(in_path),
        ])
        exit_code_b, stdout_b, _ = _run_main([
            "event-log", "validate",
            "--in", str(in_path),
        ])
        self.assertEqual(exit_code_a, 2, msg=stderr_a)
        self.assertEqual(exit_code_b, 2)
        self.assertEqual(stdout_a, stdout_b)

        result = json.loads(stdout_a)
        issues = result.get("issues")
        self.assertIsInstance(issues, list)
        if not isinstance(issues, list):
            return
        self.assertGreaterEqual(len(issues), 3)
        self.assertEqual(
            issues,
            sorted(
                issues,
                key=lambda issue: (
                    issue["line"],
                    issue["issue_id"],
                    issue["message"],
                ),
            ),
        )

        self.assertEqual(issues[0]["line"], 1)
        self.assertEqual(issues[0]["issue_id"], "ISSUE.EVENT_LOG.INVALID_JSON")
        self.assertEqual(issues[1]["line"], 2)
        self.assertEqual(issues[1]["issue_id"], "ISSUE.EVENT_LOG.NOT_OBJECT")
        self.assertTrue(
            any(
                issue["line"] == 3
                and issue["issue_id"] == "ISSUE.EVENT_LOG.SCHEMA_INVALID"
                for issue in issues
            )
        )


class TestEventLogValidateOverwriteRules(unittest.TestCase):

    def test_out_requires_force_and_force_overwrites(self) -> None:
        base = _SANDBOX / "overwrite"
        base.mkdir(parents=True, exist_ok=True)
        in_path = base / "event_log.jsonl"
        out_path = base / "validation.json"
        _write_valid_event_log(in_path)
        out_path.write_text('{"seed":true}\n', encoding="utf-8")
        original = out_path.read_bytes()

        refused_exit, _, refused_stderr = _run_main([
            "event-log", "validate",
            "--in", str(in_path),
            "--out", str(out_path),
        ])
        self.assertEqual(refused_exit, 1)
        self.assertIn("--force", refused_stderr)
        self.assertEqual(out_path.read_bytes(), original)

        allowed_exit, allowed_stdout, allowed_stderr = _run_main([
            "event-log", "validate",
            "--in", str(in_path),
            "--out", str(out_path),
            "--force",
        ])
        self.assertEqual(allowed_exit, 0, msg=allowed_stderr)
        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.read_text(encoding="utf-8"), allowed_stdout)


if __name__ == "__main__":
    unittest.main()
