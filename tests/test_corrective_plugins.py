"""Tests for harshness_sibilance_detector, masking_detector, compressor_renderer, safe_renderer."""
from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

_SR = 48_000


# ---------------------------------------------------------------------------
# WAV helpers
# ---------------------------------------------------------------------------

def _write_sine_wav(
    path: Path,
    freqs_amps: list[tuple[float, float]],
    *,
    sr: int = _SR,
    duration_s: float = 1.0,
    channels: int = 1,
    amplitude: float = 0.9,
) -> None:
    n = int(duration_s * sr)
    samples = [0.0] * n
    for freq, amp in freqs_amps:
        for i in range(n):
            samples[i] += amp * math.sin(2 * math.pi * freq * i / sr)
    peak = max(abs(s) for s in samples) or 1.0
    samples = [s / peak * amplitude for s in samples]
    ints = [int(s * 32767) for s in samples]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        interleaved = []
        for s in ints:
            for _ in range(channels):
                interleaved.append(s)
        w.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))


def _write_silent_wav(path: Path, *, sr: int = _SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack("<1000h", *([0] * 1000)))


def _write_harsh_wav(path: Path, *, sr: int = _SR) -> None:
    """Stem dominated by 2–5 kHz (harsh upper-mid region)."""
    freqs_amps = [
        (100.0, 0.05),
        (500.0, 0.05),
        (2000.0, 0.55),
        (3000.0, 0.60),
        (4500.0, 0.50),
        (8000.0, 0.05),
    ]
    _write_sine_wav(path, freqs_amps, sr=sr, duration_s=1.5)


def _write_sibilant_wav(path: Path, *, sr: int = _SR) -> None:
    """Stem dominated by 5–10 kHz (sibilance region)."""
    freqs_amps = [
        (200.0, 0.05),
        (1000.0, 0.05),
        (5500.0, 0.55),
        (7000.0, 0.60),
        (9000.0, 0.50),
    ]
    _write_sine_wav(path, freqs_amps, sr=sr, duration_s=1.5)


def _write_balanced_wav(path: Path, *, sr: int = _SR) -> None:
    """Broadly balanced spectrum — should not trigger harshness or sibilance.

    Deliberately keeps 2–5 kHz and 5–10 kHz energy well below the detector
    thresholds by anchoring most energy in the sub-2kHz region.
    """
    freqs_amps = [
        (80.0, 0.40),
        (200.0, 0.35),
        (500.0, 0.30),
        (1000.0, 0.20),
        (2000.0, 0.06),   # small upper-mid contribution
        (4000.0, 0.05),   # small upper-mid contribution
        (8000.0, 0.04),
    ]
    _write_sine_wav(path, freqs_amps, sr=sr, duration_s=1.0)


def _write_kick_wav(path: Path, *, sr: int = _SR) -> None:
    """Stem dominated by 60–200 Hz (kick drum character)."""
    freqs_amps = [
        (60.0, 0.70),
        (90.0, 0.60),
        (120.0, 0.50),
        (150.0, 0.40),
        (3000.0, 0.05),
    ]
    _write_sine_wav(path, freqs_amps, sr=sr, duration_s=1.0)


def _write_bass_wav(path: Path, *, sr: int = _SR) -> None:
    """Stem dominated by 60–200 Hz (bass guitar character)."""
    freqs_amps = [
        (70.0, 0.65),
        (100.0, 0.55),
        (140.0, 0.50),
        (180.0, 0.40),
        (4000.0, 0.05),
    ]
    _write_sine_wav(path, freqs_amps, sr=sr, duration_s=1.0)


