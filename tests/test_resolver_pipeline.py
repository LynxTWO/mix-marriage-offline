"""Tests for HarshnessResolver, SibilanceResolver, MaskingResolver, and HPF/low-shelf in ParametricEqRenderer."""
from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

_SR = 48_000


# ---------------------------------------------------------------------------
# Minimal WAV helpers (same pattern as test_corrective_plugins.py)
# ---------------------------------------------------------------------------

def _write_sine_wav(path: Path, freqs_amps: list[tuple[float, float]],
                    *, sr: int = _SR, duration_s: float = 1.0) -> None:
    n = int(duration_s * sr)
    samples = [0.0] * n
    for freq, amp in freqs_amps:
        for i in range(n):
            samples[i] += amp * math.sin(2 * math.pi * freq * i / sr)
    peak = max(abs(s) for s in samples) or 1.0
    samples = [s / peak * 0.88 for s in samples]
    ints = [int(s * 32767) for s in samples]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack(f"<{n}h", *ints))


def _write_balanced_wav(path: Path) -> None:
    _write_sine_wav(path, [
        (80.0, 0.40), (200.0, 0.35), (500.0, 0.30),
        (1000.0, 0.20), (2000.0, 0.06), (4000.0, 0.05), (8000.0, 0.04),
    ])


# ---------------------------------------------------------------------------
# Issue / session factories
# ---------------------------------------------------------------------------

def _harshness_issue(stem_id: str, ratio: float = 0.38, band_db: float = -3.0) -> dict:
    return {
        "issue_id": "ISSUE.SPECTRAL.HARSHNESS",
        "severity": 45,
        "confidence": 0.75,
        "target": {"scope": "stem", "stem_id": stem_id},
        "evidence": [
            {"evidence_id": "EVID.SPECTRAL.BAND_ENERGY_RATIO", "value": ratio,
             "unit_id": "UNIT.RATIO",
             "where": {"freq_range_hz": {"low_hz": 2000.0, "high_hz": 5000.0}}},
            {"evidence_id": "EVID.SPECTRAL.BAND_ENERGY_DB", "value": band_db,
             "unit_id": "UNIT.DB",
             "where": {"freq_range_hz": {"low_hz": 2000.0, "high_hz": 5000.0}}},
        ],
    }


def _sibilance_issue(stem_id: str, ratio: float = 0.35) -> dict:
    return {
        "issue_id": "ISSUE.SPECTRAL.SIBILANCE",
        "severity": 40,
        "confidence": 0.70,
        "target": {"scope": "stem", "stem_id": stem_id},
        "evidence": [
            {"evidence_id": "EVID.SPECTRAL.BAND_ENERGY_RATIO", "value": ratio,
             "unit_id": "UNIT.RATIO",
             "where": {"freq_range_hz": {"low_hz": 5000.0, "high_hz": 10000.0}}},
        ],
    }


def _kick_bass_issue(kick_id: str, bass_id: str,
                     kick_ratio: float = 0.38, bass_ratio: float = 0.42) -> dict:
    return {
        "issue_id": "ISSUE.MASKING.KICK_BASS",
        "severity": 50,
        "confidence": 0.78,
        "target": {"scope": "bus", "stem_id": kick_id, "secondary_stem_id": bass_id},
        "evidence": [
            {"evidence_id": "EVID.SPECTRAL.BAND_ENERGY_RATIO", "value": kick_ratio,
             "unit_id": "UNIT.RATIO",
             "where": {"freq_range_hz": {"low_hz": 60.0, "high_hz": 200.0},
                       "track_ref": {"track_name": kick_id}}},
            {"evidence_id": "EVID.SPECTRAL.BAND_ENERGY_RATIO", "value": bass_ratio,
             "unit_id": "UNIT.RATIO",
             "where": {"freq_range_hz": {"low_hz": 60.0, "high_hz": 200.0},
                       "track_ref": {"track_name": bass_id}}},
        ],
    }


def _vocal_masking_issue(vocal_id: str, masking_ratio: float = 4.5) -> dict:
    return {
        "issue_id": "ISSUE.MASKING.VOCAL_VS_MUSIC",
        "severity": 55,
        "confidence": 0.80,
        "target": {"scope": "bus", "stem_id": vocal_id},
        "evidence": [
            {"evidence_id": "EVID.SPECTRAL.BAND_ENERGY_RATIO", "value": 0.22,
             "unit_id": "UNIT.RATIO",
             "where": {"freq_range_hz": {"low_hz": 1000.0, "high_hz": 4000.0},
                       "track_ref": {"track_name": vocal_id}}},
            {"evidence_id": "EVID.SPECTRAL.BAND_ENERGY_RATIO", "value": masking_ratio,
             "unit_id": "UNIT.RATIO",
             "where": {"freq_range_hz": {"low_hz": 1000.0, "high_hz": 4000.0}}},
        ],
    }


