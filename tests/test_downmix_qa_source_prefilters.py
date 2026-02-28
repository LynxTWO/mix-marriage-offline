from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from mmo.core.downmix_qa import run_downmix_qa


class TestDownmixQaSourcePreFilters(unittest.TestCase):
    def test_source_pre_filters_are_applied_and_logged(self) -> None:
        src_path = Path("src.wav")
        ref_path = Path("ref.wav")
        matrix = {
            "matrix_id": "DMX.TEST.SRC_TO_ST",
            "source_speakers": ["SPK.LFE"],
            "target_speakers": ["SPK.L", "SPK.R"],
            "coeffs": [[1.0], [1.0]],
            "source_pre_filters": {
                "SPK.LFE": [{"type": "highpass", "freq_hz": 120, "slope_db_per_oct": 24}]
            },
        }
        captured: dict[str, object] = {}

        def _fake_iter_apply_matrix_to_chunks(
            _coeffs,
            _chunks_iter,
            _source_channels,
            target_channels=2,
            chunk_frames=4096,
            *,
            source_pre_filters=None,
            source_speakers=None,
            sample_rate_hz=None,
        ):
            captured["target_channels"] = target_channels
            captured["chunk_frames"] = chunk_frames
            captured["source_pre_filters"] = source_pre_filters
            captured["source_speakers"] = source_speakers
            captured["sample_rate_hz"] = sample_rate_hz
            return iter([[0.0, 0.0] * 128])

        def _fake_iter_ffmpeg_float64_samples(path, _ffmpeg_cmd, chunk_frames=4096):
            if Path(path) == src_path:
                return iter([[0.25] * 256])
            return iter([[0.0, 0.0] * 128])

        with (
            mock.patch("mmo.core.downmix_qa.resolve_ffmpeg_cmd", return_value="ffmpeg"),
            mock.patch("mmo.core.downmix_qa.resolve_downmix_matrix", return_value=matrix),
            mock.patch(
                "mmo.core.downmix_qa.read_metadata",
                side_effect=[
                    {
                        "channels": 1,
                        "sample_rate_hz": 48000,
                        "duration_s": 1.0,
                    },
                    {
                        "channels": 2,
                        "sample_rate_hz": 48000,
                        "duration_s": 1.0,
                    },
                ],
            ),
            mock.patch(
                "mmo.core.downmix_qa.iter_ffmpeg_float64_samples",
                side_effect=_fake_iter_ffmpeg_float64_samples,
            ),
            mock.patch(
                "mmo.core.downmix_qa.iter_apply_matrix_to_chunks",
                side_effect=_fake_iter_apply_matrix_to_chunks,
            ),
        ):
            payload = run_downmix_qa(
                src_path,
                ref_path,
                source_layout_id="LAYOUT.5_1",
                target_layout_id="LAYOUT.2_0",
                policy_id="POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                meters="basic",
                max_seconds=0.5,
            )

        self.assertEqual(captured.get("sample_rate_hz"), 48000)
        self.assertEqual(captured.get("source_speakers"), ["SPK.LFE"])
        self.assertEqual(captured.get("source_pre_filters"), matrix["source_pre_filters"])
        downmix_qa = payload.get("downmix_qa", {})
        log_payload = json.loads(downmix_qa.get("log", "{}"))
        self.assertTrue(log_payload.get("source_pre_filters_applied"))
        self.assertEqual(
            log_payload.get("source_pre_filters"),
            matrix["source_pre_filters"],
        )


if __name__ == "__main__":
    unittest.main()
