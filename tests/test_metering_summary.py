"""Tests for DoD 4.4: objective metering summary in scan/analyze.

Covers:
- _build_metering_summary() extracts LUFS_I, TRUEPEAK_DBTP, CREST_FACTOR_DB,
  and phase correlation from per-stem measurements.
- Session-level aggregates: lufs_i_min/max/range, true_peak_max.
- Bus-level aggregates from session.buses.
- report["metering"] is included when --meters truth|basic is used.
- report["metering"] absent when meters=None.
- metering.mode matches requested mode.
- Deterministic: sorted by stem_id, finite-only values.
- Schema validation: report with metering passes report.schema.json.
"""
from __future__ import annotations

import json
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# WAV helpers
# ---------------------------------------------------------------------------

def _write_sine_wav(
    path: Path,
    freq_hz: float,
    amplitude: float,
    channels: int,
    sample_rate: int,
    duration_s: float,
    bit_depth: int = 16,
) -> None:
    n = int(sample_rate * duration_s)
    sampwidth = bit_depth // 8
    max_val = (1 << (bit_depth - 1)) - 1
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        raw = bytearray()
        for i in range(n):
            v = amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate)
            iv = max(-max_val - 1, min(max_val, int(v * max_val)))
            for _ in range(channels):
                if sampwidth == 2:
                    raw += struct.pack("<h", iv)
                else:
                    raw += struct.pack("<i", iv)[: sampwidth]
        wf.writeframes(bytes(raw))


def _write_stereo_corr_wav(
    path: Path,
    correlation: float,  # 1.0 = in-phase, -1.0 = out-of-phase
    sample_rate: int = 48000,
    duration_s: float = 1.0,
    amplitude: float = 0.3,
    bit_depth: int = 16,
) -> None:
    """Write a 2-ch WAV with approximate phase correlation."""
    n = int(sample_rate * duration_s)
    sampwidth = bit_depth // 8
    max_val = (1 << (bit_depth - 1)) - 1
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        raw = bytearray()
        for i in range(n):
            ch0 = amplitude * math.sin(2 * math.pi * 440.0 * i / sample_rate)
            ch1 = correlation * ch0
            for v in (ch0, ch1):
                iv = max(-max_val - 1, min(max_val, int(v * max_val)))
                if sampwidth == 2:
                    raw += struct.pack("<h", iv)
                else:
                    raw += struct.pack("<i", iv)[:sampwidth]
        wf.writeframes(bytes(raw))


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _has_numpy() -> bool:
    try:
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Unit tests for _build_metering_summary
# ---------------------------------------------------------------------------

