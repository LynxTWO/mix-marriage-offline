import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.dsp.stereo import compute_stereo_correlation_wav


class TestStereoCorrelation(unittest.TestCase):
    def test_negative_correlation_near_minus_one(self) -> None:
        left_samples = [1000, -2000, 3000, -4000, 5000, -6000, 7000, -8000]
        right_samples = [-value for value in left_samples]
        interleaved = []
        for left, right in zip(left_samples, right_samples):
            interleaved.extend([left, right])

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = Path(handle.name)

        try:
            with wave.open(str(path), "wb") as wav_handle:
                wav_handle.setnchannels(2)
                wav_handle.setsampwidth(2)
                wav_handle.setframerate(48000)
                wav_handle.writeframes(
                    struct.pack(f"<{len(interleaved)}h", *interleaved)
                )

            correlation = compute_stereo_correlation_wav(path)
            self.assertAlmostEqual(correlation, -1.0, places=6)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
