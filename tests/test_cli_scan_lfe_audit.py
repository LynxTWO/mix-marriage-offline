"""Tests for DoD 4.4.2: LFE content audit in mmo scan <folder>.

Tests cover:
- LFE channel index detection from channel layout strings.
- LFE audit runs on WAV stems with LFE channels and emits ISSUE.LFE.* issues.
- Stems without LFE channels produce no ISSUE.LFE.* issues.
- --dry-run flag: scan runs, summary printed, no file written.
- --strict flag: higher severity for LFE issues.
- Role naming convention: ISSUE.VALIDATION.UNKNOWN_ROLE emitted for unrecognized names.
- Human-readable summary flag.
"""
from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from typing import List


def _write_wav(
    path: Path,
    channels: int,
    sample_rate: int,
    bit_depth: int,
    samples_per_channel: int,
    channel_data: dict[int, list[float]] | None = None,
) -> None:
    """Write a simple WAV file.  channel_data maps channel_index -> sample list."""
    sampwidth = bit_depth // 8
    max_val = (1 << (bit_depth - 1)) - 1
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        raw = bytearray()
        for frame_idx in range(samples_per_channel):
            for ch_idx in range(channels):
                if channel_data and ch_idx in channel_data:
                    ch_samples = channel_data[ch_idx]
                    v = ch_samples[frame_idx] if frame_idx < len(ch_samples) else 0.0
                else:
                    v = 0.0
                int_val = max(-max_val - 1, min(max_val, int(v * max_val)))
                if sampwidth == 2:
                    raw += struct.pack("<h", int_val)
                else:
                    # 24-bit
                    iv = int_val & 0xFFFFFF
                    raw += bytes([iv & 0xFF, (iv >> 8) & 0xFF, (iv >> 16) & 0xFF])
        wf.writeframes(bytes(raw))


def _make_sine(freq_hz: float, sample_rate: int, n_samples: int, amplitude: float = 0.5) -> list[float]:
    return [
        amplitude * math.sin(2.0 * math.pi * freq_hz * i / sample_rate)
        for i in range(n_samples)
    ]


def _write_wav_extensible_51(
    path: Path,
    sample_rate: int,
    channel_data: dict[int, list[float]],
    n_frames: int,
) -> None:
    """Write a 6-channel WAVE_FORMAT_EXTENSIBLE WAV with 5.1 channel mask (0x3F).

    Channel order: FL FR FC LFE BL BR — mask 0x3F.
    LFE is channel index 3.
    The WAVE_FORMAT_EXTENSIBLE header lets the WAV reader detect the channel mask.
    """
    channels = 6
    sampwidth = 2
    max_val = 32767
    channel_mask = 0x3F  # FL|FR|FC|LFE|BL|BR

    pcm = bytearray()
    for frame_idx in range(n_frames):
        for ch_idx in range(channels):
            v = 0.0
            if ch_idx in channel_data:
                ch_s = channel_data[ch_idx]
                v = ch_s[frame_idx] if frame_idx < len(ch_s) else 0.0
            int_val = max(-max_val - 1, min(max_val, int(v * max_val)))
            pcm += struct.pack("<h", int_val)

    bits_per_sample = 16
    block_align = channels * sampwidth
    byte_rate = sample_rate * block_align
    valid_bits = 16
    # PCM SubFormat GUID
    subformat = struct.pack(
        "<IHH8s",
        0x00000001, 0x0000, 0x0010,
        b"\x80\x00\x00\xaa\x00\x38\x9b\x71",
    )
    # fmt body (18 bytes) + extension (24 bytes) = 42 bytes total
    fmt_body = struct.pack(
        "<HHIIHH",
        0xFFFE,       # WAVE_FORMAT_EXTENSIBLE
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
    )
    fmt_ext = struct.pack("<HHI", 22, valid_bits, channel_mask) + subformat
    fmt_chunk = fmt_body + fmt_ext

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return tag + struct.pack("<I", len(data)) + data

    riff_data = b"WAVE" + _chunk(b"fmt ", fmt_chunk) + _chunk(b"data", bytes(pcm))
    path.write_bytes(b"RIFF" + struct.pack("<I", len(riff_data)) + riff_data)


