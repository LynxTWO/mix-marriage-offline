import json
import math
import os
import struct
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import wave

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.io import sha256_file

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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )


def _minimal_scene(stems_dir: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.RENDER.RUN.TEST",
        "source": {
            "stems_dir": stems_dir,
            "created_from": "analyze",
        },
        "objects": [],
        "beds": [
            {
                "bed_id": "BED.FIELD.001",
                "label": "Field",
                "kind": "field",
                "intent": {
                    "diffuse": 0.5,
                    "confidence": 0.0,
                    "locks": [],
                },
                "notes": [],
            }
        ],
        "metadata": {},
    }


def _minimal_request(scene_path: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "target_layout_id": "LAYOUT.2_0",
        "scene_path": scene_path,
    }


def _request_with_options(scene_path: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "target_layout_id": "LAYOUT.5_1",
        "scene_path": scene_path,
        "options": {
            "output_formats": ["wav", "flac"],
            "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            "gates_policy_id": "POLICY.GATES.CORE_V0",
        },
    }


def _routing_plan() -> dict:
    return {
        "schema_version": "0.1.0",
        "source_layout_id": "LAYOUT.5_1",
        "target_layout_id": "LAYOUT.2_0",
        "routes": [
            {
                "stem_id": "STEM.001",
                "stem_channels": 2,
                "target_channels": 2,
                "mapping": [
                    {"src_ch": 0, "dst_ch": 0, "gain_db": 0.0},
                    {"src_ch": 1, "dst_ch": 1, "gain_db": 0.0},
                ],
                "notes": [],
            }
        ],
    }


def _run_render_run(
    temp_path: Path,
    *,
    request_payload: dict | None = None,
    with_routing_plan: bool = False,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str, Path, Path]:
    stems_dir = temp_path / "stems"
    stems_dir.mkdir(exist_ok=True)

    scene_path = temp_path / "scene.json"
    request_path = temp_path / "render_request.json"
    plan_out = temp_path / "render_plan.json"
    report_out = temp_path / "render_report.json"

    scene_posix = scene_path.resolve().as_posix()
    _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
    _write_json(
        request_path,
        request_payload if request_payload is not None else _minimal_request(scene_posix),
    )

    args = [
        "render-run",
        "--request", str(request_path),
        "--scene", str(scene_path),
        "--plan-out", str(plan_out),
        "--report-out", str(report_out),
    ]
    if with_routing_plan:
        routing_plan_path = temp_path / "routing_plan.json"
        _write_json(routing_plan_path, _routing_plan())
        args.extend(["--routing-plan", str(routing_plan_path)])
    if extra_args:
        args.extend(extra_args)

    stdout_capture = StringIO()
    stderr_capture = StringIO()
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        exit_code = main(args)
    return exit_code, stdout_capture.getvalue(), stderr_capture.getvalue(), plan_out, report_out


def _read_jsonl(path: Path) -> list[dict]:
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [json.loads(line) for line in lines]


