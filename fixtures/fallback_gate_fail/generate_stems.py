from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


def _write_stereo_wav(
    path: Path,
    *,
    amp_l: float,
    amp_r: float,
    freq_l: float,
    freq_r: float,
    phase_r: float = 0.0,
    sample_rate_hz: int = 48000,
    duration_s: float = 0.4,
) -> None:
    frame_count = int(sample_rate_hz * duration_s)
    samples: list[int] = []
    path.parent.mkdir(parents=True, exist_ok=True)
    for index in range(frame_count):
        left = amp_l * math.sin(2.0 * math.pi * freq_l * index / sample_rate_hz)
        right = amp_r * math.sin(
            2.0 * math.pi * freq_r * index / sample_rate_hz + phase_r
        )
        samples.extend(
            (
                int(max(-1.0, min(1.0, left)) * 32767.0),
                int(max(-1.0, min(1.0, right)) * 32767.0),
            )
        )
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def main() -> None:
    root = Path(__file__).resolve().parent
    stems_dir = root / "stems"
    _write_stereo_wav(
        stems_dir / "reference_front.wav",
        amp_l=0.22,
        amp_r=0.18,
        freq_l=440.0,
        freq_r=554.37,
    )
    _write_stereo_wav(
        stems_dir / "ambience_bed.wav",
        amp_l=0.72,
        amp_r=0.72,
        freq_l=110.0,
        freq_r=110.0,
        phase_r=math.pi / 2.0,
    )


if __name__ == "__main__":
    main()