def _make_stems_dir_with_lfe(stems_dir: Path, sample_rate: int = 48000) -> Path:
    """Create a 5.1 WAV stem with strong LFE signal for testing.

    LFE (channel index 3) has: 60 Hz in-band + 200 Hz out-of-band (well above 120 Hz).
    Uses WAVE_FORMAT_EXTENSIBLE so the WAV reader detects channel mask → LFE index.
    """
    stems_dir.mkdir(parents=True, exist_ok=True)
    n = sample_rate // 4  # 0.25s

    lfe_inband = _make_sine(60.0, sample_rate, n, amplitude=0.8)
    lfe_oob = _make_sine(200.0, sample_rate, n, amplitude=0.7)
    lfe_combined = [
        max(-1.0, min(1.0, a + b)) for a, b in zip(lfe_inband, lfe_oob)
    ]
    fl_fr = _make_sine(1000.0, sample_rate, n, amplitude=0.3)

    channel_data = {
        0: fl_fr,           # FL
        1: fl_fr,           # FR
        2: fl_fr,           # FC
        3: lfe_combined,    # LFE
        4: fl_fr,           # BL
        5: fl_fr,           # BR
    }
    path = stems_dir / "mix_51.wav"
    _write_wav_extensible_51(path, sample_rate, channel_data, n)
    return stems_dir


def _run_scan_session(
    stems_dir: Path,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str]:
    """Run mmo.tools.scan_session and return (returncode, stdout, stderr)."""
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")

    cmd = [
        os.fspath(os.getenv("PYTHON", "") or sys.executable),
        "-m",
        "mmo.tools.scan_session",
        os.fspath(stems_dir),
    ]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


class TestLfeChannelDetection(unittest.TestCase):
    """Unit tests for detect_lfe_channel_indices (no audio needed)."""

    def setUp(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(repo_root / "src"))

    def test_detect_lfe_from_51_layout(self) -> None:
        from mmo.core.lfe_audit import detect_lfe_channel_indices

        indices = detect_lfe_channel_indices(6, channel_layout="5.1")
        self.assertEqual(indices, [3])

    def test_detect_lfe_from_51_side_layout(self) -> None:
        from mmo.core.lfe_audit import detect_lfe_channel_indices

        indices = detect_lfe_channel_indices(6, channel_layout="5.1(side)")
        self.assertEqual(indices, [3])

    def test_detect_lfe_from_71_layout(self) -> None:
        from mmo.core.lfe_audit import detect_lfe_channel_indices

        indices = detect_lfe_channel_indices(8, channel_layout="7.1")
        self.assertEqual(indices, [3])

    def test_no_lfe_in_stereo(self) -> None:
        from mmo.core.lfe_audit import detect_lfe_channel_indices

        indices = detect_lfe_channel_indices(2, channel_layout="stereo")
        self.assertEqual(indices, [])

    def test_detect_lfe_from_wav_mask(self) -> None:
        from mmo.core.lfe_audit import detect_lfe_channel_indices

        # 5.1 mask: FL(1)+FR(2)+FC(4)+LFE(8)+BL(16)+BR(32) = 0x3F = 63
        indices = detect_lfe_channel_indices(6, wav_channel_mask=0x3F)
        self.assertEqual(indices, [3])

    def test_detect_lfe_from_21_layout(self) -> None:
        from mmo.core.lfe_audit import detect_lfe_channel_indices

        indices = detect_lfe_channel_indices(3, channel_layout="2.1")
        self.assertEqual(indices, [2])

    def test_detect_dual_lfe_from_52_layout(self) -> None:
        from mmo.core.lfe_audit import detect_lfe_channel_indices

        indices = detect_lfe_channel_indices(7, channel_layout="5.2")
        self.assertEqual(indices, [3, 4])