def _write_pcm16_wav(
    path: Path,
    *,
    channels: int,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.05,
) -> None:
    frames = max(1, int(sample_rate_hz * duration_s))
    samples: list[int] = []
    for frame_index in range(frames):
        value = int(
            0.35
            * 32767.0
            * math.sin(2.0 * math.pi * 330.0 * frame_index / sample_rate_hz)
        )
        for _ in range(channels):
            samples.append(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _pcm16_abs_peak(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        sample_width = handle.getsampwidth()
        if sample_width != 2:
            raise ValueError(f"Expected 16-bit WAV, got sample width {sample_width}")
        frame_count = handle.getnframes()
        frames = handle.readframes(frame_count)
    if not frames:
        return 0
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    return max(abs(value) for value in samples)


def _encode_flac(source_wav: Path, output_flac: Path, ffmpeg_cmd: list[str]) -> None:
    output_flac.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        list(ffmpeg_cmd)
        + [
            "-v",
            "error",
            "-y",
            "-i",
            os.fspath(source_wav),
            "-c:a",
            "flac",
            os.fspath(output_flac),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _write_pcm16_two_tone_wav(
    path: Path,
    *,
    channels: int,
    sample_rate_hz: int = 48000,
    duration_s: float = 1.0,
    low_hz: float = 160.0,
    high_hz: float = 6000.0,
) -> None:
    frames = max(1, int(sample_rate_hz * duration_s))
    samples: list[int] = []
    for frame_index in range(frames):
        low_value = math.sin(2.0 * math.pi * low_hz * frame_index / sample_rate_hz)
        high_value = math.sin(2.0 * math.pi * high_hz * frame_index / sample_rate_hz)
        mixed = int(0.2 * 32767.0 * low_value + 0.2 * 32767.0 * high_value)
        for _ in range(channels):
            samples.append(mixed)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _pcm16_band_energy(path: Path, *, band_low_hz: float, band_high_hz: float) -> float:
    import numpy as np

    with wave.open(str(path), "rb") as handle:
        sample_width = handle.getsampwidth()
        if sample_width != 2:
            raise ValueError(f"Expected 16-bit WAV, got sample width {sample_width}")
        channel_count = handle.getnchannels()
        sample_rate_hz = handle.getframerate()
        frame_count = handle.getnframes()
        frames = handle.readframes(frame_count)
    if not frames:
        return 0.0
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
    if channel_count > 1:
        mono = np.mean(samples.reshape(-1, channel_count), axis=1, dtype=np.float64)
    else:
        mono = samples
    window = np.hanning(int(mono.shape[0])).astype(np.float64)
    windowed = mono * window
    spectrum = np.fft.rfft(windowed)
    freqs_hz = np.fft.rfftfreq(int(mono.shape[0]), d=1.0 / float(sample_rate_hz))
    mask = (freqs_hz >= float(band_low_hz)) & (freqs_hz < float(band_high_hz))
    if not bool(np.any(mask)):
        return 0.0
    magnitudes = np.abs(spectrum[mask])
    return float(np.sum(np.square(magnitudes), dtype=np.float64))


class TestRenderRunHappyPath(unittest.TestCase):
    def test_produces_schema_valid_plan_and_report(self) -> None:
        plan_validator = _schema_validator("render_plan.schema.json")
        report_validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exit_code, stdout, stderr, plan_out, report_out = _run_render_run(temp_path)

            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertTrue(plan_out.exists())
            self.assertTrue(report_out.exists())

            plan = json.loads(plan_out.read_text(encoding="utf-8"))
            report = json.loads(report_out.read_text(encoding="utf-8"))
            plan_validator.validate(plan)
            report_validator.validate(report)

    def test_plan_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exit_code, _, stderr, plan_out, _ = _run_render_run(temp_path)

            self.assertEqual(exit_code, 0, msg=stderr)
            plan = json.loads(plan_out.read_text(encoding="utf-8"))
            self.assertIn("plan_id", plan)
            self.assertIn("request", plan)
            self.assertEqual(plan["request"]["target_layout_id"], "LAYOUT.2_0")
            self.assertEqual(len(plan["jobs"]), 1)
            self.assertEqual(plan["jobs"][0]["job_id"], "JOB.001")

    def test_report_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exit_code, _, stderr, _, report_out = _run_render_run(temp_path)

            self.assertEqual(exit_code, 0, msg=stderr)
            report = json.loads(report_out.read_text(encoding="utf-8"))
            self.assertEqual(report["schema_version"], "0.1.0")
            self.assertEqual(len(report["jobs"]), 1)
            self.assertEqual(report["jobs"][0]["status"], "skipped")
            self.assertIn("reason: dry_run", report["jobs"][0]["notes"])
            self.assertEqual(report["qa_gates"]["status"], "not_run")

    def test_with_routing_plan(self) -> None:
        plan_validator = _schema_validator("render_plan.schema.json")
        report_validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()
            scene_posix = scene_path.resolve().as_posix()
            exit_code, _, stderr, plan_out, report_out = _run_render_run(
                temp_path,
                request_payload=_request_with_options(scene_posix),
                with_routing_plan=True,
            )

            self.assertEqual(exit_code, 0, msg=stderr)
            plan = json.loads(plan_out.read_text(encoding="utf-8"))
            report = json.loads(report_out.read_text(encoding="utf-8"))
            plan_validator.validate(plan)
            report_validator.validate(report)

            self.assertEqual(
                plan["resolved"]["downmix_policy_id"],
                "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            )


class TestRenderRunAudioExecution(unittest.TestCase):
    def test_executes_stereo_source_when_dry_run_false(self) -> None:
        report_validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "mix.wav"
            _write_pcm16_wav(source_path, channels=2)

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "options": {
                    "dry_run": False,
                },
            }
            exit_code, _, stderr, _, report_out = _run_render_run(
                temp_path,
                request_payload=request_payload,
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            report = json.loads(report_out.read_text(encoding="utf-8"))
            report_validator.validate(report)

            job = report["jobs"][0]
            self.assertEqual(job["status"], "completed")
            self.assertIn("reason: rendered", job.get("notes", []))
            output_files = job.get("output_files", [])
            self.assertEqual(len(output_files), 1)
            output_file = output_files[0]
            self.assertEqual(output_file.get("format"), "wav")
            self.assertEqual(output_file.get("channel_count"), 2)
            self.assertEqual(output_file.get("sample_rate_hz"), 48000)

            rendered_path = Path(str(output_file["file_path"]))
            self.assertTrue(rendered_path.is_file())
            self.assertEqual(output_file.get("sha256"), sha256_file(rendered_path))

    def test_plugin_chain_gain_v0_applies_gain_and_is_deterministic(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "mix.wav"
            _write_pcm16_wav(source_path, channels=2, duration_s=1.0)
            source_peak = _pcm16_abs_peak(source_path)

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "options": {
                    "dry_run": False,
                    "plugin_chain": [
                        {
                            "plugin_id": "gain_v0",
                            "params": {
                                "gain_db": -6.0,
                            },
                        }
                    ],
                },
            }
            event_log_out = temp_path / "render_events.jsonl"
            exit_a, _, stderr_a, _, report_out_a = _run_render_run(
                temp_path,
                request_payload=request_payload,
                extra_args=[
                    "--event-log-out", str(event_log_out),
                ],
            )
            self.assertEqual(exit_a, 0, msg=stderr_a)

            report_a = json.loads(report_out_a.read_text(encoding="utf-8"))
            rendered_path_a = Path(report_a["jobs"][0]["output_files"][0]["file_path"])
            wav_bytes_a = rendered_path_a.read_bytes()
            event_bytes_a = event_log_out.read_bytes()

            rendered_peak = _pcm16_abs_peak(rendered_path_a)
            self.assertGreater(source_peak, rendered_peak)
            gain_ratio = rendered_peak / source_peak if source_peak else 0.0
            self.assertAlmostEqual(gain_ratio, math.pow(10.0, -6.0 / 20.0), delta=0.02)

            events = _read_jsonl(event_log_out)
            plugin_events = [
                event
                for event in events
                if isinstance(event, dict)
                and isinstance(event.get("evidence"), dict)
                and any(
                    str(code).startswith("RENDER.RUN.PLUGIN.")
                    for code in event.get("evidence", {}).get("codes", [])
                )
            ]
            self.assertEqual(len(plugin_events), 3)
            for event in plugin_events:
                self.assertTrue(event.get("what"))
                self.assertTrue(event.get("why"))
                self.assertTrue(event.get("where"))
                self.assertIn("confidence", event)
                self.assertIsNone(event.get("confidence"))

            exit_b, _, stderr_b, _, report_out_b = _run_render_run(
                temp_path,
                request_payload=request_payload,
                extra_args=[
                    "--force",
                    "--event-log-out", str(event_log_out),
                    "--event-log-force",
                ],
            )
            self.assertEqual(exit_b, 0, msg=stderr_b)

            report_b = json.loads(report_out_b.read_text(encoding="utf-8"))
            rendered_path_b = Path(report_b["jobs"][0]["output_files"][0]["file_path"])
            wav_bytes_b = rendered_path_b.read_bytes()
            event_bytes_b = event_log_out.read_bytes()

            self.assertEqual(wav_bytes_a, wav_bytes_b)
            self.assertEqual(event_bytes_a, event_bytes_b)

    def test_plugin_chain_tilt_eq_v0_is_deterministic_across_runs(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "mix.wav"
            _write_pcm16_wav(source_path, channels=2, duration_s=1.0)

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "options": {
                    "dry_run": False,
                    "plugin_chain": [
                        {
                            "plugin_id": "tilt_eq_v0",
                            "params": {
                                "tilt_db": 4.0,
                                "pivot_hz": 1000.0,
                                "macro_mix": 100.0,
                                "bypass": False,
                            },
                        }
                    ],
                },
            }
            event_log_out = temp_path / "render_events.jsonl"
            exit_a, _, stderr_a, _, report_out_a = _run_render_run(
                temp_path,
                request_payload=request_payload,
                extra_args=[
                    "--event-log-out", str(event_log_out),
                ],
            )
            self.assertEqual(exit_a, 0, msg=stderr_a)

            report_a = json.loads(report_out_a.read_text(encoding="utf-8"))
            rendered_path_a = Path(report_a["jobs"][0]["output_files"][0]["file_path"])
            wav_bytes_a = rendered_path_a.read_bytes()
            event_bytes_a = event_log_out.read_bytes()

            events = _read_jsonl(event_log_out)
            stage_event = next(
                (
                    event
                    for event in events
                    if isinstance(event, dict)
                    and isinstance(event.get("evidence"), dict)
                    and "RENDER.RUN.PLUGIN.STAGE_APPLIED"
                    in event.get("evidence", {}).get("codes", [])
                    and "tilt_eq_v0" in event.get("evidence", {}).get("ids", [])
                ),
                None,
            )
            self.assertIsNotNone(stage_event)
            metrics = {
                str(item.get("name")): item.get("value")
                for item in stage_event.get("evidence", {}).get("metrics", [])
                if isinstance(item, dict)
            }
            self.assertAlmostEqual(float(metrics.get("tilt_db", -999.0)), 4.0, delta=1e-8)
            self.assertAlmostEqual(float(metrics.get("pivot_hz", -999.0)), 1000.0, delta=1e-8)
            self.assertAlmostEqual(float(metrics.get("macro_mix", -1.0)), 1.0, delta=1e-8)

            exit_b, _, stderr_b, _, report_out_b = _run_render_run(
                temp_path,
                request_payload=request_payload,
                extra_args=[
                    "--force",
                    "--event-log-out", str(event_log_out),
                    "--event-log-force",
                ],
            )
            self.assertEqual(exit_b, 0, msg=stderr_b)

            report_b = json.loads(report_out_b.read_text(encoding="utf-8"))
            rendered_path_b = Path(report_b["jobs"][0]["output_files"][0]["file_path"])
            wav_bytes_b = rendered_path_b.read_bytes()
            event_bytes_b = event_log_out.read_bytes()

            self.assertEqual(wav_bytes_a, wav_bytes_b)
            self.assertEqual(event_bytes_a, event_bytes_b)

    def test_plugin_chain_tilt_eq_v0_tilt_direction_changes_band_energy(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "mix.wav"
            _write_pcm16_two_tone_wav(source_path, channels=2, duration_s=1.0)

            scene_posix = (temp_path / "scene.json").resolve().as_posix()

            def _render_tilt(tilt_db: float) -> Path:
                request_payload = {
                    "schema_version": "0.1.0",
                    "target_layout_id": "LAYOUT.2_0",
                    "scene_path": scene_posix,
                    "options": {
                        "dry_run": False,
                        "plugin_chain": [
                            {
                                "plugin_id": "tilt_eq_v0",
                                "params": {
                                    "tilt_db": tilt_db,
                                    "pivot_hz": 1000.0,
                                    "macro_mix": 100.0,
                                    "bypass": False,
                                },
                            }
                        ],
                    },
                }
                exit_code, _, stderr, _, report_out = _run_render_run(
                    temp_path,
                    request_payload=request_payload,
                    extra_args=[
                        "--force",
                    ],
                )
                self.assertEqual(exit_code, 0, msg=stderr)
                report = json.loads(report_out.read_text(encoding="utf-8"))
                return Path(report["jobs"][0]["output_files"][0]["file_path"])

            tilt_up_path = _render_tilt(6.0)
            up_hf = _pcm16_band_energy(tilt_up_path, band_low_hz=4000.0, band_high_hz=12000.0)
            up_lf = _pcm16_band_energy(tilt_up_path, band_low_hz=60.0, band_high_hz=400.0)

            tilt_down_path = _render_tilt(-6.0)
            down_hf = _pcm16_band_energy(tilt_down_path, band_low_hz=4000.0, band_high_hz=12000.0)
            down_lf = _pcm16_band_energy(tilt_down_path, band_low_hz=60.0, band_high_hz=400.0)

            self.assertGreater(up_hf, down_hf)
            self.assertGreater(down_lf, up_lf)

    def test_plugin_chain_precision_mode_note_reflects_quality_flag(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "mix.wav"
            _write_pcm16_wav(source_path, channels=2, duration_s=1.0)
            scene_posix = (temp_path / "scene.json").resolve().as_posix()

            def _run_with_precision(flag_value: bool) -> list[str]:
                request_payload = {
                    "schema_version": "0.1.0",
                    "target_layout_id": "LAYOUT.2_0",
                    "scene_path": scene_posix,
                    "options": {
                        "dry_run": False,
                        "max_theoretical_quality": flag_value,
                        "plugin_chain": [
                            {
                                "plugin_id": "gain_v0",
                                "params": {
                                    "gain_db": -3.0,
                                },
                            }
                        ],
                    },
                }
                exit_code, _, stderr, _, report_out = _run_render_run(
                    temp_path,
                    request_payload=request_payload,
                    extra_args=["--force"],
                )
                self.assertEqual(exit_code, 0, msg=stderr)
                report = json.loads(report_out.read_text(encoding="utf-8"))
                notes = report["jobs"][0].get("notes", [])
                self.assertIsInstance(notes, list)
                return [str(item) for item in notes]

            notes_float64 = _run_with_precision(True)
            self.assertIn("plugin_chain_precision_mode: float64", notes_float64)

            notes_float32 = _run_with_precision(False)
            self.assertIn("plugin_chain_precision_mode: float32", notes_float32)

    def test_plugin_chain_gain_v0_honors_bypass_and_macro_mix_linear_blend(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "mix.wav"
            _write_pcm16_wav(source_path, channels=2, duration_s=1.0)
            source_bytes = source_path.read_bytes()
            source_peak = _pcm16_abs_peak(source_path)

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            event_log_out = temp_path / "render_events.jsonl"

            def _render_with_params(params: dict[str, object]) -> tuple[dict, Path, dict[str, object]]:
                request_payload = {
                    "schema_version": "0.1.0",
                    "target_layout_id": "LAYOUT.2_0",
                    "scene_path": scene_posix,
                    "options": {
                        "dry_run": False,
                        "plugin_chain": [
                            {
                                "plugin_id": "gain_v0",
                                "params": params,
                            }
                        ],
                    },
                }
                exit_code, _, stderr, _, report_out = _run_render_run(
                    temp_path,
                    request_payload=request_payload,
                    extra_args=[
                        "--force",
                        "--event-log-out", str(event_log_out),
                        "--event-log-force",
                    ],
                )
                self.assertEqual(exit_code, 0, msg=stderr)
                report = json.loads(report_out.read_text(encoding="utf-8"))
                rendered_path = Path(report["jobs"][0]["output_files"][0]["file_path"])
                events = _read_jsonl(event_log_out)
                stage_event = next(
                    (
                        event
                        for event in events
                        if isinstance(event, dict)
                        and isinstance(event.get("evidence"), dict)
                        and "RENDER.RUN.PLUGIN.STAGE_APPLIED"
                        in event.get("evidence", {}).get("codes", [])
                    ),
                    None,
                )
                self.assertIsNotNone(stage_event)
                metrics: dict[str, object] = {
                    str(item.get("name")): item.get("value")
                    for item in stage_event.get("evidence", {}).get("metrics", [])
                    if isinstance(item, dict)
                }
                return report, rendered_path, metrics

            report_bypass, bypass_path, bypass_metrics = _render_with_params(
                {"gain_db": -18.0, "macro_mix": 1.0, "bypass": True}
            )
            self.assertEqual(source_bytes, bypass_path.read_bytes())
            self.assertEqual(sha256_file(source_path), sha256_file(bypass_path))
            self.assertIn(
                "macro_mix applied as linear blend.",
                report_bypass["jobs"][0].get("notes", []),
            )
            self.assertAlmostEqual(float(bypass_metrics.get("bypass", -1.0)), 1.0, delta=1e-8)
            self.assertAlmostEqual(float(bypass_metrics.get("macro_mix", -1.0)), 1.0, delta=1e-8)
            self.assertAlmostEqual(
                float(bypass_metrics.get("macro_mix_input", -1.0)),
                1.0,
                delta=1e-8,
            )

            _, mix0_path, mix0_metrics = _render_with_params(
                {"gain_db": -6.0, "macro_mix": 0.0, "bypass": False}
            )
            self.assertEqual(source_bytes, mix0_path.read_bytes())
            self.assertAlmostEqual(float(mix0_metrics.get("bypass", -1.0)), 0.0, delta=1e-8)
            self.assertAlmostEqual(float(mix0_metrics.get("macro_mix", -1.0)), 0.0, delta=1e-8)

            _, mix05_path, mix05_metrics = _render_with_params(
                {"gain_db": -6.0, "macro_mix": 0.5, "bypass": False}
            )
            mix05_peak = _pcm16_abs_peak(mix05_path)
            mix05_ratio = mix05_peak / source_peak if source_peak else 0.0
            expected_mix05_ratio = 0.5 + (0.5 * math.pow(10.0, -6.0 / 20.0))
            self.assertAlmostEqual(mix05_ratio, expected_mix05_ratio, delta=0.02)
            self.assertAlmostEqual(float(mix05_metrics.get("bypass", -1.0)), 0.0, delta=1e-8)
            self.assertAlmostEqual(float(mix05_metrics.get("macro_mix", -1.0)), 0.5, delta=1e-8)

            _, mix1_path, mix1_metrics = _render_with_params(
                {"gain_db": -6.0, "macro_mix": 1.0, "bypass": False}
            )
            mix1_peak = _pcm16_abs_peak(mix1_path)
            mix1_ratio = mix1_peak / source_peak if source_peak else 0.0
            self.assertAlmostEqual(mix1_ratio, math.pow(10.0, -6.0 / 20.0), delta=0.02)
            self.assertAlmostEqual(float(mix1_metrics.get("bypass", -1.0)), 0.0, delta=1e-8)
            self.assertAlmostEqual(float(mix1_metrics.get("macro_mix", -1.0)), 1.0, delta=1e-8)
            self.assertGreater(mix05_peak, mix1_peak)
            self.assertLess(mix05_peak, source_peak)

    def test_plugin_chain_gain_v0_accepts_flac_source_and_is_deterministic(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

        ffmpeg_cmd = resolve_ffmpeg_cmd()
        if ffmpeg_cmd is None:
            self.skipTest("ffmpeg not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_wav = temp_path / "source.wav"
            source_flac = stems_dir / "mix.flac"
            _write_pcm16_wav(source_wav, channels=2, duration_s=1.0)
            _encode_flac(source_wav, source_flac, list(ffmpeg_cmd))

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "options": {
                    "dry_run": False,
                    "plugin_chain": [
                        {
                            "plugin_id": "gain_v0",
                            "params": {
                                "gain_db": -6.0,
                            },
                        }
                    ],
                },
            }
            event_log_out = temp_path / "render_events.jsonl"
            exit_a, _, stderr_a, _, report_out_a = _run_render_run(
                temp_path,
                request_payload=request_payload,
                extra_args=[
                    "--event-log-out", str(event_log_out),
                ],
            )
            self.assertEqual(exit_a, 0, msg=stderr_a)

            report_a = json.loads(report_out_a.read_text(encoding="utf-8"))
            rendered_path_a = Path(report_a["jobs"][0]["output_files"][0]["file_path"])
            wav_bytes_a = rendered_path_a.read_bytes()
            event_bytes_a = event_log_out.read_bytes()

            events = _read_jsonl(event_log_out)
            plugin_events = [
                event
                for event in events
                if isinstance(event, dict)
                and isinstance(event.get("evidence"), dict)
                and any(
                    str(code).startswith("RENDER.RUN.PLUGIN.")
                    for code in event.get("evidence", {}).get("codes", [])
                )
            ]
            self.assertEqual(len(plugin_events), 3)

            exit_b, _, stderr_b, _, report_out_b = _run_render_run(
                temp_path,
                request_payload=request_payload,
                extra_args=[
                    "--force",
                    "--event-log-out", str(event_log_out),
                    "--event-log-force",
                ],
            )
            self.assertEqual(exit_b, 0, msg=stderr_b)

            report_b = json.loads(report_out_b.read_text(encoding="utf-8"))
            rendered_path_b = Path(report_b["jobs"][0]["output_files"][0]["file_path"])
            wav_bytes_b = rendered_path_b.read_bytes()
            event_bytes_b = event_log_out.read_bytes()

            self.assertEqual(wav_bytes_a, wav_bytes_b)
            self.assertEqual(event_bytes_a, event_bytes_b)

    def test_plugin_chain_clamp_notes_are_recorded_in_report(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "mix.wav"
            _write_pcm16_wav(source_path, channels=2, duration_s=1.0)

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "options": {
                    "dry_run": False,
                    "plugin_chain": [
                        {
                            "plugin_id": "gain_v0",
                            "params": {
                                "gain_db": 99.0,
                                "macro_mix": 200.0,
                            },
                        }
                    ],
                },
            }

            exit_code, _, stderr, _, report_out = _run_render_run(
                temp_path,
                request_payload=request_payload,
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            report = json.loads(report_out.read_text(encoding="utf-8"))
            notes = report["jobs"][0].get("notes", [])
            self.assertTrue(
                any(
                    (
                        "plugin_chain_note: options.plugin_chain[1].params.gain_db "
                        "clamped from 99.0 to 24.0"
                    )
                    in note
                    for note in notes
                )
            )
            self.assertTrue(
                any(
                    (
                        "plugin_chain_note: options.plugin_chain[1].params.macro_mix "
                        "clamped from 200.0 to 100.0"
                    )
                    in note
                    for note in notes
                )
            )

    def test_refuses_multi_target_with_stable_issue_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            _write_pcm16_wav(stems_dir / "mix.wav", channels=2)

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_ids": ["LAYOUT.2_0", "LAYOUT.5_1"],
                "scene_path": scene_posix,
                "options": {
                    "dry_run": False,
                },
            }
            exit_code, _, stderr, _, report_out = _run_render_run(
                temp_path,
                request_payload=request_payload,
            )

            self.assertEqual(exit_code, 1)
            self.assertIn("ISSUE.RENDER.RUN.DOWNMIX_SCOPE_UNSUPPORTED", stderr)
            self.assertFalse(report_out.exists())

    def test_refuses_non_stereo_source_with_stable_issue_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            _write_pcm16_wav(stems_dir / "mix.wav", channels=1)

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "options": {
                    "dry_run": False,
                },
            }
            exit_code, _, stderr, _, report_out = _run_render_run(
                temp_path,
                request_payload=request_payload,
            )

            self.assertEqual(exit_code, 1)
            self.assertIn("ISSUE.RENDER.RUN.SOURCE_LAYOUT_UNSUPPORTED", stderr)
            self.assertFalse(report_out.exists())

    def test_refuses_multiple_sources_with_stable_issue_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            _write_pcm16_wav(stems_dir / "mix_a.wav", channels=2)
            _write_pcm16_wav(stems_dir / "mix_b.wav", channels=2)

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "options": {
                    "dry_run": False,
                },
            }
            exit_code, _, stderr, _, report_out = _run_render_run(
                temp_path,
                request_payload=request_payload,
            )

            self.assertEqual(exit_code, 1)
            self.assertIn("ISSUE.RENDER.RUN.SOURCE_COUNT_UNSUPPORTED", stderr)
            self.assertIn("mix_a.wav", stderr)
            self.assertIn("mix_b.wav", stderr)
            self.assertFalse(report_out.exists())


class TestRenderRunExecuteArtifact(unittest.TestCase):
    def test_execute_artifact_and_wav_are_byte_identical_across_runs(self) -> None:
        if resolve_ffmpeg_cmd() is None:
            self.skipTest("ffmpeg not available")

        execute_validator = _schema_validator("render_execute.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            source_path = stems_dir / "mix.wav"
            _write_pcm16_wav(source_path, channels=2, duration_s=1.0)

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "options": {
                    "dry_run": False,
                },
            }

            execute_a = temp_path / "render_execute_a.json"
            exit_a, _, stderr_a, _, report_out = _run_render_run(
                temp_path,
                request_payload=request_payload,
                extra_args=[
                    "--execute-out", str(execute_a),
                ],
            )
            self.assertEqual(exit_a, 0, msg=stderr_a)
            self.assertTrue(execute_a.is_file())
            execute_payload_a = json.loads(execute_a.read_text(encoding="utf-8"))
            execute_validator.validate(execute_payload_a)

            report_a = json.loads(report_out.read_text(encoding="utf-8"))
            output_path_a = Path(report_a["jobs"][0]["output_files"][0]["file_path"])
            wav_bytes_a = output_path_a.read_bytes()

            execute_b = temp_path / "render_execute_b.json"
            exit_b, _, stderr_b, _, report_out_b = _run_render_run(
                temp_path,
                request_payload=request_payload,
                extra_args=[
                    "--force",
                    "--execute-out", str(execute_b),
                ],
            )
            self.assertEqual(exit_b, 0, msg=stderr_b)
            self.assertTrue(execute_b.is_file())
            execute_payload_b = json.loads(execute_b.read_text(encoding="utf-8"))
            execute_validator.validate(execute_payload_b)

            report_b = json.loads(report_out_b.read_text(encoding="utf-8"))
            output_path_b = Path(report_b["jobs"][0]["output_files"][0]["file_path"])
            wav_bytes_b = output_path_b.read_bytes()

            self.assertEqual(wav_bytes_a, wav_bytes_b)
            self.assertEqual(execute_a.read_bytes(), execute_b.read_bytes())


class TestRenderRunDeterminism(unittest.TestCase):
    def test_byte_identical_plan_and_report_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _request_with_options(scene_posix))

            plan_out_1 = temp_path / "plan1.json"
            report_out_1 = temp_path / "report1.json"
            plan_out_2 = temp_path / "plan2.json"
            report_out_2 = temp_path / "report2.json"

            exit1 = main([
                "render-run",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--plan-out", str(plan_out_1),
                "--report-out", str(report_out_1),
            ])
            exit2 = main([
                "render-run",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--plan-out", str(plan_out_2),
                "--report-out", str(report_out_2),
            ])
            self.assertEqual(exit1, 0)
            self.assertEqual(exit2, 0)

            self.assertEqual(plan_out_1.read_bytes(), plan_out_2.read_bytes())
            self.assertEqual(report_out_1.read_bytes(), report_out_2.read_bytes())

    def test_stdout_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            def _capture_stdout(plan_out: Path, report_out: Path) -> str:
                stdout_buf = StringIO()
                with redirect_stdout(stdout_buf):
                    main([
                        "render-run",
                        "--request", str(request_path),
                        "--scene", str(scene_path),
                        "--plan-out", str(plan_out),
                        "--report-out", str(report_out),
                    ])
                return stdout_buf.getvalue()

            stdout1 = _capture_stdout(
                temp_path / "plan_a.json", temp_path / "report_a.json",
            )
            stdout2 = _capture_stdout(
                temp_path / "plan_b.json", temp_path / "report_b.json",
            )
            # stdout contains resolved paths, which differ per output name;
            # verify structure is valid JSON and has expected keys.
            parsed1 = json.loads(stdout1)
            parsed2 = json.loads(stdout2)
            self.assertEqual(parsed1["plan_id"], parsed2["plan_id"])
            self.assertEqual(parsed1["jobs"], parsed2["jobs"])
            self.assertEqual(parsed1["targets"], parsed2["targets"])


class TestRenderRunPreflight(unittest.TestCase):
    def test_preflight_bytes_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            preflight_a = temp_path / "preflight_a.json"
            preflight_b = temp_path / "preflight_b.json"

            exit_a, _, stderr_a, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--preflight-out", str(preflight_a),
                ],
            )
            exit_b, _, stderr_b, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--preflight-out", str(preflight_b),
                    "--force",
                ],
            )

            self.assertEqual(exit_a, 0, msg=stderr_a)
            self.assertEqual(exit_b, 0, msg=stderr_b)
            self.assertTrue(preflight_a.exists())
            self.assertTrue(preflight_b.exists())
            self.assertEqual(preflight_a.read_bytes(), preflight_b.read_bytes())

    def test_preflight_overwrite_requires_preflight_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            preflight_out = temp_path / "render_preflight.json"
            preflight_out.write_text(
                json.dumps({"existing": True}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            existing_bytes = preflight_out.read_bytes()

            exit_refused, _, stderr_refused, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--preflight-out", str(preflight_out),
                ],
            )
            self.assertEqual(exit_refused, 1)
            self.assertIn("File exists", stderr_refused)
            self.assertIn("--preflight-force", stderr_refused)
            self.assertEqual(existing_bytes, preflight_out.read_bytes())

            exit_allowed, _, stderr_allowed, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--preflight-out", str(preflight_out),
                    "--preflight-force",
                ],
            )
            self.assertEqual(exit_allowed, 0, msg=stderr_allowed)
            self.assertNotEqual(existing_bytes, preflight_out.read_bytes())

    def test_preflight_force_requires_preflight_out(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exit_code, _, stderr, _, _ = _run_render_run(
                temp_path,
                extra_args=["--preflight-force"],
            )
            self.assertEqual(exit_code, 1)
            self.assertIn("--preflight-force requires --preflight-out", stderr)

    def test_preflight_error_issues_exit_two_and_skip_report_and_event_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            preflight_out = temp_path / "render_preflight.json"
            event_log_out = temp_path / "event_log.jsonl"

            fake_preflight_payload = {
                "schema_version": "0.1.0",
                "plan_path": (temp_path / "render_plan.json").resolve().as_posix(),
                "plan_id": "PLAN.render.preflight.abcdef01",
                "checks": [
                    {
                        "job_id": "JOB.001",
                        "input_count": 1,
                        "status": "error",
                        "input_checks": [
                            {
                                "path": "missing/input.wav",
                                "role": "scene",
                                "exists": False,
                                "is_file": False,
                                "ffprobe": {
                                    "status": "skipped",
                                    "reason": "input path does not exist",
                                },
                            }
                        ],
                    }
                ],
                "issues": [
                    {
                        "issue_id": "ISSUE.RENDER.PREFLIGHT.INPUT_MISSING",
                        "severity": "error",
                        "message": "Input path does not exist.",
                        "evidence": {
                            "job_id": "JOB.001",
                            "path": "missing/input.wav",
                            "role": "scene",
                        },
                    }
                ],
            }

            with patch(
                "mmo.core.render_preflight.build_render_preflight_payload",
                return_value=fake_preflight_payload,
            ):
                exit_code, stdout, stderr, plan_out, report_out = _run_render_run(
                    temp_path,
                    extra_args=[
                        "--preflight-out", str(preflight_out),
                        "--event-log-out", str(event_log_out),
                    ],
                )

            self.assertEqual(exit_code, 2, msg=stderr)
            self.assertEqual(stdout, "")
            self.assertTrue(plan_out.exists())
            self.assertTrue(preflight_out.exists())
            self.assertFalse(report_out.exists())
            self.assertFalse(event_log_out.exists())

    def test_preflight_payload_paths_use_forward_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            preflight_out = temp_path / "render_preflight.json"

            exit_code, _, stderr, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--preflight-out", str(preflight_out),
                ],
            )
            self.assertEqual(exit_code, 0, msg=stderr)

            payload = json.loads(preflight_out.read_text(encoding="utf-8"))
            self.assertNotIn("\\", payload.get("plan_path", ""))
            for job_check in payload.get("checks", []):
                if not isinstance(job_check, dict):
                    continue
                for input_check in job_check.get("input_checks", []):
                    if isinstance(input_check, dict):
                        self.assertNotIn("\\", str(input_check.get("path", "")))
            for issue in payload.get("issues", []):
                if not isinstance(issue, dict):
                    continue
                evidence = issue.get("evidence")
                if isinstance(evidence, dict):
                    self.assertNotIn("\\", str(evidence.get("path", "")))


