import json
import json
import math
import shutil
import struct
import unittest
import wave
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.render_qa import build_render_qa_payload, render_qa_has_error_issues

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _schema_validator(schema_name: str) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


def _write_stereo_pcm16_wav(
    path: Path,
    *,
    sample_rate_hz: int = 48000,
    duration_s: float = 1.0,
    frequency_hz: float = 220.0,
    left_scale: float = 0.35,
    right_scale: float = 0.35,
) -> None:
    frames = max(1, int(sample_rate_hz * duration_s))
    samples: list[int] = []
    for frame_index in range(frames):
        base = math.sin(2.0 * math.pi * frequency_hz * frame_index / sample_rate_hz)
        left = int(max(-1.0, min(1.0, base * left_scale)) * 32767.0)
        right = int(max(-1.0, min(1.0, base * right_scale)) * 32767.0)
        samples.extend([left, right])
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class TestRenderQABuilder(unittest.TestCase):
    def test_build_payload_is_deterministic_and_schema_valid(self) -> None:
        validator = _schema_validator("render_qa.schema.json")
        temp_root = (REPO_ROOT / "sandbox_tmp" / "test_render_qa").resolve()
        temp_root.mkdir(parents=True, exist_ok=True)
        temp_path = temp_root / "deterministic"
        shutil.rmtree(temp_path, ignore_errors=True)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            input_path = temp_path / "input.wav"
            output_path = temp_path / "output.wav"
            _write_stereo_pcm16_wav(input_path)
            _write_stereo_pcm16_wav(output_path)

            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": "scene.json",
                "options": {"dry_run": False},
            }
            plan_payload = {
                "schema_version": "0.1.0",
                "plan_id": "PLAN.render.qa.00000001",
                "jobs": [{"job_id": "JOB.001"}],
                "targets": ["TARGET.STEREO.2_0"],
            }
            report_payload = {
                "schema_version": "0.1.0",
                "request": {
                    "target_layout_id": "LAYOUT.2_0",
                    "scene_path": "scene.json",
                },
                "jobs": [
                    {
                        "job_id": "JOB.001",
                        "status": "completed",
                        "output_files": [
                            {"file_path": output_path.resolve().as_posix(), "format": "wav"},
                        ],
                    }
                ],
                "policies_applied": {},
                "qa_gates": {"status": "not_run", "gates": []},
            }
            job_rows = [
                {
                    "job_id": "JOB.001",
                    "input_paths": [input_path],
                    "output_paths": [output_path],
                }
            ]

            payload_a = build_render_qa_payload(
                request_payload=request_payload,
                plan_payload=plan_payload,
                report_payload=report_payload,
                job_rows=job_rows,
                plugin_chain_used=False,
            )
            payload_b = build_render_qa_payload(
                request_payload=request_payload,
                plan_payload=plan_payload,
                report_payload=report_payload,
                job_rows=job_rows,
                plugin_chain_used=False,
            )
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)

        self.assertEqual(payload_a, payload_b)
        validator.validate(payload_a)
        self.assertEqual(payload_a["jobs"][0]["comparisons"], [])
        output_metrics = payload_a["jobs"][0]["outputs"][0]["metrics"]
        self.assertIn("true_peak_dbtp", output_metrics)
        self.assertIn("short_term_lufs_p50", output_metrics)
        output_spectral = payload_a["jobs"][0]["outputs"][0]["spectral"]
        self.assertIn("section_tilt_db_per_oct", output_spectral)
        self.assertFalse(render_qa_has_error_issues(payload_a))

    def test_polarity_risk_produces_error_issue(self) -> None:
        temp_root = (REPO_ROOT / "sandbox_tmp" / "test_render_qa").resolve()
        temp_root.mkdir(parents=True, exist_ok=True)
        temp_path = temp_root / "polarity"
        shutil.rmtree(temp_path, ignore_errors=True)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            input_path = temp_path / "input.wav"
            output_path = temp_path / "output.wav"
            _write_stereo_pcm16_wav(input_path, left_scale=0.35, right_scale=0.35)
            _write_stereo_pcm16_wav(output_path, left_scale=0.35, right_scale=-0.35)

            payload = build_render_qa_payload(
                request_payload={
                    "schema_version": "0.1.0",
                    "target_layout_id": "LAYOUT.2_0",
                    "scene_path": "scene.json",
                    "options": {"dry_run": False},
                },
                plan_payload={
                    "schema_version": "0.1.0",
                    "plan_id": "PLAN.render.qa.00000002",
                    "jobs": [{"job_id": "JOB.001"}],
                    "targets": ["TARGET.STEREO.2_0"],
                },
                report_payload={
                    "schema_version": "0.1.0",
                    "request": {
                        "target_layout_id": "LAYOUT.2_0",
                        "scene_path": "scene.json",
                    },
                    "jobs": [
                        {
                            "job_id": "JOB.001",
                            "status": "completed",
                            "output_files": [
                                {
                                    "file_path": output_path.resolve().as_posix(),
                                    "format": "wav",
                                },
                            ],
                        }
                    ],
                    "policies_applied": {},
                    "qa_gates": {"status": "not_run", "gates": []},
                },
                job_rows=[
                    {
                        "job_id": "JOB.001",
                        "input_paths": [input_path],
                        "output_paths": [output_path],
                    }
                ],
                plugin_chain_used=False,
            )
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)

        issue_ids = [
            issue.get("issue_id")
            for issue in payload.get("issues", [])
            if isinstance(issue, dict)
        ]
        self.assertIn("ISSUE.RENDER.QA.POLARITY_RISK", issue_ids)
        self.assertTrue(render_qa_has_error_issues(payload))

    def test_true_peak_excessive_produces_error_issue(self) -> None:
        temp_root = (REPO_ROOT / "sandbox_tmp" / "test_render_qa").resolve()
        temp_root.mkdir(parents=True, exist_ok=True)
        temp_path = temp_root / "true_peak"
        shutil.rmtree(temp_path, ignore_errors=True)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            input_path = temp_path / "input.wav"
            output_path = temp_path / "output.wav"
            _write_stereo_pcm16_wav(
                input_path,
                left_scale=0.35,
                right_scale=0.35,
                frequency_hz=220.0,
            )
            _write_stereo_pcm16_wav(
                output_path,
                left_scale=1.0,
                right_scale=1.0,
                frequency_hz=19000.0,
            )

            payload = build_render_qa_payload(
                request_payload={
                    "schema_version": "0.1.0",
                    "target_layout_id": "LAYOUT.2_0",
                    "scene_path": "scene.json",
                    "options": {"dry_run": False},
                },
                plan_payload={
                    "schema_version": "0.1.0",
                    "plan_id": "PLAN.render.qa.00000003",
                    "jobs": [{"job_id": "JOB.001"}],
                    "targets": ["TARGET.STEREO.2_0"],
                },
                report_payload={
                    "schema_version": "0.1.0",
                    "request": {
                        "target_layout_id": "LAYOUT.2_0",
                        "scene_path": "scene.json",
                    },
                    "jobs": [
                        {
                            "job_id": "JOB.001",
                            "status": "completed",
                            "output_files": [
                                {
                                    "file_path": output_path.resolve().as_posix(),
                                    "format": "wav",
                                },
                            ],
                        }
                    ],
                    "policies_applied": {},
                    "qa_gates": {"status": "not_run", "gates": []},
                },
                job_rows=[
                    {
                        "job_id": "JOB.001",
                        "input_paths": [input_path],
                        "output_paths": [output_path],
                    }
                ],
                plugin_chain_used=False,
            )
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)

        issue_ids = [
            issue.get("issue_id")
            for issue in payload.get("issues", [])
            if isinstance(issue, dict) and issue.get("severity") == "error"
        ]
        self.assertIn("ISSUE.RENDER.QA.TRUE_PEAK_EXCESSIVE", issue_ids)
        self.assertTrue(render_qa_has_error_issues(payload))


if __name__ == "__main__":
    unittest.main()
