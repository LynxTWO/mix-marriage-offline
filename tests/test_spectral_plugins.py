"""Tests for mud_detector, resonance_detector, conservative_eq_resolver, parametric_eq_renderer."""
from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

_SR = 48_000


def _write_sine_wav(path: Path, freqs_amps: list[tuple[float, float]], *, sr: int = _SR, duration_s: float = 1.0, channels: int = 1) -> None:
    n = int(duration_s * sr)
    samples = [0.0] * n
    for freq, amp in freqs_amps:
        for i in range(n):
            samples[i] += amp * math.sin(2 * math.pi * freq * i / sr)
    # Normalise
    peak = max(abs(s) for s in samples) or 1.0
    samples = [s / peak * 0.9 for s in samples]
    ints = [int(s * 32767) for s in samples]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        if channels == 1:
            w.writeframes(struct.pack(f"<{n}h", *ints))
        else:
            interleaved = []
            for s in ints:
                for _ in range(channels):
                    interleaved.append(s)
            w.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))


def _write_mud_wav(path: Path, *, sr: int = _SR) -> None:
    """A stem dominated by 200-500 Hz energy (clear mud candidate)."""
    # 60% of energy in mud zone (very muddy)
    freqs_amps = [
        (250.0, 0.8),  # heavy mud content
        (350.0, 0.7),
        (420.0, 0.6),
        (1000.0, 0.1),  # little high content
        (5000.0, 0.05),
    ]
    _write_sine_wav(path, freqs_amps, sr=sr, duration_s=1.0)


def _write_clean_wav(path: Path, *, sr: int = _SR) -> None:
    """A stem with balanced spectrum, minimal mud."""
    freqs_amps = [
        (100.0, 0.15),
        (500.0, 0.10),
        (1000.0, 0.20),
        (2000.0, 0.25),
        (4000.0, 0.20),
        (8000.0, 0.10),
    ]
    _write_sine_wav(path, freqs_amps, sr=sr, duration_s=1.0)


def _write_resonance_wav(path: Path, *, resonance_hz: float = 1200.0, sr: int = _SR) -> None:
    """A stem with a prominent narrow resonance spike."""
    freqs_amps = [
        (100.0, 0.1),
        (500.0, 0.1),
        (resonance_hz, 0.9),  # dominant narrow peak
        (2000.0, 0.05),
        (5000.0, 0.05),
    ]
    _write_sine_wav(path, freqs_amps, sr=sr, duration_s=2.0)


def _make_session(stem_path: Path, stem_id: str = "STEM.TEST") -> dict:
    return {
        "stems": [
            {
                "stem_id": stem_id,
                "file_path": str(stem_path),
            }
        ]
    }


# ---------------------------------------------------------------------------
# MudDetector
# ---------------------------------------------------------------------------