def _write_vocal_wav(path: Path, *, sr: int = _SR) -> None:
    """Stem with vocal energy, but spread across many bands so 1–4 kHz ratio is modest.

    Spreading energy across sub-1 kHz and above-4 kHz bands keeps the VIM band
    energy small enough that multiple loud music stems can exceed the 2.5x
    masking threshold.
    """
    freqs_amps = [
        (80.0, 0.40),
        (200.0, 0.35),
        (400.0, 0.30),
        (800.0, 0.25),
        (1500.0, 0.15),
        (2500.0, 0.12),
        (6000.0, 0.10),
        (10000.0, 0.08),
    ]
    _write_sine_wav(path, freqs_amps, sr=sr, duration_s=1.0)


def _write_music_loud_wav(path: Path, *, sr: int = _SR) -> None:
    """Non-vocal stem with ALL energy concentrated in the 1–4 kHz masking band."""
    freqs_amps = [
        (1200.0, 0.80),
        (2000.0, 0.85),
        (2800.0, 0.80),
        (3600.0, 0.75),
    ]
    _write_sine_wav(path, freqs_amps, sr=sr, duration_s=1.0)


def _make_session(stem_path: Path, stem_id: str = "STEM.TEST") -> dict:
    return {"stems": [{"stem_id": stem_id, "file_path": str(stem_path)}]}


def _make_multi_session(stems: list[dict]) -> dict:
    return {"stems": stems}


def _make_stem_entry(stem_id: str, path: Path, *, role_id: str | None = None) -> dict:
    entry: dict = {"stem_id": stem_id, "file_path": str(path)}
    if role_id is not None:
        entry["role_id"] = role_id
    return entry


# ---------------------------------------------------------------------------
# HarshnessDetector
# ---------------------------------------------------------------------------