class TestBuildMeteringSummaryUnit(unittest.TestCase):
    """Unit tests for the _build_metering_summary helper."""

    def setUp(self) -> None:
        from mmo.tools.scan_session import _build_metering_summary
        self._fn = _build_metering_summary

    def _make_session(
        self,
        stems: List[Dict[str, Any]],
        buses: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        s: Dict[str, Any] = {"stems": stems}
        if buses is not None:
            s["buses"] = buses
        return s

    def _make_stem(
        self,
        stem_id: str,
        lufs_i: float | None = None,
        tp: float | None = None,
        crest: float | None = None,
        corr: float | None = None,
    ) -> Dict[str, Any]:
        measurements: List[Dict[str, Any]] = []
        if lufs_i is not None:
            measurements.append(
                {"evidence_id": "EVID.METER.LUFS_I", "value": lufs_i, "unit_id": "UNIT.LUFS"}
            )
        if tp is not None:
            measurements.append(
                {"evidence_id": "EVID.METER.TRUEPEAK_DBTP", "value": tp, "unit_id": "UNIT.DBTP"}
            )
        if crest is not None:
            measurements.append(
                {"evidence_id": "EVID.METER.CREST_FACTOR_DB", "value": crest, "unit_id": "UNIT.DB"}
            )
        if corr is not None:
            measurements.append(
                {"evidence_id": "EVID.IMAGE.CORRELATION", "value": corr, "unit_id": "UNIT.CORRELATION"}
            )
        return {"stem_id": stem_id, "file_path": f"{stem_id}.wav", "measurements": measurements}

    def test_basic_structure(self) -> None:
        session = self._make_session(
            [self._make_stem("kick", lufs_i=-18.0, tp=-6.0, crest=12.5)]
        )
        result = self._fn(session, mode="truth")
        self.assertEqual(result["mode"], "truth")
        self.assertIn("stems", result)
        self.assertIn("session", result)
        self.assertEqual(len(result["stems"]), 1)

    def test_stem_fields_extracted(self) -> None:
        session = self._make_session(
            [self._make_stem("kick", lufs_i=-18.0, tp=-6.0, crest=12.5, corr=0.95)]
        )
        result = self._fn(session, mode="truth")
        stem = result["stems"][0]
        self.assertEqual(stem["stem_id"], "kick")
        self.assertAlmostEqual(stem["lufs_i"], -18.0, places=1)
        self.assertAlmostEqual(stem["true_peak_dbtp"], -6.0, places=1)
        self.assertAlmostEqual(stem["crest_db"], 12.5, places=1)
        self.assertAlmostEqual(stem["correlation"], 0.95, places=2)

    def test_missing_measurements_yield_null(self) -> None:
        session = self._make_session([self._make_stem("bass")])
        result = self._fn(session, mode="basic")
        stem = result["stems"][0]
        self.assertIsNone(stem["lufs_i"])
        self.assertIsNone(stem["true_peak_dbtp"])
        self.assertIsNone(stem["crest_db"])
        self.assertIsNone(stem["correlation"])

    def test_session_aggregates(self) -> None:
        stems = [
            self._make_stem("a", lufs_i=-20.0, tp=-8.0),
            self._make_stem("b", lufs_i=-12.0, tp=-3.0),
        ]
        session = self._make_session(stems)
        result = self._fn(session, mode="truth")
        sess = result["session"]
        self.assertEqual(sess["stem_count"], 2)
        self.assertAlmostEqual(sess["lufs_i_min"], -20.0, places=1)
        self.assertAlmostEqual(sess["lufs_i_max"], -12.0, places=1)
        self.assertAlmostEqual(sess["lufs_i_range_db"], 8.0, places=1)
        self.assertAlmostEqual(sess["true_peak_max_dbtp"], -3.0, places=1)

    def test_session_aggregates_no_measurements(self) -> None:
        session = self._make_session([self._make_stem("empty")])
        result = self._fn(session, mode="basic")
        sess = result["session"]
        self.assertIsNone(sess["lufs_i_min"])
        self.assertIsNone(sess["lufs_i_max"])
        self.assertIsNone(sess["lufs_i_range_db"])
        self.assertIsNone(sess["true_peak_max_dbtp"])

    def test_stems_sorted_by_stem_id(self) -> None:
        stems = [
            self._make_stem("z_stem", lufs_i=-20.0),
            self._make_stem("a_stem", lufs_i=-10.0),
        ]
        session = self._make_session(stems)
        result = self._fn(session, mode="truth")
        ids = [s["stem_id"] for s in result["stems"]]
        self.assertEqual(ids, sorted(ids))

    def test_bus_level_aggregates(self) -> None:
        stems = [
            self._make_stem("kick", lufs_i=-18.0, tp=-6.0, crest=10.0),
            self._make_stem("snare", lufs_i=-20.0, tp=-8.0, crest=14.0),
            self._make_stem("bass", lufs_i=-14.0, tp=-4.0, crest=8.0),
        ]
        buses = [
            {"bus_id": "drums", "member_stem_ids": ["kick", "snare"]},
        ]
        session = self._make_session(stems, buses=buses)
        result = self._fn(session, mode="truth")
        self.assertIn("buses", result)
        self.assertEqual(len(result["buses"]), 1)
        bus = result["buses"][0]
        self.assertEqual(bus["bus_id"], "drums")
        self.assertAlmostEqual(bus["lufs_i"], (-18.0 + -20.0) / 2, places=1)
        self.assertAlmostEqual(bus["true_peak_dbtp"], -6.0, places=1)  # max
        self.assertAlmostEqual(bus["crest_db"], (10.0 + 14.0) / 2, places=1)

    def test_no_buses_field_when_empty(self) -> None:
        session = self._make_session([self._make_stem("kick")])
        result = self._fn(session, mode="truth")
        self.assertNotIn("buses", result)

    def test_mode_passthrough(self) -> None:
        session = self._make_session([self._make_stem("x")])
        for mode in ("truth", "basic"):
            result = self._fn(session, mode=mode)
            self.assertEqual(result["mode"], mode)

    def test_inf_values_become_null(self) -> None:
        """Infinite LUFS (e.g. silent file) must not appear in aggregates."""
        stem = self._make_stem("silent", lufs_i=float("-inf"), tp=float("-inf"))
        session = self._make_session([stem])
        result = self._fn(session, mode="truth")
        s = result["stems"][0]
        self.assertIsNone(s["lufs_i"])
        self.assertIsNone(s["true_peak_dbtp"])
        sess = result["session"]
        self.assertIsNone(sess["lufs_i_min"])
        self.assertIsNone(sess["true_peak_max_dbtp"])


# ---------------------------------------------------------------------------
# Integration tests: build_report produces metering section
# ---------------------------------------------------------------------------

class TestBuildReportMeteringIntegration(unittest.TestCase):
    """Integration tests: scan_session.build_report produces metering field."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._stems_dir = Path(self._tmpdir)

    def _write_wav(self, name: str, freq: float = 440.0, amp: float = 0.3) -> Path:
        p = self._stems_dir / name
        _write_sine_wav(p, freq_hz=freq, amplitude=amp, channels=1, sample_rate=48000, duration_s=1.0)
        return p

    def test_metering_absent_when_no_meters_flag(self) -> None:
        """Without --meters, no metering summary in report."""
        from mmo.tools.scan_session import build_report

        self._write_wav("kick.wav")
        report = build_report(self._stems_dir, "2000-01-01T00:00:00Z", meters=None)
        self.assertNotIn("metering", report)

    def test_metering_present_basic_mode(self) -> None:
        """With meters='basic', report has metering.mode='basic'."""
        from mmo.tools.scan_session import build_report

        self._write_wav("kick.wav")
        report = build_report(self._stems_dir, "2000-01-01T00:00:00Z", meters="basic")
        self.assertIn("metering", report)
        self.assertEqual(report["metering"]["mode"], "basic")
        self.assertIn("stems", report["metering"])
        self.assertIn("session", report["metering"])

    @unittest.skipUnless(_has_numpy(), "numpy required for truth meters")
    def test_metering_present_truth_mode(self) -> None:
        """With meters='truth' and numpy, report has metering with LUFS/true-peak."""
        from mmo.tools.scan_session import build_report

        self._write_wav("kick.wav", amp=0.5)
        report = build_report(self._stems_dir, "2000-01-01T00:00:00Z", meters="truth")
        self.assertIn("metering", report)
        m = report["metering"]
        self.assertEqual(m["mode"], "truth")
        self.assertEqual(len(m["stems"]), 1)
        stem = m["stems"][0]
        self.assertEqual(stem["stem_id"], "kick")
        # LUFS should be finite for a non-silent sine wave
        if stem["lufs_i"] is not None:
            self.assertTrue(math.isfinite(stem["lufs_i"]))
        # true-peak should be finite
        if stem["true_peak_dbtp"] is not None:
            self.assertTrue(math.isfinite(stem["true_peak_dbtp"]))

    @unittest.skipUnless(_has_numpy(), "numpy required for truth meters")
    def test_session_aggregates_populated(self) -> None:
        """Session-level stats computed from multiple stems."""
        from mmo.tools.scan_session import build_report

        # Two stems with different amplitudes → different LUFS
        self._write_wav("loud.wav", amp=0.8)
        self._write_wav("quiet.wav", amp=0.05)
        report = build_report(self._stems_dir, "2000-01-01T00:00:00Z", meters="truth")
        sess = report["metering"]["session"]
        self.assertEqual(sess["stem_count"], 2)
        if sess["lufs_i_min"] is not None and sess["lufs_i_max"] is not None:
            self.assertLessEqual(sess["lufs_i_min"], sess["lufs_i_max"])

    @unittest.skipUnless(_has_numpy(), "numpy required for truth meters")
    def test_stereo_correlation_in_metering(self) -> None:
        """Stereo WAV correlation appears in metering summary."""
        from mmo.tools.scan_session import build_report

        p = self._stems_dir / "synth.wav"
        _write_stereo_corr_wav(p, correlation=1.0)
        report = build_report(self._stems_dir, "2000-01-01T00:00:00Z", meters="truth")
        stem = next((s for s in report["metering"]["stems"] if s["stem_id"] == "synth"), None)
        self.assertIsNotNone(stem)
        if stem["correlation"] is not None:
            self.assertGreater(stem["correlation"], 0.9)

    @unittest.skipUnless(_has_numpy(), "numpy required for truth meters")
    def test_metering_deterministic(self) -> None:
        """Same WAV → same metering summary on two calls."""
        from mmo.tools.scan_session import build_report

        self._write_wav("bass.wav", amp=0.4)
        r1 = build_report(self._stems_dir, "2000-01-01T00:00:00Z", meters="truth")
        r2 = build_report(self._stems_dir, "2000-01-01T00:00:00Z", meters="truth")
        self.assertEqual(r1["metering"], r2["metering"])

    def test_metering_stems_sorted(self) -> None:
        """metering.stems is sorted by stem_id."""
        from mmo.tools.scan_session import build_report

        self._write_wav("z_stem.wav")
        self._write_wav("a_stem.wav")
        report = build_report(self._stems_dir, "2000-01-01T00:00:00Z", meters="basic")
        ids = [s["stem_id"] for s in report["metering"]["stems"]]
        self.assertEqual(ids, sorted(ids))


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestMeteringSchemaValidation(unittest.TestCase):
    """Validate report and scene schemas accept metering payloads."""

    def _load_schema(self, name: str) -> Dict[str, Any]:
        try:
            from mmo.resources import schemas_dir
            path = schemas_dir() / name
        except Exception:
            path = Path(__file__).resolve().parents[1] / "schemas" / name
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _validate(self, schema: Dict[str, Any], instance: Dict[str, Any]) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
        if errors:
            msgs = "\n".join(f"  - {e.message}" for e in errors)
            self.fail(f"Schema validation failed:\n{msgs}")

    def _minimal_report(self) -> Dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "report_id": "abc123",
            "project_id": "abc123",
            "generated_at": "2000-01-01T00:00:00Z",
            "engine_version": "0.1.0",
            "ontology_version": "0.1.0",
            "session": {"stems": []},
            "issues": [],
            "recommendations": [],
        }

    def test_report_with_metering_truth_passes_schema(self) -> None:
        schema = self._load_schema("report.schema.json")
        report = self._minimal_report()
        report["metering"] = {
            "mode": "truth",
            "stems": [
                {
                    "stem_id": "kick",
                    "lufs_i": -18.5,
                    "true_peak_dbtp": -6.0,
                    "crest_db": 12.5,
                    "correlation": None,
                }
            ],
            "session": {
                "stem_count": 1,
                "lufs_i_min": -18.5,
                "lufs_i_max": -18.5,
                "lufs_i_range_db": 0.0,
                "true_peak_max_dbtp": -6.0,
            },
        }
        self._validate(schema, report)

    def test_report_with_metering_basic_passes_schema(self) -> None:
        schema = self._load_schema("report.schema.json")
        report = self._minimal_report()
        report["metering"] = {
            "mode": "basic",
            "stems": [
                {"stem_id": "bass", "lufs_i": None, "true_peak_dbtp": None, "crest_db": 10.0, "correlation": None}
            ],
            "session": {"stem_count": 1},
        }
        self._validate(schema, report)

    def test_report_with_metering_buses_passes_schema(self) -> None:
        schema = self._load_schema("report.schema.json")
        report = self._minimal_report()
        report["metering"] = {
            "mode": "truth",
            "stems": [
                {"stem_id": "kick", "lufs_i": -18.0, "true_peak_dbtp": -6.0, "crest_db": 12.0, "correlation": None},
                {"stem_id": "snare", "lufs_i": -20.0, "true_peak_dbtp": -8.0, "crest_db": 14.0, "correlation": None},
            ],
            "buses": [
                {
                    "bus_id": "drums",
                    "member_stem_ids": ["kick", "snare"],
                    "lufs_i": -19.0,
                    "true_peak_dbtp": -6.0,
                    "crest_db": 13.0,
                }
            ],
            "session": {
                "stem_count": 2,
                "lufs_i_min": -20.0,
                "lufs_i_max": -18.0,
                "lufs_i_range_db": 2.0,
                "true_peak_max_dbtp": -6.0,
            },
        }
        self._validate(schema, report)

    def test_report_without_metering_still_valid(self) -> None:
        schema = self._load_schema("report.schema.json")
        report = self._minimal_report()
        self._validate(schema, report)

    def test_scene_with_metering_passes_schema(self) -> None:
        schema = self._load_schema("scene.schema.json")
        scene = {
            "schema_version": "0.1.0",
            "scene_id": "SCENE.test",
            "source": {"stems_dir": "/tmp/stems", "created_from": "analyze"},
            "objects": [],
            "beds": [],
            "metadata": {
                "metering": {
                    "mode": "truth",
                    "objects": [
                        {
                            "object_id": "OBJ.001",
                            "stem_id": "kick",
                            "lufs_i": -18.5,
                            "true_peak_dbtp": -6.0,
                            "crest_db": 12.5,
                            "correlation": None,
                        }
                    ],
                    "session": {
                        "stem_count": 1,
                        "lufs_i_min": -18.5,
                        "lufs_i_max": -18.5,
                        "lufs_i_range_db": 0.0,
                        "true_peak_max_dbtp": -6.0,
                    },
                }
            },
        }
        self._validate(schema, scene)

    def test_scene_without_metering_passes_schema(self) -> None:
        schema = self._load_schema("scene.schema.json")
        scene = {
            "schema_version": "0.1.0",
            "scene_id": "SCENE.test",
            "source": {"stems_dir": "/tmp/stems", "created_from": "analyze"},
            "objects": [],
            "beds": [],
            "metadata": {},
        }
        self._validate(schema, scene)


if __name__ == "__main__":
    unittest.main()