class TestMudDetector(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.detectors.mud_detector import MudDetector
        self.detector = MudDetector()

    def test_detects_muddy_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mud.wav"
            _write_mud_wav(path)
            session = _make_session(path, "STEM.MUD")
            issues = self.detector.detect(session, {})
        self.assertTrue(any(i["issue_id"] == "ISSUE.SPECTRAL.MUD" for i in issues),
                        f"Expected mud issue, got: {issues}")

    def test_no_false_positive_on_clean_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clean.wav"
            _write_clean_wav(path)
            session = _make_session(path, "STEM.CLEAN")
            issues = self.detector.detect(session, {})
        mud_issues = [i for i in issues if i["issue_id"] == "ISSUE.SPECTRAL.MUD"]
        self.assertEqual(mud_issues, [], f"False positive on clean stem: {mud_issues}")

    def test_issue_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mud.wav"
            _write_mud_wav(path)
            session = _make_session(path, "STEM.MUD")
            issues = self.detector.detect(session, {})
        mud_issues = [i for i in issues if i["issue_id"] == "ISSUE.SPECTRAL.MUD"]
        self.assertTrue(mud_issues)
        issue = mud_issues[0]
        self.assertIn("severity", issue)
        self.assertIn("confidence", issue)
        self.assertIn("target", issue)
        self.assertIn("evidence", issue)
        self.assertIsInstance(issue["severity"], int)
        self.assertGreater(issue["severity"], 0)
        self.assertGreater(issue["confidence"], 0.0)
        self.assertLessEqual(issue["confidence"], 1.0)

    def test_silent_stem_produces_no_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silent.wav"
            # Write a near-silent WAV
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(_SR)
                w.writeframes(struct.pack("<1000h", *([0] * 1000)))
            session = _make_session(path, "STEM.SILENT")
            issues = self.detector.detect(session, {})
        self.assertEqual([i for i in issues if i["issue_id"] == "ISSUE.SPECTRAL.MUD"], [])

    def test_missing_stem_path_skipped(self) -> None:
        session = {"stems": [{"stem_id": "STEM.MISSING", "file_path": "/nonexistent/file.wav"}]}
        issues = self.detector.detect(session, {})
        self.assertEqual(issues, [])

    def test_stem_id_in_issue_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mud.wav"
            _write_mud_wav(path)
            session = _make_session(path, "STEM.MUDDY_GUITAR")
            issues = self.detector.detect(session, {})
        mud = [i for i in issues if i["issue_id"] == "ISSUE.SPECTRAL.MUD"]
        if mud:
            self.assertEqual(mud[0]["target"]["stem_id"], "STEM.MUDDY_GUITAR")


# ---------------------------------------------------------------------------
# ResonanceDetector
# ---------------------------------------------------------------------------

class TestResonanceDetector(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.detectors.resonance_detector import ResonanceDetector
        self.detector = ResonanceDetector()

    def test_detects_narrow_resonance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resonance.wav"
            _write_resonance_wav(path, resonance_hz=1200.0)
            session = _make_session(path, "STEM.RESONANCE")
            issues = self.detector.detect(session, {})
        res_issues = [i for i in issues if i["issue_id"] == "ISSUE.SPECTRAL.RESONANCE"]
        self.assertTrue(res_issues, f"Expected resonance issue, got: {issues}")

    def test_resonance_issue_centroid_near_peak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resonance.wav"
            _write_resonance_wav(path, resonance_hz=1200.0)
            session = _make_session(path, "STEM.RESONANCE")
            issues = self.detector.detect(session, {})
        res = [i for i in issues if i["issue_id"] == "ISSUE.SPECTRAL.RESONANCE"]
        self.assertTrue(res)
        # Find centroid evidence
        centroids = [
            e["value"]
            for issue in res
            for e in issue.get("evidence", [])
            if e.get("evidence_id") == "EVID.SPECTRAL.CENTROID_HZ"
        ]
        # At least one centroid should be near the injected resonance
        self.assertTrue(any(abs(c - 1200.0) < 200.0 for c in centroids),
                        f"No centroid near 1200 Hz: {centroids}")

    def test_balanced_spectrum_has_fewer_resonances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clean.wav"
            _write_clean_wav(path)
            session = _make_session(path, "STEM.CLEAN")
            issues = self.detector.detect(session, {})
        res_issues = [i for i in issues if i["issue_id"] == "ISSUE.SPECTRAL.RESONANCE"]
        # A clean balanced sine mix may or may not trigger resonance — just check count <= 3
        self.assertLessEqual(len(res_issues), 3)

    def test_issue_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resonance.wav"
            _write_resonance_wav(path, resonance_hz=800.0)
            session = _make_session(path, "STEM.RES")
            issues = self.detector.detect(session, {})
        res = [i for i in issues if i["issue_id"] == "ISSUE.SPECTRAL.RESONANCE"]
        if res:
            issue = res[0]
            self.assertIn("severity", issue)
            self.assertIn("confidence", issue)
            self.assertIn("target", issue)
            self.assertIn("evidence", issue)
            self.assertGreater(issue["confidence"], 0.0)


# ---------------------------------------------------------------------------
# ConservativeEqResolver
# ---------------------------------------------------------------------------

class TestConservativeEqResolver(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.resolvers.conservative_eq_resolver import ConservativeEqResolver
        self.resolver = ConservativeEqResolver()

    def _mud_issue(self, stem_id: str = "STEM.MUD") -> dict:
        return {
            "issue_id": "ISSUE.SPECTRAL.MUD",
            "severity": 45,
            "confidence": 0.75,
            "target": {"scope": "stem", "stem_id": stem_id},
            "evidence": [
                {"evidence_id": "EVID.SPECTRAL.BAND_ENERGY_RATIO", "value": 0.35, "unit_id": "UNIT.RATIO"},
            ],
        }

    def _resonance_issue(self, stem_id: str = "STEM.SNARE", freq_hz: float = 1200.0) -> dict:
        return {
            "issue_id": "ISSUE.SPECTRAL.RESONANCE",
            "severity": 40,
            "confidence": 0.80,
            "target": {"scope": "stem", "stem_id": stem_id},
            "evidence": [
                {"evidence_id": "EVID.SPECTRAL.CENTROID_HZ", "value": freq_hz, "unit_id": "UNIT.HZ"},
                {"evidence_id": "EVID.SPECTRAL.BAND_ENERGY_DB", "value": 10.5, "unit_id": "UNIT.DB"},
            ],
        }

    def test_mud_produces_bell_cut_recommendation(self) -> None:
        recs = self.resolver.resolve({}, {}, [self._mud_issue()])
        bell_cuts = [r for r in recs if r.get("action_id") == "ACTION.EQ.BELL_CUT"]
        self.assertTrue(bell_cuts, "Expected ACTION.EQ.BELL_CUT for mud issue")

    def test_mud_recommendation_is_low_risk(self) -> None:
        recs = self.resolver.resolve({}, {}, [self._mud_issue()])
        for rec in recs:
            if rec.get("action_id") == "ACTION.EQ.BELL_CUT":
                self.assertEqual(rec.get("risk"), "low")
                self.assertIs(rec.get("requires_approval"), False)

    def test_mud_recommendation_params_are_cuts_only(self) -> None:
        recs = self.resolver.resolve({}, {}, [self._mud_issue()])
        for rec in recs:
            if rec.get("action_id") == "ACTION.EQ.BELL_CUT":
                gain_param = next(
                    (p for p in rec.get("params", []) if p.get("param_id") == "PARAM.EQ.GAIN_DB"),
                    None
                )
                self.assertIsNotNone(gain_param)
                self.assertLess(gain_param["value"], 0.0, "Mud cut must be negative gain")

    def test_resonance_produces_notch_cut_recommendation(self) -> None:
        recs = self.resolver.resolve({}, {}, [self._resonance_issue()])
        notch_cuts = [r for r in recs if r.get("action_id") == "ACTION.EQ.NOTCH_CUT"]
        self.assertTrue(notch_cuts, "Expected ACTION.EQ.NOTCH_CUT for resonance issue")

    def test_resonance_freq_in_params(self) -> None:
        freq = 1200.0
        recs = self.resolver.resolve({}, {}, [self._resonance_issue(freq_hz=freq)])
        for rec in recs:
            if rec.get("action_id") == "ACTION.EQ.NOTCH_CUT":
                freq_param = next(
                    (p for p in rec.get("params", []) if p.get("param_id") == "PARAM.EQ.FREQ_HZ"),
                    None
                )
                self.assertIsNotNone(freq_param)
                self.assertAlmostEqual(freq_param["value"], freq, places=0)

    def test_duplicate_mud_issues_deduplicated(self) -> None:
        issues = [self._mud_issue("STEM.DRUMS"), self._mud_issue("STEM.DRUMS")]
        recs = self.resolver.resolve({}, {}, issues)
        bell_cuts = [r for r in recs if r.get("action_id") == "ACTION.EQ.BELL_CUT"]
        self.assertEqual(len(bell_cuts), 1, "Duplicate mud issue should produce single recommendation")

    def test_non_spectral_issues_ignored(self) -> None:
        unrelated = {
            "issue_id": "ISSUE.DYNAMICS.OVER_COMPRESSION",
            "severity": 35,
            "confidence": 0.6,
            "target": {"scope": "stem", "stem_id": "STEM.BUS"},
            "evidence": [],
        }
        recs = self.resolver.resolve({}, {}, [unrelated])
        self.assertEqual(recs, [])

    def test_recommendation_has_required_fields(self) -> None:
        recs = self.resolver.resolve({}, {}, [self._mud_issue()])
        self.assertTrue(recs)
        rec = recs[0]
        for field in ("recommendation_id", "issue_id", "action_id", "risk", "requires_approval", "scope", "params"):
            self.assertIn(field, rec, f"Missing field: {field}")
        self.assertTrue(rec["recommendation_id"].startswith("REC."))


# ---------------------------------------------------------------------------
# ParametricEqRenderer (smoke test — verifies it runs without crashing)
# ---------------------------------------------------------------------------

class TestParametricEqRenderer(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.renderers.parametric_eq_renderer import ParametricEqRenderer
        self.renderer = ParametricEqRenderer()

    def _make_rec(self, stem_id: str, action_id: str, freq_hz: float, q: float, gain_db: float) -> dict:
        return {
            "recommendation_id": f"REC.TEST.{stem_id}.{action_id}",
            "issue_id": "ISSUE.SPECTRAL.MUD",
            "action_id": action_id,
            "risk": "low",
            "requires_approval": False,
            "scope": {"scope": "stem", "stem_id": stem_id},
            "params": [
                {"param_id": "PARAM.EQ.FREQ_HZ", "value": freq_hz},
                {"param_id": "PARAM.EQ.Q", "value": q},
                {"param_id": "PARAM.EQ.GAIN_DB", "value": gain_db},
            ],
        }

    def test_render_bell_cut_produces_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src" / "stem.wav"
            out_dir = Path(tmp) / "out"
            _write_clean_wav(src)
            session = {"stems": [{"stem_id": "STEM.MAIN", "file_path": str(src)}]}
            rec = self._make_rec("STEM.MAIN", "ACTION.EQ.BELL_CUT", 300.0, 0.7, -3.0)
            manifest = self.renderer.render(session, [rec], output_dir=out_dir)
            self.assertIsInstance(manifest, dict)
            self.assertEqual(manifest.get("renderer_id"), "PLUGIN.RENDERER.PARAMETRIC_EQ")
            outputs = manifest.get("outputs", [])
            self.assertTrue(outputs, f"Expected output, got: {manifest}")
            output_path = Path(outputs[0]["file_path"])
            self.assertTrue(output_path.exists(), f"Output WAV not created: {output_path}")

    def test_render_without_output_dir_skips(self) -> None:
        session = {"stems": [{"stem_id": "STEM.MAIN", "file_path": "/fake/path.wav"}]}
        rec = self._make_rec("STEM.MAIN", "ACTION.EQ.BELL_CUT", 300.0, 0.7, -3.0)
        manifest = self.renderer.render(session, [rec], output_dir=None)
        self.assertEqual(manifest.get("outputs"), [])
        self.assertTrue(manifest.get("skipped"))

    def test_boost_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "stem.wav"
            out_dir = Path(tmp) / "out"
            _write_clean_wav(src)
            session = {"stems": [{"stem_id": "STEM.MAIN", "file_path": str(src)}]}
            # Boost (positive gain_db) should be rejected
            rec = self._make_rec("STEM.MAIN", "ACTION.EQ.BELL_CUT", 300.0, 0.7, +3.0)
            manifest = self.renderer.render(session, [rec], output_dir=out_dir)
            self.assertEqual(manifest.get("outputs"), [], "Boosts must be rejected")

    def test_high_risk_rec_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "stem.wav"
            out_dir = Path(tmp) / "out"
            _write_clean_wav(src)
            session = {"stems": [{"stem_id": "STEM.MAIN", "file_path": str(src)}]}
            rec = self._make_rec("STEM.MAIN", "ACTION.EQ.BELL_CUT", 300.0, 0.7, -3.0)
            rec["risk"] = "high"
            rec["requires_approval"] = True
            manifest = self.renderer.render(session, [rec], output_dir=out_dir)
            self.assertEqual(manifest.get("outputs"), [], "High-risk recs must be rejected")

    def test_output_wav_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src" / "stem.wav"
            out_dir = Path(tmp) / "out"
            _write_clean_wav(src, sr=48000)
            session = {"stems": [{"stem_id": "STEM.A", "file_path": str(src)}]}
            rec = self._make_rec("STEM.A", "ACTION.EQ.BELL_CUT", 300.0, 0.7, -2.5)
            manifest = self.renderer.render(session, [rec], output_dir=out_dir)
            outputs = manifest.get("outputs", [])
            if not outputs:
                self.skipTest("No output produced (scipy may be missing)")
            output_path = Path(outputs[0]["file_path"])
            with wave.open(str(output_path), "rb") as w:
                self.assertEqual(w.getsampwidth(), 3)  # 24-bit
                self.assertEqual(w.getframerate(), 48000)
                self.assertGreater(w.getnframes(), 0)


if __name__ == "__main__":
    unittest.main()