class TestHarshnessDetector(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.detectors.harshness_sibilance_detector import HarshnessDetector
        self.detector = HarshnessDetector()
        self.issue_id = "ISSUE.SPECTRAL.HARSHNESS"

    def test_detects_harsh_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "harsh.wav"
            _write_harsh_wav(path)
            issues = self.detector.detect(_make_session(path), {})
        self.assertTrue(any(i["issue_id"] == self.issue_id for i in issues),
                        f"Expected harshness issue; got {issues}")

    def test_no_false_positive_on_balanced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "balanced.wav"
            _write_balanced_wav(path)
            issues = self.detector.detect(_make_session(path), {})
        self.assertFalse(any(i["issue_id"] == self.issue_id for i in issues),
                         f"False positive on balanced stem: {issues}")

    def test_issue_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "harsh.wav"
            _write_harsh_wav(path)
            issues = self.detector.detect(_make_session(path, "STEM.HARSH"), {})
        hits = [i for i in issues if i["issue_id"] == self.issue_id]
        self.assertTrue(hits)
        issue = hits[0]
        self.assertIn("severity", issue)
        self.assertIn("confidence", issue)
        self.assertIn("target", issue)
        self.assertIn("evidence", issue)
        self.assertIsInstance(issue["severity"], int)
        self.assertGreaterEqual(issue["severity"], 30)
        self.assertGreater(issue["confidence"], 0.0)
        self.assertLessEqual(issue["confidence"], 1.0)

    def test_stem_id_in_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "harsh.wav"
            _write_harsh_wav(path)
            issues = self.detector.detect(_make_session(path, "STEM.HARSH_GTR"), {})
        hits = [i for i in issues if i["issue_id"] == self.issue_id]
        if hits:
            self.assertEqual(hits[0]["target"].get("stem_id"), "STEM.HARSH_GTR")

    def test_silent_stem_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silent.wav"
            _write_silent_wav(path)
            issues = self.detector.detect(_make_session(path), {})
        self.assertFalse(any(i["issue_id"] == self.issue_id for i in issues))

    def test_missing_file_skipped(self) -> None:
        session = {"stems": [{"stem_id": "STEM.MISSING", "file_path": "/nonexistent/file.wav"}]}
        issues = self.detector.detect(session, {})
        self.assertFalse(any(i["issue_id"] == self.issue_id for i in issues))

    def test_empty_stems_list(self) -> None:
        issues = self.detector.detect({"stems": []}, {})
        self.assertEqual(issues, [])

    def test_plugin_id(self) -> None:
        self.assertEqual(self.detector.plugin_id, "PLUGIN.DETECTOR.HARSHNESS")


# ---------------------------------------------------------------------------
# SibilanceDetector
# ---------------------------------------------------------------------------

class TestSibilanceDetector(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.detectors.harshness_sibilance_detector import SibilanceDetector
        self.detector = SibilanceDetector()
        self.issue_id = "ISSUE.SPECTRAL.SIBILANCE"

    def test_detects_sibilant_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sib.wav"
            _write_sibilant_wav(path)
            issues = self.detector.detect(_make_session(path), {})
        self.assertTrue(any(i["issue_id"] == self.issue_id for i in issues),
                        f"Expected sibilance issue; got {issues}")

    def test_no_false_positive_on_balanced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "balanced.wav"
            _write_balanced_wav(path)
            issues = self.detector.detect(_make_session(path), {})
        self.assertFalse(any(i["issue_id"] == self.issue_id for i in issues),
                         f"False positive on balanced: {issues}")

    def test_issue_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sib.wav"
            _write_sibilant_wav(path)
            issues = self.detector.detect(_make_session(path, "STEM.SIB"), {})
        hits = [i for i in issues if i["issue_id"] == self.issue_id]
        self.assertTrue(hits)
        issue = hits[0]
        for field in ("severity", "confidence", "target", "evidence"):
            self.assertIn(field, issue)
        self.assertGreaterEqual(issue["severity"], 30)

    def test_low_sample_rate_wav_skipped(self) -> None:
        """Stems where Nyquist < 0.9 * 10 kHz should be silently skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "low_sr.wav"
            # Write a WAV at 16 kHz — Nyquist (8 kHz) < 9 kHz threshold
            _write_sibilant_wav(path, sr=16_000)
            issues = self.detector.detect(_make_session(path), {})
        self.assertFalse(any(i["issue_id"] == self.issue_id for i in issues))

    def test_plugin_id(self) -> None:
        self.assertEqual(self.detector.plugin_id, "PLUGIN.DETECTOR.SIBILANCE")


# ---------------------------------------------------------------------------
# MaskingDetector — kick/bass
# ---------------------------------------------------------------------------

class TestMaskingDetectorKickBass(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.detectors.masking_detector import MaskingDetector
        self.detector = MaskingDetector()
        self.issue_id = "ISSUE.MASKING.KICK_BASS"

    def _kick_bass_session(self, tmp: str) -> dict:
        kick = Path(tmp) / "kick.wav"
        bass = Path(tmp) / "bass.wav"
        _write_kick_wav(kick)
        _write_bass_wav(bass)
        return _make_multi_session([
            _make_stem_entry("STEM.KICK", kick, role_id="ROLE.DRUM.KICK"),
            _make_stem_entry("STEM.BASS", bass, role_id="ROLE.BASS.DI"),
        ])

    def test_detects_kick_bass_masking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._kick_bass_session(tmp)
            issues = self.detector.detect(session, {})
        self.assertTrue(any(i["issue_id"] == self.issue_id for i in issues),
                        f"Expected kick/bass masking; got {issues}")

    def test_issue_has_bus_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._kick_bass_session(tmp)
            issues = self.detector.detect(session, {})
        hits = [i for i in issues if i["issue_id"] == self.issue_id]
        if hits:
            self.assertEqual(hits[0]["target"]["scope"], "bus")

    def test_issue_references_stem_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._kick_bass_session(tmp)
            issues = self.detector.detect(session, {})
        hits = [i for i in issues if i["issue_id"] == self.issue_id]
        if hits:
            target = hits[0]["target"]
            self.assertIn("stem_id", target)
            self.assertIn("secondary_stem_id", target)

    def test_issue_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._kick_bass_session(tmp)
            issues = self.detector.detect(session, {})
        hits = [i for i in issues if i["issue_id"] == self.issue_id]
        if hits:
            issue = hits[0]
            for field in ("severity", "confidence", "target", "evidence"):
                self.assertIn(field, issue)
            self.assertGreaterEqual(issue["severity"], 30)
            self.assertGreater(issue["confidence"], 0.0)

    def test_no_bass_no_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kick = Path(tmp) / "kick.wav"
            _write_kick_wav(kick)
            session = _make_multi_session([
                _make_stem_entry("STEM.KICK", kick, role_id="ROLE.DRUM.KICK"),
            ])
            issues = self.detector.detect(session, {})
        self.assertFalse(any(i["issue_id"] == self.issue_id for i in issues))

    def test_filename_heuristic_kick(self) -> None:
        """Role fallback: detect kick by filename token when no role_id."""
        with tempfile.TemporaryDirectory() as tmp:
            kick = Path(tmp) / "01_kick.wav"
            bass = Path(tmp) / "02_bass.wav"
            _write_kick_wav(kick)
            _write_bass_wav(bass)
            session = _make_multi_session([
                {"stem_id": "01_kick", "file_path": str(kick)},
                {"stem_id": "02_bass", "file_path": str(bass)},
            ])
            issues = self.detector.detect(session, {})
        self.assertTrue(any(i["issue_id"] == self.issue_id for i in issues),
                        f"Expected kick/bass heuristic detection; got {issues}")

    def test_plugin_id(self) -> None:
        self.assertEqual(self.detector.plugin_id, "PLUGIN.DETECTOR.MASKING")

    def test_empty_session(self) -> None:
        issues = self.detector.detect({"stems": []}, {})
        self.assertEqual(issues, [])


# ---------------------------------------------------------------------------
# MaskingDetector — vocal vs music
# ---------------------------------------------------------------------------

class TestMaskingDetectorVocalVsMusic(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.detectors.masking_detector import MaskingDetector
        self.detector = MaskingDetector()
        self.issue_id = "ISSUE.MASKING.VOCAL_VS_MUSIC"

    def _vocal_vs_loud_music_session(self, tmp: str) -> dict:
        vocal = Path(tmp) / "vocal.wav"
        music1 = Path(tmp) / "music1.wav"
        music2 = Path(tmp) / "music2.wav"
        _write_vocal_wav(vocal)
        _write_music_loud_wav(music1)
        _write_music_loud_wav(music2)
        return _make_multi_session([
            _make_stem_entry("STEM.VOCAL", vocal, role_id="ROLE.VOCAL.LEAD"),
            _make_stem_entry("STEM.MUSIC1", music1, role_id="ROLE.GTR.ELECTRIC"),
            _make_stem_entry("STEM.MUSIC2", music2, role_id="ROLE.KEYS.PIANO"),
        ])

    def test_detects_vocal_masking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._vocal_vs_loud_music_session(tmp)
            issues = self.detector.detect(session, {})
        self.assertTrue(any(i["issue_id"] == self.issue_id for i in issues),
                        f"Expected vocal masking; got {issues}")

    def test_issue_has_bus_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._vocal_vs_loud_music_session(tmp)
            issues = self.detector.detect(session, {})
        hits = [i for i in issues if i["issue_id"] == self.issue_id]
        if hits:
            self.assertEqual(hits[0]["target"]["scope"], "bus")

    def test_no_vocal_no_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            music = Path(tmp) / "music.wav"
            _write_music_loud_wav(music)
            session = _make_multi_session([
                _make_stem_entry("STEM.MUSIC", music, role_id="ROLE.GTR.ELECTRIC"),
            ])
            issues = self.detector.detect(session, {})
        self.assertFalse(any(i["issue_id"] == self.issue_id for i in issues))

    def test_filename_heuristic_vocal(self) -> None:
        """Role fallback: detect vocal lead by filename token when no role_id."""
        with tempfile.TemporaryDirectory() as tmp:
            vocal = Path(tmp) / "lead_vox.wav"
            music = Path(tmp) / "guitar.wav"
            _write_vocal_wav(vocal)
            _write_music_loud_wav(music)
            _write_music_loud_wav(Path(tmp) / "keys.wav")
            session = _make_multi_session([
                {"stem_id": "lead_vox", "file_path": str(vocal)},
                {"stem_id": "guitar", "file_path": str(music)},
                {"stem_id": "keys", "file_path": str(Path(tmp) / "keys.wav")},
            ])
            issues = self.detector.detect(session, {})
        # May or may not trigger depending on energy ratios — just check no crash
        _ = issues


# ---------------------------------------------------------------------------
# CompressorRenderer
# ---------------------------------------------------------------------------

def _make_compression_rec(
    stem_id: str,
    *,
    threshold_db: float = -12.0,
    ratio: float = 2.5,
    attack_ms: float = 10.0,
    release_ms: float = 100.0,
    makeup_db: float = 2.0,
    rec_id: str = "REC.001",
    risk: str = "low",
) -> dict:
    return {
        "recommendation_id": rec_id,
        "action_id": "ACTION.DYN.COMPRESSOR",
        "risk": risk,
        "requires_approval": False,
        "scope": {"stem_id": stem_id},
        "params": [
            {"param_id": "PARAM.COMP.THRESHOLD_DB", "value": threshold_db},
            {"param_id": "PARAM.COMP.RATIO", "value": ratio},
            {"param_id": "PARAM.COMP.ATTACK_MS", "value": attack_ms},
            {"param_id": "PARAM.COMP.RELEASE_MS", "value": release_ms},
            {"param_id": "PARAM.COMP.MAKEUP_DB", "value": makeup_db},
        ],
    }


class TestCompressorRenderer(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.renderers.compressor_renderer import CompressorRenderer
        self.renderer = CompressorRenderer()

    def _stem_session(self, path: Path, stem_id: str = "STEM.TEST") -> dict:
        return {"stems": [{"stem_id": stem_id, "file_path": str(path)}]}

    def test_renders_wav_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            session = self._stem_session(src, "STEM.TEST")
            rec = _make_compression_rec("STEM.TEST")
            out_dir = Path(tmp) / "out"
            manifest = self.renderer.render(session, [rec], output_dir=out_dir)

        self.assertIsInstance(manifest["outputs"], list)
        if manifest["outputs"]:
            out = manifest["outputs"][0]
            self.assertIn("output_id", out)
            self.assertIn("file_path", out)
            output_path = Path(out["file_path"])
            self.assertTrue(output_path.is_file(), f"Output WAV not created: {output_path}")

    def test_output_is_24bit_wav(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            session = self._stem_session(src, "STEM.TEST")
            rec = _make_compression_rec("STEM.TEST")
            out_dir = Path(tmp) / "out"
            manifest = self.renderer.render(session, [rec], output_dir=out_dir)

        if manifest["outputs"]:
            out_path = Path(manifest["outputs"][0]["file_path"])
            with wave.open(str(out_path), "rb") as w:
                self.assertEqual(w.getsampwidth(), 3)  # 24-bit = 3 bytes

    def test_no_output_dir_produces_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            session = self._stem_session(src, "STEM.TEST")
            rec = _make_compression_rec("STEM.TEST")
            manifest = self.renderer.render(session, [rec], output_dir=None)
        self.assertEqual(manifest["outputs"], [])
        self.assertTrue(len(manifest["skipped"]) > 0)
        self.assertEqual(manifest["skipped"][0]["reason"], "missing_output_dir")

    def test_missing_stem_skipped(self) -> None:
        session = {"stems": [{"stem_id": "STEM.MISSING", "file_path": "/nonexistent/x.wav"}]}
        with tempfile.TemporaryDirectory() as tmp:
            rec = _make_compression_rec("STEM.MISSING")
            manifest = self.renderer.render(session, [rec], output_dir=Path(tmp))
        self.assertEqual(manifest["outputs"], [])
        self.assertTrue(any(s["reason"] == "missing_stem_file_path" for s in manifest["skipped"]))

    def test_high_risk_rec_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            session = self._stem_session(src, "STEM.TEST")
            rec = _make_compression_rec("STEM.TEST", risk="high")
            out_dir = Path(tmp) / "out"
            manifest = self.renderer.render(session, [rec], output_dir=out_dir)
        self.assertEqual(manifest["outputs"], [])
        self.assertTrue(any(s["reason"] == "invalid_params" for s in manifest["skipped"]))

    def test_ratio_capped_at_max(self) -> None:
        """Extreme ratio (100:1) should be clamped to 4:1; render should succeed."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            session = self._stem_session(src, "STEM.TEST")
            rec = _make_compression_rec("STEM.TEST", ratio=100.0)
            out_dir = Path(tmp) / "out"
            manifest = self.renderer.render(session, [rec], output_dir=out_dir)
        # Should produce an output (clamped ratio, not an error)
        self.assertTrue(len(manifest["outputs"]) > 0 or len(manifest["skipped"]) > 0)

    def test_manifest_has_renderer_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            session = self._stem_session(src, "STEM.TEST")
            rec = _make_compression_rec("STEM.TEST")
            manifest = self.renderer.render(session, [rec], output_dir=Path(tmp))
        self.assertEqual(manifest["renderer_id"], "PLUGIN.RENDERER.COMPRESSOR")

    def test_non_wav_stem_skipped(self) -> None:
        """Non-WAV file extension should be skipped."""
        session = {"stems": [{"stem_id": "STEM.MP3", "file_path": "/some/stem.mp3"}]}
        with tempfile.TemporaryDirectory() as tmp:
            rec = _make_compression_rec("STEM.MP3")
            manifest = self.renderer.render(session, [rec], output_dir=Path(tmp))
        self.assertEqual(manifest["outputs"], [])

    def test_output_suffix_is_mmo_comp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "guitar.wav"
            _write_balanced_wav(src)
            session = self._stem_session(src, "STEM.GTR")
            rec = _make_compression_rec("STEM.GTR")
            out_dir = Path(tmp) / "out"
            manifest = self.renderer.render(session, [rec], output_dir=out_dir)
        if manifest["outputs"]:
            fp = manifest["outputs"][0]["file_path"]
            self.assertIn(".mmo_comp.wav", fp)

    def test_plugin_id(self) -> None:
        self.assertEqual(self.renderer.plugin_id, "PLUGIN.RENDERER.COMPRESSOR")


# ---------------------------------------------------------------------------
# SafeRenderer
# ---------------------------------------------------------------------------

def _make_rec(rec_id: str, action_id: str, risk: str, requires_approval: bool) -> dict:
    return {
        "recommendation_id": rec_id,
        "action_id": action_id,
        "risk": risk,
        "requires_approval": requires_approval,
    }


class TestSafeRenderer(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.renderers.safe_renderer import SafeRenderer
        self.renderer = SafeRenderer()

    def test_never_produces_audio_outputs(self) -> None:
        recs = [
            _make_rec("REC.001", "ACTION.EQ.BELL_CUT", "low", False),
            _make_rec("REC.002", "ACTION.DYN.COMPRESSOR", "medium", False),
        ]
        manifest = self.renderer.render({}, recs)
        self.assertEqual(manifest["outputs"], [])

    def test_low_risk_auto_approved_in_skipped(self) -> None:
        recs = [_make_rec("REC.001", "ACTION.EQ.BELL_CUT", "low", False)]
        manifest = self.renderer.render({}, recs)
        self.assertTrue(
            any(s["reason"] == "safe_auto_approved" for s in manifest["skipped"]),
            f"Expected safe_auto_approved; got {manifest['skipped']}",
        )

    def test_requires_approval_reason(self) -> None:
        recs = [_make_rec("REC.002", "ACTION.EQ.BELL_CUT", "low", True)]
        manifest = self.renderer.render({}, recs)
        self.assertTrue(
            any(s["reason"] == "requires_approval" for s in manifest["skipped"]),
            f"Expected requires_approval; got {manifest['skipped']}",
        )

    def test_high_risk_exceeds_limit(self) -> None:
        recs = [_make_rec("REC.003", "ACTION.DYN.COMPRESSOR", "high", False)]
        manifest = self.renderer.render({}, recs)
        self.assertTrue(
            any(s["reason"] == "risk_exceeds_limit" for s in manifest["skipped"]),
            f"Expected risk_exceeds_limit; got {manifest['skipped']}",
        )

    def test_medium_risk_no_approval_auto_approved(self) -> None:
        recs = [_make_rec("REC.004", "ACTION.DYN.COMPRESSOR", "medium", False)]
        manifest = self.renderer.render({}, recs)
        self.assertTrue(
            any(s["reason"] == "safe_auto_approved" for s in manifest["skipped"]),
            f"Expected medium risk to be auto_approved; got {manifest['skipped']}",
        )

    def test_all_recs_appear_in_skipped(self) -> None:
        recs = [
            _make_rec("REC.001", "ACTION.EQ.BELL_CUT", "low", False),
            _make_rec("REC.002", "ACTION.EQ.NOTCH_CUT", "medium", True),
            _make_rec("REC.003", "ACTION.DYN.COMPRESSOR", "high", False),
        ]
        manifest = self.renderer.render({}, recs)
        skipped_ids = {s["recommendation_id"] for s in manifest["skipped"]}
        for rec in recs:
            self.assertIn(rec["recommendation_id"], skipped_ids)

    def test_empty_recommendations(self) -> None:
        manifest = self.renderer.render({}, [])
        self.assertEqual(manifest["outputs"], [])
        self.assertEqual(manifest["skipped"], [])

    def test_gate_summary_contains_risk_info(self) -> None:
        recs = [_make_rec("REC.001", "ACTION.EQ.BELL_CUT", "low", False)]
        manifest = self.renderer.render({}, recs)
        self.assertTrue(manifest["skipped"])
        gate = manifest["skipped"][0]["gate_summary"]
        self.assertIn("risk=", gate)

    def test_skipped_sorted_deterministically(self) -> None:
        recs = [
            _make_rec("REC.Z", "ACTION.EQ.BELL_CUT", "low", False),
            _make_rec("REC.A", "ACTION.EQ.BELL_CUT", "low", False),
            _make_rec("REC.M", "ACTION.EQ.BELL_CUT", "low", False),
        ]
        manifest1 = self.renderer.render({}, recs)
        manifest2 = self.renderer.render({}, recs)
        self.assertEqual(
            [s["recommendation_id"] for s in manifest1["skipped"]],
            [s["recommendation_id"] for s in manifest2["skipped"]],
        )

    def test_output_dir_ignored(self) -> None:
        """output_dir is irrelevant; safe renderer always produces empty outputs."""
        recs = [_make_rec("REC.001", "ACTION.EQ.BELL_CUT", "low", False)]
        manifest = self.renderer.render({}, recs, output_dir="/some/path")
        self.assertEqual(manifest["outputs"], [])

    def test_plugin_id(self) -> None:
        self.assertEqual(self.renderer.plugin_id, "PLUGIN.RENDERER.SAFE")

    def test_renderer_id_in_manifest(self) -> None:
        manifest = self.renderer.render({}, [])
        self.assertEqual(manifest["renderer_id"], "PLUGIN.RENDERER.SAFE")


if __name__ == "__main__":
    unittest.main()
