from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES_DIR = _REPO_ROOT / "fixtures"
_SAMPLE_RATE_HZ = 48_000
_DURATION_S = 0.25
_PCM_SCALE = 32_767


def _sine(
    *,
    freq_hz: float,
    frames: int,
    amplitude: float,
) -> list[float]:
    return [
        amplitude * math.sin(2.0 * math.pi * freq_hz * index / _SAMPLE_RATE_HZ)
        for index in range(frames)
    ]


def _mix(*signals: list[float]) -> list[float]:
    if not signals:
        return []
    frames = min(len(signal) for signal in signals)
    mixed: list[float] = []
    for frame_index in range(frames):
        value = sum(float(signal[frame_index]) for signal in signals)
        if value > 1.0:
            value = 1.0
        elif value < -1.0:
            value = -1.0
        mixed.append(value)
    return mixed


def _write_wav(path: Path, *, channels: list[list[float]]) -> None:
    frames = min(len(channel) for channel in channels)
    path.parent.mkdir(parents=True, exist_ok=True)
    samples: list[int] = []
    for frame_index in range(frames):
        for channel in channels:
            value = float(channel[frame_index])
            if value > 1.0:
                value = 1.0
            elif value < -1.0:
                value = -1.0
            samples.append(int(round(value * _PCM_SCALE)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(len(channels))
        handle.setsampwidth(2)
        handle.setframerate(_SAMPLE_RATE_HZ)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def main() -> int:
    frames = int(_SAMPLE_RATE_HZ * _DURATION_S)

    mains_left = _mix(
        _sine(freq_hz=440.0, frames=frames, amplitude=0.25),
        _sine(freq_hz=660.0, frames=frames, amplitude=0.15),
    )
    mains_right = _mix(
        _sine(freq_hz=550.0, frames=frames, amplitude=0.22),
        _sine(freq_hz=770.0, frames=frames, amplitude=0.12),
    )
    explicit_lfe = _sine(freq_hz=60.0, frames=frames, amplitude=0.45)
    out_of_band_lfe = _mix(
        _sine(freq_hz=60.0, frames=frames, amplitude=0.45),
        _sine(freq_hz=250.0, frames=frames, amplitude=0.4),
    )

    _write_wav(
        _FIXTURES_DIR / "lfe_explicit" / "mains.wav",
        channels=[mains_left, mains_right],
    )
    _write_wav(
        _FIXTURES_DIR / "lfe_explicit" / "lfe.wav",
        channels=[explicit_lfe],
    )
    _write_wav(
        _FIXTURES_DIR / "lfe_out_of_band" / "mains.wav",
        channels=[mains_left, mains_right],
    )
    _write_wav(
        _FIXTURES_DIR / "lfe_out_of_band" / "lfe.wav",
        channels=[out_of_band_lfe],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