class TestRenderRunEventLog(unittest.TestCase):
    def test_writes_schema_valid_event_log_when_requested(self) -> None:
        event_validator = _schema_validator("event.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_log_out = temp_path / "render_events.jsonl"
            exit_code, _, stderr, plan_out, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_out),
                ],
            )

            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertTrue(event_log_out.exists())

            events = _read_jsonl(event_log_out)
            self.assertEqual(len(events), 4)
            for event in events:
                event_validator.validate(event)
                for where_item in event.get("where", []):
                    self.assertNotIn("\\", where_item)
                evidence = event.get("evidence", {})
                if isinstance(evidence, dict):
                    for path_item in evidence.get("paths", []):
                        self.assertNotIn("\\", path_item)

            events_by_what = {
                str(event.get("what", "")): event
                for event in events
            }
            self.assertIn("render-run started", events_by_what)
            self.assertIn("render plan built", events_by_what)
            self.assertIn("render report built", events_by_what)
            self.assertIn("render-run completed", events_by_what)

            request_posix = (temp_path / "render_request.json").resolve().as_posix()
            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            self.assertEqual(
                events_by_what["render-run started"]["where"],
                [request_posix, scene_posix],
            )

            plan_payload = json.loads(plan_out.read_text(encoding="utf-8"))
            plan_event = events_by_what["render plan built"]
            self.assertEqual(plan_event["where"], [plan_out.resolve().as_posix()])
            plan_evidence = plan_event.get("evidence", {})
            self.assertIn(plan_payload["plan_id"], plan_evidence.get("ids", []))
            for target in sorted(plan_payload.get("targets", [])):
                self.assertIn(target, plan_evidence.get("ids", []))
            metrics = {
                metric.get("name"): metric.get("value")
                for metric in plan_evidence.get("metrics", [])
                if isinstance(metric, dict)
            }
            self.assertEqual(metrics.get("job_count"), len(plan_payload.get("jobs", [])))

            report_event = events_by_what["render report built"]
            report_notes = report_event.get("evidence", {}).get("notes", [])
            self.assertIn("status=skipped", report_notes)
            self.assertIn("reason=dry_run", report_notes)

    def test_event_log_bytes_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_log_a = temp_path / "events_a.jsonl"
            event_log_b = temp_path / "events_b.jsonl"

            exit_a, _, stderr_a, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_a),
                ],
            )
            exit_b, _, stderr_b, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_b),
                    "--force",
                ],
            )

            self.assertEqual(exit_a, 0, msg=stderr_a)
            self.assertEqual(exit_b, 0, msg=stderr_b)
            self.assertEqual(event_log_a.read_bytes(), event_log_b.read_bytes())

    def test_event_log_overwrite_requires_event_log_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_log_out = temp_path / "events.jsonl"

            exit_first, _, stderr_first, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_out),
                ],
            )
            self.assertEqual(exit_first, 0, msg=stderr_first)
            first_bytes = event_log_out.read_bytes()

            exit_refused, _, stderr_refused, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_out),
                    "--force",
                ],
            )
            self.assertEqual(exit_refused, 1)
            self.assertIn("--event-log-force", stderr_refused)
            self.assertEqual(first_bytes, event_log_out.read_bytes())

            exit_allowed, _, stderr_allowed, _, _ = _run_render_run(
                temp_path,
                extra_args=[
                    "--event-log-out", str(event_log_out),
                    "--force",
                    "--event-log-force",
                ],
            )
            self.assertEqual(exit_allowed, 0, msg=stderr_allowed)
            self.assertTrue(event_log_out.exists())

    def test_stdout_unchanged_when_event_log_flag_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exit_code, stdout, stderr, _, _ = _run_render_run(temp_path)
            self.assertEqual(exit_code, 0, msg=stderr)

            self.assertNotIn("render-run started", stdout)
            self.assertNotIn("render plan built", stdout)
            self.assertNotIn("render report built", stdout)
            self.assertNotIn("render-run completed", stdout)
            parsed = json.loads(stdout)
            self.assertIn("plan_id", parsed)


