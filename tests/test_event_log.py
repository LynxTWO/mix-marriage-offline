import json
import shutil
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main
from mmo.core.event_log import new_event_id, write_event_log

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SANDBOX = _REPO_ROOT / "sandbox_tmp" / "test_event_log"


def _schema_validator(schema_name: str) -> jsonschema.Draft202012Validator:
    schema_path = _REPO_ROOT / "schemas" / schema_name

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


def _demo_events() -> list[dict]:
    rows: list[dict] = [
        {
            "kind": "info",
            "scope": "stems",
            "what": "Indexed stem inputs",
            "why": "Prepared deterministic source map for routing.",
            "where": ["stems/stems_index.json", "STEMSET.DEMO.A"],
            "evidence": {
                "codes": ["STEMS.INDEXED"],
                "ids": ["STEMSET.DEMO.A"],
                "paths": ["stems/stems_index.json"],
                "metrics": [{"name": "stem_count", "value": 4}],
                "notes": ["Indexed by rel_path sort."],
            },
        },
        {
            "kind": "action",
            "scope": "render",
            "what": "Planned stereo dry-run",
            "why": "Validated render graph without writing audio.",
            "where": ["render/render_plan.json", "TARGET.STEREO.2_0"],
            "confidence": 0.99,
            "evidence": {
                "codes": ["RENDER.PLAN.CREATED"],
                "ids": ["TARGET.STEREO.2_0"],
                "paths": ["render/render_plan.json"],
                "metrics": [{"name": "job_count", "value": 1}],
                "notes": ["No wall-clock timestamps were captured."],
            },
        },
        {
            "kind": "warn",
            "scope": "qa",
            "what": "Translation checks skipped",
            "why": "Reference audio was not provided.",
            "where": ["qa/translation_summary.json", "TRANS.MONO.COLLAPSE"],
            "confidence": 0.67,
            "evidence": {
                "codes": ["QA.TRANSLATION.SKIPPED"],
                "ids": ["TRANS.MONO.COLLAPSE"],
                "paths": ["qa/translation_summary.json"],
                "metrics": [{"name": "profiles_checked", "value": 0}],
                "notes": ["Demo fixture intentionally omits reference audio."],
            },
        },
    ]

    events: list[dict] = []
    for row in rows:
        event = dict(row)
        event["event_id"] = new_event_id(event)
        events.append(event)
    return events


def _read_jsonl(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def setUpModule() -> None:
    _SANDBOX.mkdir(parents=True, exist_ok=True)


def tearDownModule() -> None:
    if _SANDBOX.exists():
        shutil.rmtree(_SANDBOX, ignore_errors=True)


class TestEventLog(unittest.TestCase):
    def test_cli_demo_writes_schema_valid_jsonl(self) -> None:
        validator = _schema_validator("event.schema.json")
        test_root = _SANDBOX / "cli_demo"
        _reset_dir(test_root)
        out_path = test_root / "event_log.jsonl"
        stdout_capture = StringIO()
        with redirect_stdout(stdout_capture):
            exit_code = main(
                [
                    "event-log",
                    "demo",
                    "--out",
                    str(out_path),
                ]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout_capture.getvalue())
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("event_count"), 3)
        self.assertEqual(payload.get("out_path"), out_path.resolve().as_posix())
        self.assertNotIn("\\", payload.get("out_path", ""))

        events = _read_jsonl(out_path)
        self.assertEqual(len(events), 3)
        for event in events:
            validator.validate(event)
            self.assertTrue(str(event.get("event_id", "")).startswith("EVT."))

    def test_write_event_log_deterministic_bytes_across_runs(self) -> None:
        test_root = _SANDBOX / "deterministic"
        _reset_dir(test_root)
        out_a = test_root / "event_log_a.jsonl"
        out_b = test_root / "event_log_b.jsonl"

        events = _demo_events()
        write_event_log(events, out_a, force=False)
        write_event_log(list(reversed(events)), out_b, force=False)

        self.assertEqual(out_a.read_bytes(), out_b.read_bytes())
        self.assertTrue(out_a.read_bytes().endswith(b"\n"))

    def test_write_event_log_overwrite_rules(self) -> None:
        test_root = _SANDBOX / "overwrite"
        _reset_dir(test_root)
        out_path = test_root / "event_log.jsonl"
        events = _demo_events()

        write_event_log(events, out_path, force=False)

        with self.assertRaises(ValueError) as raised:
            write_event_log(events, out_path, force=False)
        self.assertIn("--force", str(raised.exception))

        write_event_log(events, out_path, force=True)
        self.assertTrue(out_path.exists())


if __name__ == "__main__":
    unittest.main()