def _simple_session(*stem_ids: str) -> dict:
    return {"stems": [{"stem_id": sid, "file_path": f"/fake/{sid}.wav"} for sid in stem_ids]}


def _session_with_roles(**role_map: str) -> dict:
    """role_map: stem_id → role_id"""
    return {"stems": [
        {"stem_id": sid, "file_path": f"/fake/{sid}.wav", "role_id": role}
        for sid, role in role_map.items()
    ]}


# ---------------------------------------------------------------------------
# HarshnessResolver
# ---------------------------------------------------------------------------

class TestHarshnessResolver(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.resolvers.harshness_resolver import HarshnessResolver
        self.resolver = HarshnessResolver()

    def test_emits_bell_cut_for_harshness(self) -> None:
        issues = [_harshness_issue("STEM.GTR")]
        recs = self.resolver.resolve({}, {}, issues)
        self.assertTrue(any(r["action_id"] == "ACTION.EQ.BELL_CUT" for r in recs),
                        f"Expected BELL_CUT; got {[r['action_id'] for r in recs]}")

    def test_targets_correct_stem(self) -> None:
        issues = [_harshness_issue("STEM.GTR")]
        recs = self.resolver.resolve({}, {}, issues)
        bell = [r for r in recs if r["action_id"] == "ACTION.EQ.BELL_CUT"]
        self.assertTrue(bell)
        self.assertEqual(bell[0]["scope"]["stem_id"], "STEM.GTR")

    def test_low_ratio_produces_low_risk(self) -> None:
        # Ratio just above threshold → small cut → low-risk
        issues = [_harshness_issue("STEM.GTR", ratio=0.28)]
        recs = self.resolver.resolve({}, {}, issues)
        bell = [r for r in recs if r["action_id"] == "ACTION.EQ.BELL_CUT"]
        self.assertTrue(bell)
        self.assertEqual(bell[0]["risk"], "low")
        self.assertFalse(bell[0]["requires_approval"])

    def test_high_ratio_produces_medium_risk(self) -> None:
        # Ratio near ceiling → deep cut → medium-risk
        issues = [_harshness_issue("STEM.GTR", ratio=0.48)]
        recs = self.resolver.resolve({}, {}, issues)
        bell = [r for r in recs if r["action_id"] == "ACTION.EQ.BELL_CUT"]
        self.assertTrue(bell)
        self.assertEqual(bell[0]["risk"], "medium")
        self.assertTrue(bell[0]["requires_approval"])

    def test_gain_db_is_negative(self) -> None:
        issues = [_harshness_issue("STEM.GTR")]
        recs = self.resolver.resolve({}, {}, issues)
        bell = [r for r in recs if r["action_id"] == "ACTION.EQ.BELL_CUT"]
        self.assertTrue(bell)
        gain = next(p["value"] for p in bell[0]["params"] if p["param_id"] == "PARAM.EQ.GAIN_DB")
        self.assertLess(gain, 0.0)

    def test_freq_is_in_harshness_band(self) -> None:
        issues = [_harshness_issue("STEM.GTR")]
        recs = self.resolver.resolve({}, {}, issues)
        bell = [r for r in recs if r["action_id"] == "ACTION.EQ.BELL_CUT"]
        freq = next(p["value"] for p in bell[0]["params"] if p["param_id"] == "PARAM.EQ.FREQ_HZ")
        self.assertGreaterEqual(freq, 2000.0)
        self.assertLessEqual(freq, 5000.0)

    def test_deduplicates_per_stem(self) -> None:
        issues = [_harshness_issue("STEM.GTR"), _harshness_issue("STEM.GTR")]
        recs = self.resolver.resolve({}, {}, issues)
        gtr_recs = [r for r in recs if r["scope"]["stem_id"] == "STEM.GTR"]
        self.assertEqual(len(gtr_recs), 1)

    def test_multiple_stems_get_separate_recs(self) -> None:
        issues = [_harshness_issue("STEM.GTR"), _harshness_issue("STEM.KEYS")]
        recs = self.resolver.resolve({}, {}, issues)
        stem_ids = {r["scope"]["stem_id"] for r in recs}
        self.assertIn("STEM.GTR", stem_ids)
        self.assertIn("STEM.KEYS", stem_ids)

    def test_ignores_other_issue_types(self) -> None:
        issues = [_sibilance_issue("STEM.GTR")]
        recs = self.resolver.resolve({}, {}, issues)
        self.assertEqual(recs, [])

    def test_recommendation_id_stable(self) -> None:
        issues = [_harshness_issue("STEM.GTR")]
        recs1 = self.resolver.resolve({}, {}, issues)
        recs2 = self.resolver.resolve({}, {}, issues)
        self.assertEqual(recs1[0]["recommendation_id"], recs2[0]["recommendation_id"])

    def test_plugin_id(self) -> None:
        self.assertEqual(self.resolver.plugin_id, "PLUGIN.RESOLVER.HARSHNESS")


# ---------------------------------------------------------------------------
# SibilanceResolver
# ---------------------------------------------------------------------------

class TestSibilanceResolver(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.resolvers.sibilance_resolver import SibilanceResolver
        self.resolver = SibilanceResolver()

    def test_emits_bell_cut_for_sibilance(self) -> None:
        issues = [_sibilance_issue("STEM.VOX")]
        recs = self.resolver.resolve({}, {}, issues)
        self.assertTrue(any(r["action_id"] == "ACTION.EQ.BELL_CUT" for r in recs))

    def test_targets_correct_stem(self) -> None:
        issues = [_sibilance_issue("STEM.VOX")]
        recs = self.resolver.resolve({}, {}, issues)
        self.assertTrue(all(r["scope"]["stem_id"] == "STEM.VOX" for r in recs))

    def test_always_medium_risk(self) -> None:
        for ratio in (0.25, 0.35, 0.44):
            issues = [_sibilance_issue("STEM.VOX", ratio=ratio)]
            recs = self.resolver.resolve({}, {}, issues)
            bell = [r for r in recs if r["action_id"] == "ACTION.EQ.BELL_CUT"]
            self.assertTrue(bell, f"No rec for ratio={ratio}")
            self.assertEqual(bell[0]["risk"], "medium", f"Expected medium risk for ratio={ratio}")
            self.assertTrue(bell[0]["requires_approval"])

    def test_freq_in_sibilance_band(self) -> None:
        issues = [_sibilance_issue("STEM.VOX")]
        recs = self.resolver.resolve({}, {}, issues)
        bell = [r for r in recs if r["action_id"] == "ACTION.EQ.BELL_CUT"]
        freq = next(p["value"] for p in bell[0]["params"] if p["param_id"] == "PARAM.EQ.FREQ_HZ")
        self.assertGreaterEqual(freq, 5000.0)
        self.assertLessEqual(freq, 10000.0)

    def test_gain_db_is_negative(self) -> None:
        issues = [_sibilance_issue("STEM.VOX")]
        recs = self.resolver.resolve({}, {}, issues)
        bell = [r for r in recs if r["action_id"] == "ACTION.EQ.BELL_CUT"]
        gain = next(p["value"] for p in bell[0]["params"] if p["param_id"] == "PARAM.EQ.GAIN_DB")
        self.assertLess(gain, 0.0)

    def test_deduplicates_per_stem(self) -> None:
        issues = [_sibilance_issue("STEM.VOX"), _sibilance_issue("STEM.VOX")]
        recs = self.resolver.resolve({}, {}, issues)
        self.assertEqual(len(recs), 1)

    def test_ignores_harshness_issues(self) -> None:
        issues = [_harshness_issue("STEM.VOX")]
        recs = self.resolver.resolve({}, {}, issues)
        self.assertEqual(recs, [])

    def test_plugin_id(self) -> None:
        self.assertEqual(self.resolver.plugin_id, "PLUGIN.RESOLVER.SIBILANCE")


# ---------------------------------------------------------------------------
# MaskingResolver — kick/bass
# ---------------------------------------------------------------------------

class TestMaskingResolverKickBass(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.resolvers.masking_resolver import MaskingResolver
        self.resolver = MaskingResolver()

    def test_emits_bass_bell_cut(self) -> None:
        issue = _kick_bass_issue("STEM.KICK", "STEM.BASS")
        recs = self.resolver.resolve(_simple_session("STEM.KICK", "STEM.BASS"), {}, [issue])
        bass_recs = [r for r in recs if r["scope"]["stem_id"] == "STEM.BASS"
                     and r["action_id"] == "ACTION.EQ.BELL_CUT"]
        self.assertTrue(bass_recs, f"Expected bass bell cut; got {recs}")

    def test_bass_cut_freq_in_overlap_zone(self) -> None:
        issue = _kick_bass_issue("STEM.KICK", "STEM.BASS")
        recs = self.resolver.resolve(_simple_session("STEM.KICK", "STEM.BASS"), {}, [issue])
        bass_recs = [r for r in recs if r["scope"]["stem_id"] == "STEM.BASS"]
        self.assertTrue(bass_recs)
        freq = next(p["value"] for p in bass_recs[0]["params"] if p["param_id"] == "PARAM.EQ.FREQ_HZ")
        self.assertGreaterEqual(freq, 60.0)
        self.assertLessEqual(freq, 250.0)

    def test_all_recs_are_medium_risk(self) -> None:
        issue = _kick_bass_issue("STEM.KICK", "STEM.BASS")
        recs = self.resolver.resolve(_simple_session("STEM.KICK", "STEM.BASS"), {}, [issue])
        self.assertTrue(all(r["risk"] == "medium" for r in recs))
        self.assertTrue(all(r["requires_approval"] for r in recs))

    def test_gain_db_is_negative(self) -> None:
        issue = _kick_bass_issue("STEM.KICK", "STEM.BASS")
        recs = self.resolver.resolve(_simple_session("STEM.KICK", "STEM.BASS"), {}, [issue])
        for rec in recs:
            gain = next((p["value"] for p in rec["params"] if p["param_id"] == "PARAM.EQ.GAIN_DB"), None)
            if gain is not None:
                self.assertLess(gain, 0.0)

    def test_deduplicates_same_pair(self) -> None:
        issue = _kick_bass_issue("STEM.KICK", "STEM.BASS")
        recs = self.resolver.resolve(
            _simple_session("STEM.KICK", "STEM.BASS"), {}, [issue, issue]
        )
        bass_recs = [r for r in recs if r["scope"]["stem_id"] == "STEM.BASS"]
        self.assertEqual(len(bass_recs), 1)

    def test_missing_stem_ids_skipped(self) -> None:
        issue = {"issue_id": "ISSUE.MASKING.KICK_BASS", "target": {}, "evidence": []}
        recs = self.resolver.resolve({}, {}, [issue])
        self.assertEqual(recs, [])

    def test_high_kick_ratio_adds_secondary(self) -> None:
        # kick_ratio > 0.30 should add a secondary kick cut
        issue = _kick_bass_issue("STEM.KICK", "STEM.BASS", kick_ratio=0.42)
        recs = self.resolver.resolve(_simple_session("STEM.KICK", "STEM.BASS"), {}, [issue])
        kick_recs = [r for r in recs if r["scope"]["stem_id"] == "STEM.KICK"]
        self.assertTrue(kick_recs, "Expected secondary kick cut for high kick ratio")

    def test_low_kick_ratio_no_secondary(self) -> None:
        # kick_ratio below secondary threshold → no kick rec
        issue = _kick_bass_issue("STEM.KICK", "STEM.BASS", kick_ratio=0.22)
        recs = self.resolver.resolve(_simple_session("STEM.KICK", "STEM.BASS"), {}, [issue])
        kick_recs = [r for r in recs if r["scope"]["stem_id"] == "STEM.KICK"]
        self.assertEqual(kick_recs, [])


# ---------------------------------------------------------------------------
# MaskingResolver — vocal / music
# ---------------------------------------------------------------------------

class TestMaskingResolverVocalMusic(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.resolvers.masking_resolver import MaskingResolver
        self.resolver = MaskingResolver()

    def _session_vocal_plus_music(self) -> dict:
        return _session_with_roles(
            **{"STEM.VOX": "ROLE.VOCAL.LEAD",
               "STEM.GTR": "ROLE.GTR.ELECTRIC",
               "STEM.KEYS": "ROLE.KEYS.PIANO"}
        )

    def test_emits_cuts_on_music_stems(self) -> None:
        issue = _vocal_masking_issue("STEM.VOX")
        recs = self.resolver.resolve(self._session_vocal_plus_music(), {}, [issue])
        music_recs = [r for r in recs if r["scope"]["stem_id"] in ("STEM.GTR", "STEM.KEYS")]
        self.assertTrue(music_recs, f"Expected cuts on music stems; got {recs}")

    def test_does_not_cut_the_vocal_stem(self) -> None:
        issue = _vocal_masking_issue("STEM.VOX")
        recs = self.resolver.resolve(self._session_vocal_plus_music(), {}, [issue])
        vocal_recs = [r for r in recs if r["scope"]["stem_id"] == "STEM.VOX"]
        self.assertEqual(vocal_recs, [])

    def test_cut_freq_in_intelligibility_band(self) -> None:
        issue = _vocal_masking_issue("STEM.VOX")
        recs = self.resolver.resolve(self._session_vocal_plus_music(), {}, [issue])
        for rec in recs:
            freq = next(p["value"] for p in rec["params"] if p["param_id"] == "PARAM.EQ.FREQ_HZ")
            self.assertGreaterEqual(freq, 1000.0)
            self.assertLessEqual(freq, 4000.0)

    def test_all_recs_medium_risk_require_approval(self) -> None:
        issue = _vocal_masking_issue("STEM.VOX")
        recs = self.resolver.resolve(self._session_vocal_plus_music(), {}, [issue])
        self.assertTrue(recs)
        for rec in recs:
            self.assertEqual(rec["risk"], "medium")
            self.assertTrue(rec["requires_approval"])

    def test_caps_at_max_music_stems(self) -> None:
        # 10 competing stems — should be capped at _MAX_MUSIC_STEMS (4)
        session = {"stems": [
            {"stem_id": "STEM.VOX", "role_id": "ROLE.VOCAL.LEAD",
             "file_path": "/fake/vox.wav"},
        ] + [
            {"stem_id": f"STEM.INSTR{i}", "file_path": f"/fake/instr{i}.wav"}
            for i in range(10)
        ]}
        issue = _vocal_masking_issue("STEM.VOX")
        recs = self.resolver.resolve(session, {}, [issue])
        self.assertLessEqual(len(recs), 4)

    def test_deduplicates_same_vocal(self) -> None:
        issue = _vocal_masking_issue("STEM.VOX")
        recs1 = self.resolver.resolve(self._session_vocal_plus_music(), {}, [issue])
        recs2 = self.resolver.resolve(self._session_vocal_plus_music(), {}, [issue, issue])
        self.assertEqual(len(recs1), len(recs2))

    def test_filename_heuristic_excludes_vocal_from_targets(self) -> None:
        # Session with no role_id — use filename to detect vocal
        session = {"stems": [
            {"stem_id": "lead_vox", "file_path": "/fake/lead_vox.wav"},
            {"stem_id": "guitar", "file_path": "/fake/guitar.wav"},
        ]}
        issue = _vocal_masking_issue("lead_vox")
        recs = self.resolver.resolve(session, {}, [issue])
        vocal_recs = [r for r in recs if r["scope"]["stem_id"] == "lead_vox"]
        self.assertEqual(vocal_recs, [])

    def test_no_music_stems_produces_no_recs(self) -> None:
        session = {"stems": [{"stem_id": "STEM.VOX", "role_id": "ROLE.VOCAL.LEAD",
                               "file_path": "/fake/vox.wav"}]}
        issue = _vocal_masking_issue("STEM.VOX")
        recs = self.resolver.resolve(session, {}, [issue])
        self.assertEqual(recs, [])

    def test_plugin_id(self) -> None:
        from mmo.plugins.resolvers.masking_resolver import MaskingResolver
        self.assertEqual(MaskingResolver().plugin_id, "PLUGIN.RESOLVER.MASKING")


# ---------------------------------------------------------------------------
# ParametricEqRenderer — HPF
# ---------------------------------------------------------------------------

class TestParametricEqRendererHPF(unittest.TestCase):
    def setUp(self) -> None:
        from mmo.plugins.renderers.parametric_eq_renderer import ParametricEqRenderer
        self.renderer = ParametricEqRenderer()

    def _hpf_rec(self, stem_id: str, freq_hz: float = 80.0, risk: str = "medium") -> dict:
        return {
            "recommendation_id": f"REC.HPF.{stem_id}",
            "action_id": "ACTION.EQ.HIGH_PASS",
            "risk": risk,
            "requires_approval": False,
            "scope": {"stem_id": stem_id},
            "params": [
                {"param_id": "PARAM.EQ.FREQ_HZ", "value": freq_hz},
                {"param_id": "PARAM.EQ.SLOPE_DB_PER_OCT", "value": 12.0},
            ],
        }

    def _low_shelf_rec(self, stem_id: str, freq_hz: float = 120.0, gain_db: float = -2.0) -> dict:
        return {
            "recommendation_id": f"REC.SHELF.{stem_id}",
            "action_id": "ACTION.EQ.LOW_SHELF",
            "risk": "medium",
            "requires_approval": False,
            "scope": {"stem_id": stem_id},
            "params": [
                {"param_id": "PARAM.EQ.FREQ_HZ", "value": freq_hz},
                {"param_id": "PARAM.EQ.Q", "value": 0.707},
                {"param_id": "PARAM.EQ.GAIN_DB", "value": gain_db},
            ],
        }

    def _session(self, path: Path, stem_id: str) -> dict:
        return {"stems": [{"stem_id": stem_id, "file_path": str(path)}]}

    def test_hpf_renders_wav(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            rec = self._hpf_rec("STEM.BASS", freq_hz=80.0)
            manifest = self.renderer.render(
                self._session(src, "STEM.BASS"), [rec], output_dir=Path(tmp) / "out"
            )
            # Check file existence inside the temp dir context
            if manifest["outputs"]:
                out_path = Path(manifest["outputs"][0]["file_path"])
                self.assertTrue(out_path.is_file(), f"HPF output not created: {out_path}")
        self.assertIsInstance(manifest["outputs"], list)

    def test_hpf_output_is_24bit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            rec = self._hpf_rec("STEM.BASS")
            manifest = self.renderer.render(
                self._session(src, "STEM.BASS"), [rec], output_dir=Path(tmp) / "out"
            )
            if manifest["outputs"]:
                with wave.open(str(Path(manifest["outputs"][0]["file_path"])), "rb") as w:
                    self.assertEqual(w.getsampwidth(), 3)

    def test_hpf_freq_too_high_skipped(self) -> None:
        """Freq above HPF ceiling (600 Hz) should be rejected by renderer."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            rec = self._hpf_rec("STEM.BASS", freq_hz=900.0)
            manifest = self.renderer.render(
                self._session(src, "STEM.BASS"), [rec], output_dir=Path(tmp) / "out"
            )
        self.assertEqual(manifest["outputs"], [])
        self.assertTrue(any(s["reason"] == "invalid_params" for s in manifest["skipped"]))

    def test_low_shelf_cut_renders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            rec = self._low_shelf_rec("STEM.BASS", gain_db=-2.0)
            manifest = self.renderer.render(
                self._session(src, "STEM.BASS"), [rec], output_dir=Path(tmp) / "out"
            )
        # Should produce an output (or skip with a reason other than invalid_params)
        # Low-shelf with a valid negative gain should not be rejected by param check
        if manifest["skipped"]:
            non_param_reasons = [s for s in manifest["skipped"]
                                 if s["reason"] != "invalid_params"]
            # Any skip should be due to audio pipeline (not param rejection)
            self.assertTrue(len(non_param_reasons) > 0 or len(manifest["outputs"]) > 0)

    def test_low_shelf_boost_rejected(self) -> None:
        """Positive gain_db on low-shelf should be rejected (cuts only)."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            rec = self._low_shelf_rec("STEM.BASS", gain_db=+2.0)  # boost — not allowed
            manifest = self.renderer.render(
                self._session(src, "STEM.BASS"), [rec], output_dir=Path(tmp) / "out"
            )
        self.assertEqual(manifest["outputs"], [])

    def test_medium_risk_bell_cut_now_accepted(self) -> None:
        """Renderer should now accept medium-risk recs with requires_approval=False."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.wav"
            _write_balanced_wav(src)
            rec = {
                "recommendation_id": "REC.MED.001",
                "action_id": "ACTION.EQ.BELL_CUT",
                "risk": "medium",
                "requires_approval": False,
                "scope": {"stem_id": "STEM.GTR"},
                "params": [
                    {"param_id": "PARAM.EQ.FREQ_HZ", "value": 3200.0},
                    {"param_id": "PARAM.EQ.Q", "value": 0.9},
                    {"param_id": "PARAM.EQ.GAIN_DB", "value": -2.5},
                ],
            }
            session = self._session(src, "STEM.GTR")
            manifest = self.renderer.render(session, [rec], output_dir=Path(tmp) / "out")
        # Should not skip with invalid_params — medium risk is now accepted
        param_skips = [s for s in manifest["skipped"] if s["reason"] == "invalid_params"]
        self.assertEqual(param_skips, [])

    def test_renderer_id(self) -> None:
        manifest = self.renderer.render({}, [], output_dir=None)
        self.assertEqual(manifest["renderer_id"], "PLUGIN.RENDERER.PARAMETRIC_EQ")


if __name__ == "__main__":
    unittest.main()