class TestRenderRunOverwrite(unittest.TestCase):
    def test_refuses_overwrite_plan_out_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            plan_out = temp_path / "render_plan.json"
            report_out = temp_path / "render_report.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            plan_out.write_text("{}", encoding="utf-8")

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-run",
                    "--request", str(request_path),
                    "--scene", str(scene_path),
                    "--plan-out", str(plan_out),
                    "--report-out", str(report_out),
                ])
            self.assertEqual(exit_code, 1)
            self.assertIn("File exists", stderr_capture.getvalue())
            self.assertIn("--force", stderr_capture.getvalue())

    def test_refuses_overwrite_report_out_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            plan_out = temp_path / "plan.json"
            report_out = temp_path / "report.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            report_out.write_text("{}", encoding="utf-8")

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-run",
                    "--request", str(request_path),
                    "--scene", str(scene_path),
                    "--plan-out", str(plan_out),
                    "--report-out", str(report_out),
                ])
            self.assertEqual(exit_code, 1)
            self.assertIn("File exists", stderr_capture.getvalue())

    def test_allows_overwrite_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            plan_out = temp_path / "plan.json"
            report_out = temp_path / "report.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _minimal_request(scene_posix))

            plan_out.write_text("{}", encoding="utf-8")
            report_out.write_text("{}", encoding="utf-8")

            exit_code = main([
                "render-run",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--plan-out", str(plan_out),
                "--report-out", str(report_out),
                "--force",
            ])
            self.assertEqual(exit_code, 0)
            plan = json.loads(plan_out.read_text(encoding="utf-8"))
            report = json.loads(report_out.read_text(encoding="utf-8"))
            self.assertEqual(plan["schema_version"], "0.1.0")
            self.assertEqual(report["schema_version"], "0.1.0")

    def test_execute_out_overwrite_requires_execute_force(self) -> None:
        if resolve_ffmpeg_cmd() is None:
            self.skipTest("ffmpeg not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            _write_pcm16_wav(stems_dir / "mix.wav", channels=2)

            scene_posix = (temp_path / "scene.json").resolve().as_posix()
            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "options": {"dry_run": False},
            }
            execute_out = temp_path / "render_execute.json"

            exit_first, _, stderr_first, _, _ = _run_render_run(
                temp_path,
                request_payload=request_payload,
                extra_args=[
                    "--execute-out", str(execute_out),
                ],
            )
            self.assertEqual(exit_first, 0, msg=stderr_first)

            exit_refused, _, stderr_refused, _, _ = _run_render_run(
                temp_path,
                request_payload=request_payload,
                extra_args=[
                    "--force",
                    "--execute-out", str(execute_out),
                ],
            )
            self.assertEqual(exit_refused, 1)
            self.assertIn("--execute-force", stderr_refused)

            exit_allowed, _, stderr_allowed, _, _ = _run_render_run(
                temp_path,
                request_payload=request_payload,
                extra_args=[
                    "--force",
                    "--execute-out", str(execute_out),
                    "--execute-force",
                ],
            )
            self.assertEqual(exit_allowed, 0, msg=stderr_allowed)

    def test_execute_force_requires_execute_out(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            exit_code, _, stderr, _, _ = _run_render_run(
                temp_path,
                extra_args=["--execute-force"],
            )
            self.assertEqual(exit_code, 1)
            self.assertIn("--execute-force requires --execute-out", stderr)


class TestRenderRunBackslashRejection(unittest.TestCase):
    def test_rejects_backslash_in_request_scene_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"
            plan_out = temp_path / "plan.json"
            report_out = temp_path / "report.json"

            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": "scenes\\bad\\path.json",
            })

            stderr_capture = StringIO()
            with redirect_stderr(stderr_capture):
                exit_code = main([
                    "render-run",
                    "--request", str(request_path),
                    "--scene", str(scene_path),
                    "--plan-out", str(plan_out),
                    "--report-out", str(report_out),
                ])
            self.assertNotEqual(exit_code, 0)


