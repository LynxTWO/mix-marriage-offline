"""Tests for stem_features: transient/tail separation, azimuth scale, depth_hint."""
from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.core.stem_features import (
    _STEREO_PAN_MAX_AZIMUTH_DEG,
    compute_azimuth_hint,
    compute_stereo_width,
    infer_stereo_hints,
)

_SR = 48_000


def _write_wav(path: Path, frames: list[tuple[float, float]], *, sr: int = _SR) -> None:
    """Write a 16-bit stereo WAV from a list of (left, right) float samples."""
    path.parent.mkdir(parents=True, exist_ok=True)
    interleaved = []
    for left, right in frames:
        interleaved.append(int(max(-1.0, min(1.0, left)) * 32767))
        interleaved.append(int(max(-1.0, min(1.0, right)) * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))


def _sine(amp: float, duration_s: float, sr: int = _SR) -> list[float]:
    """Return a list of 220 Hz sine samples at given amplitude."""
    n = int(duration_s * sr)
    return [amp * math.sin(2 * math.pi * 220.0 * i / sr) for i in range(n)]


def _make_panned_stem(
    path: Path,
    *,
    pan: float,  # -1.0 = full left, 0.0 = center, +1.0 = full right
    duration_s: float = 0.5,
    sr: int = _SR,
) -> None:
    """Write a panned sine stem.  pan is standard linear pan law."""
    gain_l = math.sqrt(max(0.0, 0.5 - pan * 0.5))
    gain_r = math.sqrt(max(0.0, 0.5 + pan * 0.5))
    dry = _sine(0.5, duration_s, sr)
    frames = [(gain_l * s, gain_r * s) for s in dry]
    _write_wav(path, frames, sr=sr)


def _make_reverb_stem(
    path: Path,
    *,
    pan: float = 0.0,
    dry_duration_s: float = 0.1,
    tail_duration_s: float = 0.4,
    dry_amp: float = 0.5,
    tail_amp: float = 0.06,
    sr: int = _SR,
) -> None:
    """Write a stem with a loud transient burst followed by a quiet centered reverb tail."""
    gain_l = math.sqrt(max(0.0, 0.5 - pan * 0.5))
    gain_r = math.sqrt(max(0.0, 0.5 + pan * 0.5))
    dry = _sine(dry_amp, dry_duration_s, sr)
    # Tail is centered (L=R) to simulate a room reverb return
    tail = _sine(tail_amp, tail_duration_s, sr)
    frames = [(gain_l * s, gain_r * s) for s in dry]
    frames += [(0.5 * s, 0.5 * s) for s in tail]  # centered reverb return
    _write_wav(path, frames, sr=sr)


# ---------------------------------------------------------------------------
# compute_azimuth_hint: scale check
# ---------------------------------------------------------------------------

class TestComputeAzimuthHintScale(unittest.TestCase):
    def test_max_azimuth_is_90_degrees(self) -> None:
        """Full pan (very high ILD) must reach _STEREO_PAN_MAX_AZIMUTH_DEG, not 60°."""
        self.assertEqual(_STEREO_PAN_MAX_AZIMUTH_DEG, 90.0)
        # Simulate hard-right pan: ILD >> threshold
        large_ild = [60.0, 60.0, 60.0, 60.0]
        weights = [1.0, 1.0, 1.0, 1.0]
        az, _, _ = compute_azimuth_hint(ild_db_windows=large_ild, window_weights=weights)
        self.assertAlmostEqual(az, 90.0, places=1)

    def test_moderate_pan_maps_between_zero_and_90(self) -> None:
        """A 6 dB ILD (half the full-pan threshold) should give ~45°."""
        ild = [6.0, 6.0, 6.0, 6.0]
        weights = [1.0, 1.0, 1.0, 1.0]
        az, _, _ = compute_azimuth_hint(ild_db_windows=ild, window_weights=weights)
        self.assertGreater(az, 30.0)
        self.assertLess(az, 70.0)

    def test_center_pan_gives_zero_azimuth(self) -> None:
        """L=R (ILD = 0) must give azimuth = 0."""
        ild = [0.0, 0.0, 0.0, 0.0]
        weights = [1.0, 1.0, 1.0, 1.0]
        az, _, _ = compute_azimuth_hint(ild_db_windows=ild, window_weights=weights)
        self.assertEqual(az, 0.0)

    def test_left_pan_gives_negative_azimuth(self) -> None:
        """Hard-left ILD must yield negative azimuth."""
        ild = [-60.0, -60.0, -60.0, -60.0]
        weights = [1.0, 1.0, 1.0, 1.0]
        az, _, _ = compute_azimuth_hint(ild_db_windows=ild, window_weights=weights)
        self.assertAlmostEqual(az, -90.0, places=1)


# ---------------------------------------------------------------------------
# infer_stereo_hints on simple panned stems
# ---------------------------------------------------------------------------

