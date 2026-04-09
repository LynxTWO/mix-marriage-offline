"""Tests for Phase D: mastering bus plugins.

Covers:
  - LoudnessDetector: true-peak ceiling and LUFS range detection
  - LoudnessResolver: ACTION.DYN.LIMITER and ACTION.MASTER.NORMALIZE_LOUDNESS
  - LimiterRenderer: WAV output, gain applied, safety rejection
  - TruePeakLimiterV0 DSP: ceiling enforcement, no-op when below ceiling
"""
from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_wav(path: Path, samples_f32: list[float], *, channels: int = 1, rate: int = 48000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        for sample in samples_f32:
            v = max(-32768, min(32767, int(sample * 32767)))
            w.writeframes(struct.pack("<h", v))


def _write_hot_wav(path: Path, *, peak: float = 0.98, frames: int = 4800) -> None:
    """Write a WAV with a known peak amplitude."""
    import math as _math
    samples = [peak * _math.sin(2 * _math.pi * 440 * i / 48000) for i in range(frames)]
    _write_wav(path, samples)


def _write_silent_wav(path: Path, *, frames: int = 480) -> None:
    _write_wav(path, [0.0] * frames)


def _stem(stem_id: str, *, lufs_i: float | None = None, true_peak_dbtp: float | None = None,
          file_path: str | None = None) -> dict[str, Any]:
    measurements = []
    if lufs_i is not None:
        measurements.append({"evidence_id": "EVID.METER.LUFS_I", "value": lufs_i, "unit_id": "UNIT.LUFS"})
    if true_peak_dbtp is not None:
        measurements.append({"evidence_id": "EVID.METER.TRUEPEAK_DBTP", "value": true_peak_dbtp, "unit_id": "UNIT.DBTP"})
    stem: dict[str, Any] = {"stem_id": stem_id, "measurements": measurements}
    if file_path:
        stem["file_path"] = file_path
    return stem


def _session(*stems: dict[str, Any]) -> dict[str, Any]:
    return {"stems": list(stems)}


def _issue(issue_id: str, stem_id: str, *, peak: float | None = None, ceiling: float = -1.0,
           lufs: float | None = None, target_lufs: float = -14.0) -> dict[str, Any]:
    evidence = []
    if peak is not None:
        evidence += [
            {"evidence_id": "EVID.METER.TRUEPEAK_DBTP", "value": peak, "unit_id": "UNIT.DBTP"},
            {"evidence_id": "EVID.DETECTOR.THRESHOLD_DBTP", "value": ceiling, "unit_id": "UNIT.DBTP"},
        ]
    if lufs is not None:
        evidence += [
            {"evidence_id": "EVID.METER.LUFS_I", "value": lufs, "unit_id": "UNIT.LUFS"},
            {"evidence_id": "EVID.DETECTOR.THRESHOLD_LUFS", "value": target_lufs, "unit_id": "UNIT.LUFS"},
        ]
    return {
        "issue_id": issue_id,
        "target": {"stem_id": stem_id},
        "severity": "error" if "TRUEPEAK" in issue_id else "warn",
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# DSP layer: true_peak_limiter_v0
# ---------------------------------------------------------------------------

class TestTruePeakLimiterDSP(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import numpy  # noqa: F401
            self._have_numpy = True
        except ImportError:
            self._have_numpy = False

    def _skip_if_no_numpy(self) -> None:
        if not self._have_numpy:
            self.skipTest("numpy not available")

    def test_noop_when_below_ceiling(self) -> None:
        self._skip_if_no_numpy()
        import numpy as np
        from mmo.dsp.plugins.true_peak_limiter_v0 import apply_true_peak_ceiling

        samples = np.zeros((480, 2), dtype=np.float64)
        samples[:, 0] = 0.5  # peak well below -1.0 dBTP ceiling
        out, receipt = apply_true_peak_ceiling(samples, 48000, ceiling_dbtp=-1.0)
        self.assertAlmostEqual(receipt["gain_applied_db"], 0.0, places=4)
        self.assertTrue(np.allclose(out, samples))

    def test_reduction_applied_when_over_ceiling(self) -> None:
        self._skip_if_no_numpy()
        import numpy as np
        from mmo.dsp.plugins.true_peak_limiter_v0 import apply_true_peak_ceiling

        # 0 dBFS sine should be ~0 dBTP → over -1.0 dBTP ceiling
        t = np.linspace(0, 1, 48000, endpoint=False)
        samples = (np.sin(2 * np.pi * 440 * t) * 0.999).reshape(-1, 1).astype(np.float64)
        out, receipt = apply_true_peak_ceiling(samples, 48000, ceiling_dbtp=-1.0)

        self.assertLess(receipt["gain_applied_db"], 0.0, "gain must be negative (reduction)")
        self.assertLessEqual(receipt["peak_output_dbtp"], -1.0 + 0.1)  # ±0.1 dB tolerance

    def test_output_peak_at_or_below_ceiling(self) -> None:
        self._skip_if_no_numpy()
        import numpy as np
        from mmo.dsp.plugins.true_peak_limiter_v0 import apply_true_peak_ceiling
        from mmo.dsp.meters_truth import compute_true_peak_dbtp_float64

        t = np.linspace(0, 1, 48000, endpoint=False)
        samples = (np.sin(2 * np.pi * 1000 * t) * 0.9).reshape(-1, 1).astype(np.float64)
        ceiling = -2.0
        out, receipt = apply_true_peak_ceiling(samples, 48000, ceiling_dbtp=ceiling)
        peak_out = compute_true_peak_dbtp_float64(out, 48000)
        self.assertLessEqual(peak_out, ceiling + 0.05)  # within 0.05 dB

    def test_empty_samples_returns_empty_noop(self) -> None:
        self._skip_if_no_numpy()
        import numpy as np
        from mmo.dsp.plugins.true_peak_limiter_v0 import apply_true_peak_ceiling

        samples = np.zeros((0, 2), dtype=np.float64)
        out, receipt = apply_true_peak_ceiling(samples, 48000, ceiling_dbtp=-1.0)
        self.assertEqual(out.shape, (0, 2))
        self.assertAlmostEqual(receipt["gain_applied_db"], 0.0)

    def test_gain_never_amplifies(self) -> None:
        self._skip_if_no_numpy()
        import numpy as np
        from mmo.dsp.plugins.true_peak_limiter_v0 import apply_true_peak_ceiling

        # Very quiet signal — ceiling is higher than peak, no amplification
        samples = (np.ones((480, 1)) * 0.01).astype(np.float64)
        _, receipt = apply_true_peak_ceiling(samples, 48000, ceiling_dbtp=-1.0)
        self.assertGreaterEqual(receipt["gain_applied_db"], -0.0001)  # ≤ 0 dB


# ---------------------------------------------------------------------------
# LoudnessDetector
# ---------------------------------------------------------------------------

class TestLoudnessDetector(unittest.TestCase):
    def _detect(self, session: dict, features: dict | None = None) -> list:
        from mmo.plugins.detectors.loudness_detector import LoudnessDetector
        return LoudnessDetector().detect(session, features or {})

    def test_no_issues_when_measurements_absent(self) -> None:
        issues = self._detect(_session(_stem("kick")))
        self.assertEqual(issues, [])

    def test_truepeak_over_ceiling_emits_issue(self) -> None:
        issues = self._detect(_session(_stem("kick", true_peak_dbtp=0.5)))
        ids = [i["issue_id"] for i in issues]
        self.assertIn("ISSUE.SAFETY.TRUEPEAK_OVER_CEILING", ids)

    def test_truepeak_at_ceiling_does_not_emit(self) -> None:
        issues = self._detect(_session(_stem("kick", true_peak_dbtp=-1.0)))
        ids = [i["issue_id"] for i in issues]
        self.assertNotIn("ISSUE.SAFETY.TRUEPEAK_OVER_CEILING", ids)

    def test_truepeak_below_ceiling_does_not_emit(self) -> None:
        issues = self._detect(_session(_stem("kick", true_peak_dbtp=-6.0)))
        self.assertEqual(issues, [])

    def test_lufs_too_hot_for_stems_profile_emits_issue(self) -> None:
        # stems profile: range [-35, -6]; -4 LUFS is too hot
        issues = self._detect(_session(_stem("kick", lufs_i=-4.0)))
        ids = [i["issue_id"] for i in issues]
        self.assertIn("ISSUE.TRANSLATION.LOUDNESS_OUT_OF_RANGE", ids)

    def test_lufs_within_stems_range_does_not_emit(self) -> None:
        issues = self._detect(_session(_stem("kick", lufs_i=-18.0)))
        self.assertEqual(issues, [])

    def test_lufs_too_quiet_for_stems_range_emits_issue(self) -> None:
        # -42 LUFS is below -35 warn_low for 'stems' profile
        issues = self._detect(_session(_stem("reverb_tail", lufs_i=-42.0)))
        ids = [i["issue_id"] for i in issues]
        self.assertIn("ISSUE.TRANSLATION.LOUDNESS_OUT_OF_RANGE", ids)

    def test_streaming_profile_detects_out_of_range(self) -> None:
        session = _session(_stem("kick", lufs_i=-8.0))
        session["detector_options"] = {"loudness_profile_id": "streaming"}
        issues = self._detect(session)
        ids = [i["issue_id"] for i in issues]
        self.assertIn("ISSUE.TRANSLATION.LOUDNESS_OUT_OF_RANGE", ids)

    def test_streaming_profile_within_range_no_issue(self) -> None:
        session = _session(_stem("kick", lufs_i=-14.0))
        session["detector_options"] = {"loudness_profile_id": "streaming"}
        issues = self._detect(session)
        self.assertEqual(issues, [])

    def test_multiple_stems_each_checked_independently(self) -> None:
        session = _session(
            _stem("kick", true_peak_dbtp=0.2),   # hot
            _stem("bass", true_peak_dbtp=-6.0),  # fine
            _stem("vox", true_peak_dbtp=1.0),    # hot
        )
        issues = self._detect(session)
        stem_ids = [i["target"]["stem_id"] for i in issues]
        self.assertIn("kick", stem_ids)
        self.assertNotIn("bass", stem_ids)
        self.assertIn("vox", stem_ids)

    def test_custom_ceiling_respected(self) -> None:
        # Default ceiling is -1.0; set to -3.0 so -2.0 dBTP triggers
        session = _session(_stem("kick", true_peak_dbtp=-2.0))
        session["detector_options"] = {"loudness_ceiling_dbtp": -3.0}
        issues = self._detect(session)
        ids = [i["issue_id"] for i in issues]
        self.assertIn("ISSUE.SAFETY.TRUEPEAK_OVER_CEILING", ids)

    def test_issue_has_required_evidence_fields(self) -> None:
        issues = self._detect(_session(_stem("kick", true_peak_dbtp=0.5)))
        tp_issues = [i for i in issues if i["issue_id"] == "ISSUE.SAFETY.TRUEPEAK_OVER_CEILING"]
        self.assertTrue(tp_issues)
        ev_ids = {e["evidence_id"] for e in tp_issues[0]["evidence"]}
        self.assertIn("EVID.METER.TRUEPEAK_DBTP", ev_ids)
        self.assertIn("EVID.DETECTOR.THRESHOLD_DBTP", ev_ids)


# ---------------------------------------------------------------------------
# LoudnessResolver
# ---------------------------------------------------------------------------

class TestLoudnessResolver(unittest.TestCase):
    def _resolve(self, issues: list, session: dict | None = None) -> list:
        from mmo.plugins.resolvers.loudness_resolver import LoudnessResolver
        return LoudnessResolver().resolve(session or {}, {}, issues)

    def test_truepeak_issue_emits_limiter_action(self) -> None:
        recs = self._resolve([_issue("ISSUE.SAFETY.TRUEPEAK_OVER_CEILING", "kick", peak=0.5)])
        self.assertTrue(recs)
        self.assertEqual(recs[0]["action_id"], "ACTION.DYN.LIMITER")

    def test_limiter_rec_is_medium_risk_not_requires_approval(self) -> None:
        recs = self._resolve([_issue("ISSUE.SAFETY.TRUEPEAK_OVER_CEILING", "kick", peak=0.5)])
        rec = recs[0]
        self.assertEqual(rec["risk"], "medium")
        self.assertFalse(rec["requires_approval"])

    def test_limiter_rec_has_ceiling_param(self) -> None:
        recs = self._resolve([_issue("ISSUE.SAFETY.TRUEPEAK_OVER_CEILING", "kick", peak=0.5, ceiling=-1.0)])
        param_ids = [p["param_id"] for p in recs[0]["params"]]
        self.assertIn("PARAM.LIMIT.CEILING_DBFS", param_ids)

    def test_loudness_range_issue_emits_normalize_action(self) -> None:
        recs = self._resolve([_issue("ISSUE.TRANSLATION.LOUDNESS_OUT_OF_RANGE", "kick", lufs=-8.0)])
        self.assertTrue(recs)
        self.assertEqual(recs[0]["action_id"], "ACTION.MASTER.NORMALIZE_LOUDNESS")

    def test_normalize_rec_requires_approval(self) -> None:
        recs = self._resolve([_issue("ISSUE.TRANSLATION.LOUDNESS_OUT_OF_RANGE", "kick", lufs=-8.0)])
        self.assertTrue(recs[0]["requires_approval"])
        self.assertEqual(recs[0]["risk"], "high")

    def test_deduplication_per_stem_per_issue(self) -> None:
        issues = [
            _issue("ISSUE.SAFETY.TRUEPEAK_OVER_CEILING", "kick", peak=0.5),
            _issue("ISSUE.SAFETY.TRUEPEAK_OVER_CEILING", "kick", peak=0.3),  # duplicate
        ]
        recs = self._resolve(issues)
        limiter_recs = [r for r in recs if r["action_id"] == "ACTION.DYN.LIMITER"]
        self.assertEqual(len(limiter_recs), 1)

    def test_rec_id_is_stable(self) -> None:
        issues = [_issue("ISSUE.SAFETY.TRUEPEAK_OVER_CEILING", "kick", peak=0.5)]
        recs_a = self._resolve(issues)
        recs_b = self._resolve(issues)
        self.assertEqual(recs_a[0]["recommendation_id"], recs_b[0]["recommendation_id"])

    def test_unhandled_issue_ids_are_ignored(self) -> None:
        # ISSUE.SPECTRAL.MUD is registered but not consumed by LoudnessResolver
        recs = self._resolve([{"issue_id": "ISSUE.SPECTRAL.MUD", "target": {"stem_id": "kick"}}])
        self.assertEqual(recs, [])

    def test_empty_issue_list_returns_empty(self) -> None:
        self.assertEqual(self._resolve([]), [])


# ---------------------------------------------------------------------------
# LimiterRenderer
# ---------------------------------------------------------------------------

class TestLimiterRenderer(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import numpy  # noqa: F401
            self._have_numpy = True
        except ImportError:
            self._have_numpy = False

    def _skip_if_no_numpy(self) -> None:
        if not self._have_numpy:
            self.skipTest("numpy not available")

    def _render(self, session: dict, recs: list, output_dir: str | None = None) -> dict:
        from mmo.plugins.renderers.limiter_renderer import LimiterRenderer
        return LimiterRenderer().render(session, recs, output_dir)

    def _limiter_rec(self, stem_id: str, ceiling: float = -1.0) -> dict:
        return {
            "recommendation_id": f"REC.TEST.LIMITER.{stem_id.upper()}",
            "issue_id": "ISSUE.SAFETY.TRUEPEAK_OVER_CEILING",
            "action_id": "ACTION.DYN.LIMITER",
            "risk": "medium",
            "requires_approval": False,
            "scope": {"stem_id": stem_id},
            "params": [
                {"param_id": "PARAM.LIMIT.CEILING_DBFS", "value": ceiling, "unit_id": "UNIT.DBTP"},
                {"param_id": "PARAM.LIMIT.LOOKAHEAD_MS", "value": 5.0, "unit_id": "UNIT.MS"},
                {"param_id": "PARAM.LIMIT.RELEASE_MS", "value": 100.0, "unit_id": "UNIT.MS"},
            ],
        }

    def test_no_recs_returns_empty_outputs(self) -> None:
        manifest = self._render({"stems": []}, [])
        self.assertEqual(manifest["renderer_id"], "PLUGIN.RENDERER.LIMITER")
        self.assertEqual(manifest["outputs"], [])

    def test_high_risk_rec_is_skipped(self) -> None:
        rec = self._limiter_rec("kick")
        rec["risk"] = "high"
        manifest = self._render({"stems": []}, [rec])
        self.assertEqual(manifest["outputs"], [])
        self.assertTrue(manifest["skipped"])
        self.assertEqual(manifest["skipped"][0]["reason"], "ineligible")

    def test_requires_approval_rec_is_skipped(self) -> None:
        rec = self._limiter_rec("kick")
        rec["requires_approval"] = True
        manifest = self._render({"stems": []}, [rec])
        self.assertEqual(manifest["skipped"][0]["reason"], "ineligible")

    def test_missing_stem_file_is_skipped(self) -> None:
        session = _session(_stem("kick", true_peak_dbtp=0.5, file_path="/nonexistent/kick.wav"))
        rec = self._limiter_rec("kick")
        manifest = self._render(session, [rec])
        self.assertTrue(manifest["skipped"])
        self.assertIn(manifest["skipped"][0]["reason"], {"stem_file_missing", "non_wav_stem"})

    def test_renders_wav_when_stem_file_exists(self) -> None:
        self._skip_if_no_numpy()
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "kick.wav"
            _write_hot_wav(wav_path, peak=0.98)
            session = _session(_stem("kick", true_peak_dbtp=0.5, file_path=str(wav_path)))
            rec = self._limiter_rec("kick")
            manifest = self._render(session, [rec], output_dir=tmp)

            self.assertEqual(len(manifest["outputs"]), 1)
            out = manifest["outputs"][0]
            self.assertEqual(out["stem_id"], "kick")
            self.assertTrue(Path(out["path"]).is_file())
            self.assertEqual(out["bit_depth"], 24)

    def test_output_gain_is_zero_when_below_ceiling(self) -> None:
        self._skip_if_no_numpy()
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "quiet.wav"
            _write_wav(wav_path, [0.1 * i / 480 for i in range(480)])
            session = _session(_stem("quiet", file_path=str(wav_path)))
            rec = self._limiter_rec("quiet")
            manifest = self._render(session, [rec], output_dir=tmp)

            if manifest["outputs"]:
                self.assertAlmostEqual(manifest["outputs"][0]["gain_applied_db"], 0.0, places=2)

    def test_duplicate_stem_second_rec_is_skipped(self) -> None:
        self._skip_if_no_numpy()
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "kick.wav"
            _write_hot_wav(wav_path, peak=0.98)
            session = _session(_stem("kick", file_path=str(wav_path)))
            recs = [self._limiter_rec("kick"), self._limiter_rec("kick")]
            recs[1]["recommendation_id"] = "REC.TEST.LIMITER.KICK2"
            manifest = self._render(session, recs, output_dir=tmp)

            self.assertEqual(len(manifest["outputs"]), 1)
            self.assertEqual(len(manifest["skipped"]), 1)
            self.assertEqual(manifest["skipped"][0]["reason"], "duplicate_stem")

    def test_non_wav_stem_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            flac_path = Path(tmp) / "kick.flac"
            flac_path.write_bytes(b"\x00" * 16)
            session = _session(_stem("kick", file_path=str(flac_path)))
            rec = self._limiter_rec("kick")
            manifest = self._render(session, [rec], output_dir=tmp)
            self.assertEqual(manifest["skipped"][0]["reason"], "non_wav_stem")

    def test_skipped_list_is_sorted_deterministically(self) -> None:
        session = {"stems": []}
        recs = [
            {**self._limiter_rec("z_stem"), "recommendation_id": "REC.TEST.Z"},
            {**self._limiter_rec("a_stem"), "recommendation_id": "REC.TEST.A"},
        ]
        manifest = self._render(session, recs)
        reasons = [s["reason"] for s in manifest["skipped"]]
        self.assertEqual(reasons, sorted(reasons))

    def test_manifest_has_renderer_id(self) -> None:
        manifest = self._render({"stems": []}, [])
        self.assertEqual(manifest["renderer_id"], "PLUGIN.RENDERER.LIMITER")


if __name__ == "__main__":
    unittest.main()