class TestRenderRunErrorPaths(unittest.TestCase):
    """Deterministic, stable error messages for invalid inputs."""

    def test_unknown_layout_id_fails_with_sorted_known_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, _, err, _, _ = _run_render_run(tp, request_payload={
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.DOES_NOT_EXIST",
                "scene_path": scene_posix,
            })
            self.assertEqual(rc, 1)
            self.assertIn("Unknown layout_id", err)
            self.assertIn("LAYOUT.DOES_NOT_EXIST", err)
            self.assertIn("LAYOUT.1_0", err)
            self.assertIn("LAYOUT.2_0", err)
            self.assertLess(err.index("LAYOUT.1_0"), err.index("LAYOUT.2_0"))

    def test_unknown_downmix_policy_id_fails_with_sorted_known_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, _, err, _, _ = _run_render_run(tp, request_payload={
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.5_1",
                "scene_path": scene_posix,
                "options": {
                    "downmix_policy_id": "POLICY.DOWNMIX.FAKE_V99",
                },
            })
            self.assertEqual(rc, 1)
            self.assertIn("Unknown policy_id", err)
            self.assertIn("POLICY.DOWNMIX.FAKE_V99", err)
            self.assertIn("POLICY.DOWNMIX.STANDARD_FOLDOWN_V0", err)

    def test_unknown_gates_policy_id_fails_with_sorted_known_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, _, err, _, _ = _run_render_run(tp, request_payload={
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.5_1",
                "scene_path": scene_posix,
                "options": {
                    "gates_policy_id": "POLICY.GATES.NONEXISTENT",
                },
            })
            self.assertEqual(rc, 1)
            self.assertIn("Unknown gates_policy_id", err)
            self.assertIn("POLICY.GATES.NONEXISTENT", err)
            self.assertIn("POLICY.GATES.CORE_V0", err)

    def test_routing_plan_path_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            rc, _, err, _, _ = _run_render_run(tp, request_payload={
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "routing_plan_path": "routing/plan.json",
            })
            self.assertEqual(rc, 1)
            self.assertIn("routing_plan_path is set", err)
            self.assertIn("routing/plan.json", err)

    def test_plugin_chain_invalid_params_refusal_is_deterministic_and_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            _write_pcm16_wav(tp / "stems" / "mix.wav", channels=2)
            scene_posix = (tp / "scene.json").resolve().as_posix()
            request_payload = {
                "schema_version": "0.1.0",
                "target_layout_id": "LAYOUT.2_0",
                "scene_path": scene_posix,
                "options": {
                    "dry_run": False,
                    "plugin_chain": [
                        {
                            "plugin_id": "gain_v0",
                            "params": {
                                "gain_db": -6.0,
                                "bypass": "yes",
                                "macro_mix": "bad",
                                "junk": 1,
                            },
                        }
                    ],
                },
            }
            rc_a, _, err_a, _, report_a = _run_render_run(tp, request_payload=request_payload)
            rc_b, _, err_b, _, report_b = _run_render_run(
                tp,
                request_payload=request_payload,
                extra_args=["--force"],
            )

            self.assertEqual(rc_a, 1)
            self.assertEqual(rc_b, 1)
            self.assertEqual(err_a, err_b)
            self.assertFalse(report_a.exists())
            self.assertFalse(report_b.exists())
            self.assertIn("ISSUE.RENDER.RUN.PLUGIN_CHAIN_INVALID", err_a)
            self.assertIn("options.plugin_chain validation failed:", err_a)
            self.assertIn("options.plugin_chain[1].params has unknown key(s): junk.", err_a)
            self.assertIn(
                "options.plugin_chain[1].params.bypass must be a boolean.",
                err_a,
            )
            self.assertIn(
                "options.plugin_chain[1].params.macro_mix must be a number.",
                err_a,
            )
            self.assertLess(
                err_a.index("unknown key(s): junk"),
                err_a.index("params.bypass must be a boolean"),
            )
            self.assertLess(
                err_a.index("params.bypass must be a boolean"),
                err_a.index("params.macro_mix must be a number"),
            )