class TestInferStereoHintsPan(unittest.TestCase):
    # Convention: azimuth_deg_hint = ILD = log(L/R).
    # Positive azimuth → L louder → LEFT side of stage.
    # Negative azimuth → R louder → RIGHT side of stage.
    # This matches _add_pair_with_pan where positive pan → more gain to left speaker.

    def test_center_pan_gives_near_zero_azimuth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "center.wav"
            _make_panned_stem(path, pan=0.0)
            hints = infer_stereo_hints(path)
        self.assertAlmostEqual(hints["azimuth_deg_hint"], 0.0, places=1)

    def test_right_pan_gives_negative_azimuth(self) -> None:
        """pan=+1.0 (R louder than L) → negative azimuth (right side)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "right.wav"
            _make_panned_stem(path, pan=1.0)  # hard right: L=0, R=loud
            hints = infer_stereo_hints(path)
        self.assertLess(hints["azimuth_deg_hint"], -30.0,
                        "Hard-right stem (R louder) should produce azimuth < -30°")

    def test_left_pan_gives_positive_azimuth(self) -> None:
        """pan=-1.0 (L louder than R) → positive azimuth (left side)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "left.wav"
            _make_panned_stem(path, pan=-1.0)  # hard left: L=loud, R=0
            hints = infer_stereo_hints(path)
        self.assertGreater(hints["azimuth_deg_hint"], 30.0,
                           "Hard-left stem (L louder) should produce azimuth > 30°")

    def test_azimuth_sign_is_opposite_to_linear_pan(self) -> None:
        """Moderate right pan (pan=0.5) → negative azimuth; left pan → positive."""
        with tempfile.TemporaryDirectory() as tmp:
            p_r = Path(tmp) / "right.wav"
            p_l = Path(tmp) / "left.wav"
            _make_panned_stem(p_r, pan=0.5)
            _make_panned_stem(p_l, pan=-0.5)
            h_r = infer_stereo_hints(p_r)
            h_l = infer_stereo_hints(p_l)
        self.assertLess(h_r["azimuth_deg_hint"], 0.0)
        self.assertGreater(h_l["azimuth_deg_hint"], 0.0)


# ---------------------------------------------------------------------------
# infer_stereo_hints: transient/tail separation
# ---------------------------------------------------------------------------

class TestInferStereoHintsTransientTailSeparation(unittest.TestCase):
    def test_reverb_stem_azimuth_matches_dry_pan_not_reverb(self) -> None:
        """A panned transient + centered reverb tail: azimuth should follow dry signal."""
        with tempfile.TemporaryDirectory() as tmp:
            path_reverb = Path(tmp) / "reverb_right.wav"
            path_dry = Path(tmp) / "dry_right.wav"
            # Reverb stem: panned right burst + centered tail
            _make_reverb_stem(path_reverb, pan=1.0)
            # Dry-only stem at same pan for reference
            _make_panned_stem(path_dry, pan=1.0, duration_s=0.5)
            hints_reverb = infer_stereo_hints(path_reverb)
            hints_dry = infer_stereo_hints(path_dry)

        # pan=1.0 (R louder) → negative azimuth (right side in code convention)
        self.assertLess(hints_reverb["azimuth_deg_hint"], -20.0,
                        "Reverb stem azimuth should follow panned transient (right), not centered tail")
        self.assertLess(hints_dry["azimuth_deg_hint"], -20.0)

    def test_tail_windows_counted_when_reverb_present(self) -> None:
        """Stem with long quiet tail should report tail_windows > 0."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reverb.wav"
            _make_reverb_stem(path, pan=0.0)
            hints = infer_stereo_hints(path)
        self.assertGreater(hints["metrics"]["tail_windows"], 0,
                           "Expected tail windows from reverb decay")

    def test_no_tail_windows_on_sustained_signal(self) -> None:
        """A uniform sustained sine (no decay) should have zero tail windows."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sustained.wav"
            _make_panned_stem(path, pan=0.0, duration_s=0.5)
            hints = infer_stereo_hints(path)
        # Sustained uniform signal: peak never decays → no windows qualify as tail
        self.assertEqual(hints["metrics"]["tail_windows"], 0)


# ---------------------------------------------------------------------------
# infer_stereo_hints: depth_hint
# ---------------------------------------------------------------------------

class TestInferStereoHintsDepth(unittest.TestCase):
    def test_dry_stem_has_low_depth_hint(self) -> None:
        """A dry panned stem (no reverb tail) should have a low depth_hint."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dry.wav"
            _make_panned_stem(path, pan=0.0, duration_s=0.5)
            hints = infer_stereo_hints(path)
        self.assertLessEqual(hints["depth_hint"], 0.3,
                             "Dry stem should have low depth_hint")

    def test_reverb_stem_has_higher_depth_than_dry(self) -> None:
        """A stem with significant reverb tail should have higher depth_hint than dry."""
        with tempfile.TemporaryDirectory() as tmp:
            p_dry = Path(tmp) / "dry.wav"
            p_wet = Path(tmp) / "wet.wav"
            _make_panned_stem(p_dry, pan=0.0, duration_s=0.5)
            _make_reverb_stem(p_wet, pan=0.0, dry_duration_s=0.05, tail_duration_s=0.45)
            h_dry = infer_stereo_hints(p_dry)
            h_wet = infer_stereo_hints(p_wet)
        self.assertGreater(h_wet["depth_hint"], h_dry["depth_hint"],
                           "Reverb stem should have higher depth_hint than dry stem")

    def test_depth_hint_is_in_range(self) -> None:
        """depth_hint must always be in [0, 1]."""
        with tempfile.TemporaryDirectory() as tmp:
            for pan, name in [(0.0, "c"), (1.0, "r"), (-1.0, "l")]:
                path = Path(tmp) / f"{name}.wav"
                _make_panned_stem(path, pan=pan)
                hints = infer_stereo_hints(path)
                self.assertGreaterEqual(hints["depth_hint"], 0.0)
                self.assertLessEqual(hints["depth_hint"], 1.0)

    def test_metrics_include_new_fields(self) -> None:
        """New metrics fields must all be present."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stem.wav"
            _make_panned_stem(path, pan=0.3)
            hints = infer_stereo_hints(path)
        metrics = hints["metrics"]
        for key in ("transient_windows", "tail_windows", "tail_correlation", "depth_ratio"):
            self.assertIn(key, metrics, f"Missing metrics key: {key}")


if __name__ == "__main__":
    unittest.main()
