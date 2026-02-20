import json
import shutil
import struct
import unittest
import wave
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.render_execute import build_render_execute_payload

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


def _write_constant_pcm16_wav(
    path: Path,
    *,
    channels: int,
    sample_value: int,
    sample_rate_hz: int = 48000,
    frames: int = 256,
) -> None:
    values = [sample_value] * (frames * channels)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(values)}h", *values))


class TestRenderExecuteMeters(unittest.TestCase):
    def test_build_payload_includes_deterministic_wav_meters(self) -> None:
        validator = _schema_validator("render_execute.schema.json")
        temp_root = (REPO_ROOT / "sandbox_tmp" / "test_render_execute").resolve()
        temp_root.mkdir(parents=True, exist_ok=True)
        temp_path = temp_root / "case"
        shutil.rmtree(temp_path, ignore_errors=True)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            input_path = temp_path / "input.wav"
            output_path = temp_path / "output.wav"
            _write_constant_pcm16_wav(
                input_path,
                channels=2,
                sample_value=16384,  # 0.5 -> -6.0206 dBFS
                frames=48000,
            )
            _write_constant_pcm16_wav(
                output_path,
                channels=2,
                sample_value=8192,  # 0.25 -> -12.0412 dBFS
                frames=48000,
            )

            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": "scene.json",
            }
            plan_payload = {
                "schema_version": "0.1.0",
                "plan_id": "PLAN.render.execute.meters",
                "jobs": [{"job_id": "JOB.001"}],
                "targets": ["TARGET.STEREO.2_0"],
            }
            job_rows = [
                {
                    "job_id": "JOB.001",
                    "input_paths": [input_path],
                    "output_paths": [output_path],
                    "ffmpeg_version": "ffmpeg test",
                    "ffmpeg_commands": [
                        {"args": ["ffmpeg", "-version"], "determinism_flags": []},
                    ],
                }
            ]

            payload_a = build_render_execute_payload(
                request_payload=request_payload,
                plan_payload=plan_payload,
                job_rows=job_rows,
            )
            payload_b = build_render_execute_payload(
                request_payload=request_payload,
                plan_payload=plan_payload,
                job_rows=job_rows,
            )
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)

        self.assertEqual(payload_a, payload_b)
        validator.validate(payload_a)

        job = payload_a["jobs"][0]
        input_meters = job["inputs"][0]["meters"]
        output_meters = job["outputs"][0]["meters"]

        self.assertEqual(input_meters["peak_dbfs"], -6.0206)
        self.assertEqual(input_meters["rms_dbfs"], -6.0206)
        self.assertIn("integrated_lufs", input_meters)
        self.assertTrue(
            input_meters["integrated_lufs"] is None
            or isinstance(input_meters["integrated_lufs"], (int, float))
        )

        self.assertEqual(output_meters["peak_dbfs"], -12.0412)
        self.assertEqual(output_meters["rms_dbfs"], -12.0412)
        self.assertIn("integrated_lufs", output_meters)
        self.assertTrue(
            output_meters["integrated_lufs"] is None
            or isinstance(output_meters["integrated_lufs"], (int, float))
        )


if __name__ == "__main__":
    unittest.main()