def _multi_target_request(scene_path: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "target_layout_ids": ["LAYOUT.2_0", "LAYOUT.5_1"],
        "scene_path": scene_path,
    }


class TestRenderRunMultiTarget(unittest.TestCase):
    """Multi-target render-run tests."""

    def test_multi_target_plan_and_report_schema_valid(self) -> None:
        plan_validator = _schema_validator("render_plan.schema.json")
        report_validator = _schema_validator("render_report.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_posix = scene_path.resolve().as_posix()
            exit_code, stdout, stderr, plan_out, report_out = _run_render_run(
                temp_path,
                request_payload=_multi_target_request(scene_posix),
            )

            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertTrue(plan_out.exists())
            self.assertTrue(report_out.exists())

            plan = json.loads(plan_out.read_text(encoding="utf-8"))
            report = json.loads(report_out.read_text(encoding="utf-8"))
            plan_validator.validate(plan)
            report_validator.validate(report)

    def test_multi_target_report_has_all_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_posix = scene_path.resolve().as_posix()
            exit_code, _, stderr, _, report_out = _run_render_run(
                temp_path,
                request_payload=_multi_target_request(scene_posix),
            )

            self.assertEqual(exit_code, 0, msg=stderr)
            report = json.loads(report_out.read_text(encoding="utf-8"))
            self.assertEqual(len(report["jobs"]), 2)
            self.assertEqual(report["jobs"][0]["status"], "skipped")
            self.assertEqual(report["jobs"][1]["status"], "skipped")
            self.assertEqual(report["jobs"][0]["job_id"], "JOB.001")
            self.assertEqual(report["jobs"][1]["job_id"], "JOB.002")

    def test_multi_target_stdout_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            scene_posix = scene_path.resolve().as_posix()
            exit_code, stdout, stderr, _, _ = _run_render_run(
                temp_path,
                request_payload=_multi_target_request(scene_posix),
            )

            self.assertEqual(exit_code, 0, msg=stderr)
            parsed = json.loads(stdout)
            self.assertEqual(parsed["jobs"], 2)
            self.assertEqual(parsed["targets"], sorted(parsed["targets"]))

    def test_multi_target_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            stems_dir.mkdir()

            scene_path = temp_path / "scene.json"
            request_path = temp_path / "render_request.json"

            scene_posix = scene_path.resolve().as_posix()
            _write_json(scene_path, _minimal_scene(stems_dir.resolve().as_posix()))
            _write_json(request_path, _multi_target_request(scene_posix))

            plan_out_1 = temp_path / "plan1.json"
            report_out_1 = temp_path / "report1.json"
            plan_out_2 = temp_path / "plan2.json"
            report_out_2 = temp_path / "report2.json"

            exit1 = main([
                "render-run",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--plan-out", str(plan_out_1),
                "--report-out", str(report_out_1),
            ])
            exit2 = main([
                "render-run",
                "--request", str(request_path),
                "--scene", str(scene_path),
                "--plan-out", str(plan_out_2),
                "--report-out", str(report_out_2),
            ])
            self.assertEqual(exit1, 0)
            self.assertEqual(exit2, 0)

            self.assertEqual(plan_out_1.read_bytes(), plan_out_2.read_bytes())
            self.assertEqual(report_out_1.read_bytes(), report_out_2.read_bytes())


if __name__ == "__main__":
    unittest.main()
