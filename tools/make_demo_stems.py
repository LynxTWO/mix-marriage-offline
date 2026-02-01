"""Generate deterministic demo WAV stems for MMO scans."""

from __future__ import annotations

import argparse
import math
import random
import struct
from pathlib import Path
from typing import Iterable, List
import wave


def _pack_sample(value: int, sampwidth: int) -> bytes:
    if sampwidth == 2:
        return struct.pack("<h", value)
    if sampwidth == 3:
        packed = value & 0xFFFFFF
        return bytes((packed & 0xFF, (packed >> 8) & 0xFF, (packed >> 16) & 0xFF))
    raise ValueError(f"Unsupported sample width: {sampwidth}")


def _write_wav(path: Path, samples: Iterable[int], sample_rate: int, sampwidth: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(sampwidth)
        handle.setframerate(sample_rate)
        data = b"".join(_pack_sample(sample, sampwidth) for sample in samples)
        handle.writeframes(data)


def _kick_samples(sample_rate: int, duration_s: float, max_val: int) -> List[int]:
    frames = int(sample_rate * duration_s)
    samples: List[int] = []
    for i in range(frames):
        t = i / sample_rate
        if t < 0.1:
            env = (1.0 - t / 0.1) ** 2
            sample = env * math.sin(2.0 * math.pi * 60.0 * t)
        else:
            sample = 0.0
        samples.append(int(max_val * sample))
    return samples


def _snare_samples(sample_rate: int, duration_s: float, max_val: int) -> List[int]:
    frames = int(sample_rate * duration_s)
    rng = random.Random(1337)
    samples: List[int] = []
    for i in range(frames):
        t = i / sample_rate
        if t < 0.05:
            env = 1.0 - t / 0.05
            sample = env * rng.uniform(-1.0, 1.0)
        else:
            sample = 0.0
        samples.append(int(max_val * sample))
    return samples


def make_demo_stems(out_dir: Path, sample_rate: int = 48000, duration_s: float = 1.0) -> None:
    sampwidth = 3
    max_val = (1 << 23) - 1
    kick = _kick_samples(sample_rate, duration_s, max_val)
    snare = _snare_samples(sample_rate, duration_s, max_val)
    _write_wav(out_dir / "kick.wav", kick, sample_rate, sampwidth)
    _write_wav(out_dir / "snare.wav", snare, sample_rate, sampwidth)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic demo WAV stems.")
    parser.add_argument("out_dir", help="Output directory for demo stems.")
    parser.add_argument("--sample-rate", type=int, default=48000, dest="sample_rate")
    parser.add_argument("--duration-s", type=float, default=1.0, dest="duration_s")
    args = parser.parse_args()

    make_demo_stems(Path(args.out_dir), sample_rate=args.sample_rate, duration_s=args.duration_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