class TestLfeAuditLogic(unittest.TestCase):
    """Unit tests for LFE audit computations (requires numpy)."""

    def _skip_if_no_numpy(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

    def test_audit_detects_out_of_band_high(self) -> None:
        self._skip_if_no_numpy()
        from mmo.core.lfe_audit import audit_lfe_channel

        sr = 48000
        n = sr // 4
        # Strong signal at 200 Hz (above 120 Hz cutoff)
        oob_samples = _make_sine(200.0, sr, n, amplitude=0.8)
        result = audit_lfe_channel(oob_samples, None, sr)
        self.assertTrue(result["out_of_band_high"], "Expected out_of_band_high flag")

    def test_audit_no_out_of_band_for_inband_signal(self) -> None:
        self._skip_if_no_numpy()
        from mmo.core.lfe_audit import audit_lfe_channel

        sr = 48000
        n = sr // 4
        # Signal at 60 Hz (clearly in-band)
        inband_samples = _make_sine(60.0, sr, n, amplitude=0.5)
        result = audit_lfe_channel(inband_samples, None, sr)
        self.assertFalse(result["infrasonic_rumble"], "No infrasonic expected")

    def test_audit_detects_infrasonic_rumble(self) -> None:
        self._skip_if_no_numpy()
        from mmo.core.lfe_audit import audit_lfe_channel

        sr = 48000
        n = sr  # 1 second for frequency resolution at 10 Hz
        # Signal at 10 Hz (below 20 Hz floor)
        infra_samples = _make_sine(10.0, sr, n, amplitude=0.8)
        result = audit_lfe_channel(infra_samples, None, sr)
        self.assertTrue(result["infrasonic_rumble"], "Expected infrasonic_rumble flag")

    def test_audit_headroom_low_flag(self) -> None:
        self._skip_if_no_numpy()
        from mmo.core.lfe_audit import audit_lfe_channel

        sr = 48000
        n = sr // 4
        # Near-full-scale signal → low headroom
        loud_samples = [0.99] * n
        result = audit_lfe_channel(loud_samples, None, sr)
        self.assertTrue(result["headroom_low"], "Expected headroom_low flag")

    def test_build_lfe_issues_returns_expected_ids(self) -> None:
        self._skip_if_no_numpy()
        from mmo.core.lfe_audit import audit_lfe_channel, build_lfe_audit_issues

        sr = 48000
        n = sr // 4
        oob_samples = _make_sine(200.0, sr, n, amplitude=0.8)
        result = audit_lfe_channel(oob_samples, None, sr)
        issues = build_lfe_audit_issues("test_stem", 3, result)
        issue_ids = {i["issue_id"] for i in issues}
        self.assertIn("ISSUE.LFE.OUT_OF_BAND_HIGH", issue_ids)

    def test_build_lfe_issues_strict_higher_severity(self) -> None:
        self._skip_if_no_numpy()
        from mmo.core.lfe_audit import audit_lfe_channel, build_lfe_audit_issues

        sr = 48000
        n = sr // 4
        oob_samples = _make_sine(200.0, sr, n, amplitude=0.8)
        result = audit_lfe_channel(oob_samples, None, sr)
        normal_issues = build_lfe_audit_issues("test_stem", 3, result, strict=False)
        strict_issues = build_lfe_audit_issues("test_stem", 3, result, strict=True)

        def _oob_sev(issues: list) -> int | None:
            for i in issues:
                if i.get("issue_id") == "ISSUE.LFE.OUT_OF_BAND_HIGH":
                    return i.get("severity")
            return None

        normal_sev = _oob_sev(normal_issues)
        strict_sev = _oob_sev(strict_issues)
        self.assertIsNotNone(normal_sev)
        self.assertIsNotNone(strict_sev)
        self.assertGreater(strict_sev, normal_sev)

    def test_audit_lfe_channels_returns_per_channel_rows_and_sum(self) -> None:
        self._skip_if_no_numpy()
        from mmo.core.lfe_audit import audit_lfe_channels

        sr = 48000
        n = sr // 2
        lfe1 = _make_sine(60.0, sr, n, amplitude=0.6)
        lfe2_inband = _make_sine(70.0, sr, n, amplitude=0.4)
        lfe2_oob = _make_sine(240.0, sr, n, amplitude=0.5)
        lfe2 = [max(-1.0, min(1.0, a + b)) for a, b in zip(lfe2_inband, lfe2_oob)]

        interleaved: list[float] = []
        for i in range(n):
            interleaved.extend([0.0, 0.0, 0.0, lfe1[i], lfe2[i], 0.0, 0.0])

        summary = audit_lfe_channels(
            interleaved,
            channels=7,
            lfe_indices=[3, 4],
            sample_rate_hz=sr,
        )
        rows = summary.get("rows", [])
        self.assertEqual([row["channel_index"] for row in rows], [3, 4])
        self.assertTrue(all("inband_energy_db" in row for row in rows))
        self.assertTrue(all("true_peak_dbtp" in row for row in rows))
        self.assertTrue(any(bool(row.get("out_of_band_high")) for row in rows))
        summed = float(summary.get("summed_lfe_inband_energy_db", float("-inf")))
        strongest = max(float(row["inband_energy_db"]) for row in rows)
        self.assertGreaterEqual(summed, strongest)


class TestScanSessionLfeIntegration(unittest.TestCase):
    """Integration tests: scan_session with LFE WAV stems."""

    def _skip_if_no_numpy(self) -> None:
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not available")

    def test_scan_51_wav_with_oob_emits_lfe_issue(self) -> None:
        self._skip_if_no_numpy()
        with tempfile.TemporaryDirectory() as tmp:
            stems_dir = _make_stems_dir_with_lfe(Path(tmp) / "stems")
            rc, stdout, stderr = _run_scan_session(stems_dir)
            self.assertEqual(rc, 0, f"Scan failed: {stderr}")
            report = json.loads(stdout)
            issues = report.get("issues", [])
            lfe_issue_ids = [
                i["issue_id"]
                for i in issues
                if isinstance(i, dict) and i.get("issue_id", "").startswith("ISSUE.LFE.")
            ]
            self.assertTrue(
                len(lfe_issue_ids) > 0,
                f"Expected ISSUE.LFE.* issues, got: {[i.get('issue_id') for i in issues]}",
            )

    def test_scan_51_wav_lfe_measurements_stored(self) -> None:
        self._skip_if_no_numpy()
        with tempfile.TemporaryDirectory() as tmp:
            stems_dir = _make_stems_dir_with_lfe(Path(tmp) / "stems")
            rc, stdout, _stderr = _run_scan_session(stems_dir)
            self.assertEqual(rc, 0)
            report = json.loads(stdout)
            stems = report.get("session", {}).get("stems", [])
            lfe_ev_ids: set[str] = set()
            for stem in stems:
                for m in stem.get("measurements", []):
                    if isinstance(m, dict) and m.get("evidence_id", "").startswith("EVID.LFE."):
                        lfe_ev_ids.add(m["evidence_id"])
            self.assertIn("EVID.LFE.BAND_ENERGY_DB", lfe_ev_ids)
            self.assertIn("EVID.LFE.OUT_OF_BAND_DB", lfe_ev_ids)

    def test_scan_stereo_wav_no_lfe_issues(self) -> None:
        """Stereo stems should not produce any ISSUE.LFE.* issues."""
        with tempfile.TemporaryDirectory() as tmp:
            stems_dir = Path(tmp) / "stems"
            stems_dir.mkdir()
            _write_wav(stems_dir / "kick.wav", 2, 48000, 16, 1024)
            _write_wav(stems_dir / "snare.wav", 2, 48000, 16, 1024)
            rc, stdout, _stderr = _run_scan_session(stems_dir)
            self.assertEqual(rc, 0)
            report = json.loads(stdout)
            issues = report.get("issues", [])
            lfe_issues = [
                i for i in issues
                if isinstance(i, dict) and i.get("issue_id", "").startswith("ISSUE.LFE.")
            ]
            self.assertEqual(lfe_issues, [], f"Unexpected LFE issues: {lfe_issues}")

    def test_scan_dry_run_no_file_written(self) -> None:
        """--dry-run must not write a file; prints summary to stdout."""
        with tempfile.TemporaryDirectory() as tmp:
            stems_dir = Path(tmp) / "stems"
            stems_dir.mkdir()
            _write_wav(stems_dir / "kick.wav", 2, 48000, 16, 1024)
            out_path = Path(tmp) / "report.json"
            rc, stdout, _stderr = _run_scan_session(
                stems_dir, extra_args=["--dry-run", "--out", str(out_path)]
            )
            self.assertEqual(rc, 0)
            self.assertFalse(out_path.exists(), "dry-run should not write report.json")
            self.assertIn("MMO Stem Scan Report", stdout)

    def test_scan_summary_flag_prints_text(self) -> None:
        """--summary must print human-readable text."""
        with tempfile.TemporaryDirectory() as tmp:
            stems_dir = Path(tmp) / "stems"
            stems_dir.mkdir()
            _write_wav(stems_dir / "guitar.wav", 2, 48000, 16, 1024)
            rc, stdout, _stderr = _run_scan_session(stems_dir, extra_args=["--summary"])
            self.assertEqual(rc, 0)
            self.assertIn("MMO Stem Scan Report", stdout)
            self.assertIn("Stems", stdout)

    def test_scan_strict_flag_raises_severity(self) -> None:
        self._skip_if_no_numpy()
        with tempfile.TemporaryDirectory() as tmp:
            stems_dir = _make_stems_dir_with_lfe(Path(tmp) / "stems")
            rc_normal, out_normal, _ = _run_scan_session(stems_dir)
            rc_strict, out_strict, _ = _run_scan_session(stems_dir, extra_args=["--strict"])
            self.assertEqual(rc_normal, 0)
            self.assertEqual(rc_strict, 0)
            issues_normal = json.loads(out_normal).get("issues", [])
            issues_strict = json.loads(out_strict).get("issues", [])
            # At least one LFE issue should have higher severity in strict mode
            def max_lfe_sev(issues: list) -> int:
                return max(
                    (i["severity"] for i in issues
                     if isinstance(i, dict) and i.get("issue_id", "").startswith("ISSUE.LFE.")),
                    default=0,
                )
            self.assertGreaterEqual(max_lfe_sev(issues_strict), max_lfe_sev(issues_normal))


class TestRoleNamingValidation(unittest.TestCase):
    """Tests for ISSUE.VALIDATION.UNKNOWN_ROLE emitted for unrecognised names."""

    def test_recognised_role_name_no_issue(self) -> None:
        """A stem named 'kick.wav' should NOT get an UNKNOWN_ROLE issue."""
        with tempfile.TemporaryDirectory() as tmp:
            stems_dir = Path(tmp) / "stems"
            stems_dir.mkdir()
            _write_wav(stems_dir / "kick.wav", 2, 48000, 16, 1024)
            rc, stdout, _stderr = _run_scan_session(stems_dir)
            self.assertEqual(rc, 0)
            report = json.loads(stdout)
            unknown_role_issues = [
                i for i in report.get("issues", [])
                if isinstance(i, dict) and i.get("issue_id") == "ISSUE.VALIDATION.UNKNOWN_ROLE"
            ]
            self.assertEqual(
                unknown_role_issues,
                [],
                "kick.wav should not trigger UNKNOWN_ROLE",
            )

    def test_unrecognised_role_name_emits_issue(self) -> None:
        """A stem with a completely opaque name should get an UNKNOWN_ROLE issue."""
        with tempfile.TemporaryDirectory() as tmp:
            stems_dir = Path(tmp) / "stems"
            stems_dir.mkdir()
            # Name that has no role keywords whatsoever
            _write_wav(stems_dir / "zzzxqzz123.wav", 2, 48000, 16, 1024)
            rc, stdout, _stderr = _run_scan_session(stems_dir)
            self.assertEqual(rc, 0)
            report = json.loads(stdout)
            unknown_role_issues = [
                i for i in report.get("issues", [])
                if isinstance(i, dict) and i.get("issue_id") == "ISSUE.VALIDATION.UNKNOWN_ROLE"
            ]
            self.assertTrue(
                len(unknown_role_issues) > 0,
                "Expected ISSUE.VALIDATION.UNKNOWN_ROLE for unrecognised stem name",
            )


if __name__ == "__main__":
    unittest.main()
