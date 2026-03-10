"""Generate deterministic golden render fixture stems."""

from __future__ import annotations

import argparse
import math
import random
import struct
import wave
from pathlib import Path

_RATE_HZ = 48_000
_DURATION_S = 0.35
_SCALE_16 = 32_767.0
_BASE_STEREO_FIXTURE = "golden_small_stereo"
_BASE_SURROUND_FIXTURE = "golden_small_surround"
_BASE_IMMERSIVE_FIXTURE = "golden_small_immersive"


def _clip_unit(value: float) -> float:
    if value > 1.0:
        return 1.0
    if value < -1.0:
        return -1.0
    return value


def _to_pcm16(sample: float) -> int:
    return int(round(_clip_unit(sample) * _SCALE_16))


def _write_wav(path: Path, *, channels: int, samples: list[float]) -> None:
    if channels <= 0:
        raise ValueError("channels must be positive")
    if len(samples) % channels != 0:
        raise ValueError("interleaved samples length must be divisible by channels")
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = [_to_pcm16(sample) for sample in samples]
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(_RATE_HZ)
        handle.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))


def _frame_count() -> int:
    return int(_RATE_HZ * _DURATION_S)


def _kick_mono() -> list[float]:
    frames = _frame_count()
    out: list[float] = []
    for index in range(frames):
        t = index / _RATE_HZ
        env = math.exp(-18.0 * t)
        fundamental = math.sin(2.0 * math.pi * 56.0 * t)
        click = math.sin(2.0 * math.pi * 1_120.0 * t) * math.exp(-140.0 * t)
        out.append(0.60 * env * fundamental + 0.06 * click)
    return out


def _bass_mono() -> list[float]:
    frames = _frame_count()
    out: list[float] = []
    for index in range(frames):
        t = index / _RATE_HZ
        env = 0.95 - 0.25 * (t / _DURATION_S)
        fundamental = math.sin(2.0 * math.pi * 82.41 * t)
        harmonic = 0.30 * math.sin(2.0 * math.pi * 164.82 * t + 0.2)
        out.append(0.36 * env * (fundamental + harmonic))
    return out


def _pad_stereo_wide() -> list[float]:
    frames = _frame_count()
    out: list[float] = []
    for index in range(frames):
        t = index / _RATE_HZ
        slow = 0.5 + 0.5 * math.sin(2.0 * math.pi * 0.33 * t)
        amp = 0.16 + 0.06 * slow
        left = amp * (
            math.sin(2.0 * math.pi * 330.0 * t)
            + 0.5 * math.sin(2.0 * math.pi * 495.0 * t + 0.3)
        )
        right = amp * (
            math.sin(2.0 * math.pi * 330.0 * t + 0.85)
            + 0.5 * math.sin(2.0 * math.pi * 495.0 * t + 1.25)
        )
        out.extend((left, right))
    return out


def _sfx_stereo() -> list[float]:
    frames = _frame_count()
    out: list[float] = []
    for index in range(frames):
        t = index / _RATE_HZ
        env = math.exp(-10.0 * t)
        chirp_a = math.sin(2.0 * math.pi * (420.0 + 1_500.0 * t) * t)
        chirp_b = math.sin(2.0 * math.pi * (900.0 + 700.0 * t) * t + 1.1)
        left = 0.22 * env * (0.8 * chirp_a + 0.25 * chirp_b)
        right = 0.22 * env * (0.8 * chirp_b + 0.25 * chirp_a)
        out.extend((left, right))
    return out


def _room_stereo() -> list[float]:
    frames = _frame_count()
    rng = random.Random(51)
    out: list[float] = []
    for index in range(frames):
        t = index / _RATE_HZ
        env = 0.55 + 0.35 * math.sin(2.0 * math.pi * 0.18 * t)
        noise_left = rng.uniform(-1.0, 1.0)
        noise_right = rng.uniform(-1.0, 1.0)
        tone_left = math.sin(2.0 * math.pi * 180.0 * t + 0.2)
        tone_right = math.sin(2.0 * math.pi * 210.0 * t + 0.9)
        left = 0.07 * env * (0.62 * tone_left + 0.38 * noise_left)
        right = 0.07 * env * (0.62 * tone_right + 0.38 * noise_right)
        out.extend((left, right))
    return out


def _ambience_stereo() -> list[float]:
    frames = _frame_count()
    rng = random.Random(714)
    out: list[float] = []
    for index in range(frames):
        t = index / _RATE_HZ
        sweep = 0.5 + 0.5 * math.sin(2.0 * math.pi * 0.22 * t)
        env = 0.82 + 0.12 * sweep
        noise_left = rng.uniform(-1.0, 1.0)
        noise_right = rng.uniform(-1.0, 1.0)
        shimmer_left = math.sin(2.0 * math.pi * 510.0 * t + 0.4)
        shimmer_right = math.sin(2.0 * math.pi * 610.0 * t + 1.2)
        low_left = math.sin(2.0 * math.pi * 140.0 * t)
        low_right = math.sin(2.0 * math.pi * 160.0 * t + 0.6)
        left = 0.12 * env * (0.42 * noise_left + 0.33 * shimmer_left + 0.25 * low_left)
        right = 0.12 * env * (0.42 * noise_right + 0.33 * shimmer_right + 0.25 * low_right)
        out.extend((left, right))
    return out


def _write_base_fixture(out_dir: Path) -> None:
    _write_wav(out_dir / "kick.wav", channels=1, samples=_kick_mono())
    _write_wav(out_dir / "bass_di.wav", channels=1, samples=_bass_mono())
    _write_wav(out_dir / "pad_stereo_wide.wav", channels=2, samples=_pad_stereo_wide())
    _write_wav(out_dir / "sfx_stereo.wav", channels=2, samples=_sfx_stereo())


def generate(fixtures_root: Path) -> None:
    stereo_dir = fixtures_root / _BASE_STEREO_FIXTURE / "stems"
    surround_dir = fixtures_root / _BASE_SURROUND_FIXTURE / "stems"
    immersive_dir = fixtures_root / _BASE_IMMERSIVE_FIXTURE / "stems"

    _write_base_fixture(stereo_dir)
    _write_base_fixture(surround_dir)
    _write_base_fixture(immersive_dir)

    _write_wav(surround_dir / "room_stereo.wav", channels=2, samples=_room_stereo())
    _write_wav(immersive_dir / "ambience_stereo.wav", channels=2, samples=_ambience_stereo())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output fixtures directory (default: fixtures/golden/).",
    )
    args = parser.parse_args()

    if args.out_dir:
        fixtures_root = Path(args.out_dir)
    else:
        fixtures_root = Path(__file__).resolve().parent
    generate(fixtures_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
