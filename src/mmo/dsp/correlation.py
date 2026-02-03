from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Dict, Iterator, Sequence

from mmo.dsp.float64 import (
    bytes_to_float_samples_ieee,
    bytes_to_int_samples_pcm,
    pcm_int_to_float64,
)
from mmo.dsp.io import read_wav_metadata
from mmo.dsp.backends.ffmpeg_decode import iter_ffmpeg_float64_samples

_CHUNK_FRAMES = 4096


class OnlineCorrelationAccumulator:
    def __init__(self) -> None:
        self.count = 0
        self.mean_a = 0.0
        self.mean_b = 0.0
        self.sum_a = 0.0
        self.sum_b = 0.0
        self.sum_ab = 0.0

    def update(self, sample_a: float, sample_b: float) -> None:
        self.count += 1
        delta_a = sample_a - self.mean_a
        self.mean_a += delta_a / self.count
        delta_b = sample_b - self.mean_b
        self.mean_b += delta_b / self.count
        self.sum_a += delta_a * (sample_a - self.mean_a)
        self.sum_b += delta_b * (sample_b - self.mean_b)
        self.sum_ab += delta_a * (sample_b - self.mean_b)

    def correlation(self) -> float:
        if self.count < 2:
            return 0.0
        if self.sum_a <= 0.0 or self.sum_b <= 0.0:
            return 0.0
        corr = self.sum_ab / math.sqrt(self.sum_a * self.sum_b)
        if corr > 1.0:
            return 1.0
        if corr < -1.0:
            return -1.0
        return corr


class PairCorrelationAccumulator:
    def __init__(self, channels: int, pairs: Dict[str, tuple[int, int]]) -> None:
        if channels <= 0:
            raise ValueError("channels must be positive")
        self.channels = channels
        self.pairs = dict(pairs)
        self.accumulators = {
            name: OnlineCorrelationAccumulator() for name in self.pairs
        }
        self.remainder: list[float] = []

    def update_chunk(self, chunk: list[float]) -> None:
        if not chunk:
            return
        if self.remainder:
            buffer = self.remainder + list(chunk)
        else:
            buffer = list(chunk)
        total = len(buffer) - (len(buffer) % self.channels)
        if total <= 0:
            self.remainder = buffer
            return
        self.remainder = buffer[total:]
        for index in range(0, total, self.channels):
            base = index
            for name, (idx_a, idx_b) in self.pairs.items():
                acc = self.accumulators.get(name)
                if acc is None:
                    continue
                acc.update(buffer[base + idx_a], buffer[base + idx_b])

    def correlations(self) -> Dict[str, float]:
        return {name: acc.correlation() for name, acc in self.accumulators.items()}


def compute_pair_correlations_from_chunks(
    chunks: Iterator[list[float]],
    channels: int,
    pairs: Dict[str, tuple[int, int]],
) -> Dict[str, float]:
    accumulator = PairCorrelationAccumulator(channels, pairs)
    for chunk in chunks:
        accumulator.update_chunk(chunk)
    return accumulator.correlations()


def _iter_wav_float64_samples(
    path: Path, *, error_context: str
) -> Iterator[list[float]]:
    metadata = read_wav_metadata(path)
    audio_format = metadata["audio_format_resolved"]
    bits_per_sample = metadata["bits_per_sample"]
    channels = metadata["channels"]

    if audio_format == 1:
        if bits_per_sample not in (16, 24, 32):
            raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")
    elif audio_format == 3:
        if bits_per_sample not in (32, 64):
            raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")
    else:
        raise ValueError(f"Unsupported WAV format: {audio_format}")

    try:
        with wave.open(str(path), "rb") as handle:
            while True:
                frames = handle.readframes(_CHUNK_FRAMES)
                if not frames:
                    break
                if audio_format == 1:
                    int_samples = bytes_to_int_samples_pcm(
                        frames, bits_per_sample, channels
                    )
                    if not int_samples:
                        continue
                    float_samples = pcm_int_to_float64(int_samples, bits_per_sample)
                    yield float_samples
                elif audio_format == 3:
                    float_samples = bytes_to_float_samples_ieee(
                        frames, bits_per_sample, channels
                    )
                    if not float_samples:
                        continue
                    yield float_samples
    except (OSError, wave.Error) as exc:
        raise ValueError(f"Failed to read WAV for {error_context}: {path}") from exc


def compute_pair_correlations_wav(
    path: Path, pairs: Dict[str, tuple[int, int]]
) -> Dict[str, float]:
    metadata = read_wav_metadata(path)
    channels = metadata["channels"]
    return compute_pair_correlations_from_chunks(
        _iter_wav_float64_samples(path, error_context="correlation meter"),
        channels,
        pairs,
    )


def compute_pair_correlations_ffmpeg(
    path: Path,
    ffmpeg_cmd: Sequence[str],
    *,
    channels: int,
    pairs: Dict[str, tuple[int, int]],
) -> Dict[str, float]:
    return compute_pair_correlations_from_chunks(
        iter_ffmpeg_float64_samples(path, ffmpeg_cmd, chunk_frames=_CHUNK_FRAMES),
        channels,
        pairs,
    )
