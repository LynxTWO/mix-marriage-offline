from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Iterable, Tuple

import numpy as np

from mmo.dsp.float64 import (
    bytes_to_float_samples_ieee,
    bytes_to_int_samples_pcm,
    pcm_int_to_float64,
)
from mmo.dsp.io import read_wav_metadata

_EPSILON = 1e-12
_TRUEPEAK_UPSAMPLE = 4
_TRUEPEAK_TAPS = 63
_K_WEIGHTING_HP_F0 = 38.13547087602444
_K_WEIGHTING_HP_Q = 0.5003270373253953
_K_WEIGHTING_HS_F0 = 1681.974450955533
_K_WEIGHTING_HS_GAIN_DB = 4.0
_K_WEIGHTING_HS_SLOPE = 1.0
_LOUDNESS_OFFSET = -0.691


def _read_wav_float64(path: Path) -> Tuple[np.ndarray, int]:
    metadata = read_wav_metadata(path)
    audio_format = metadata["audio_format_resolved"]
    bits_per_sample = metadata["bits_per_sample"]
    channels = metadata["channels"]
    sample_rate_hz = int(metadata["sample_rate_hz"])

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
            frames = handle.readframes(handle.getnframes())
    except (OSError, wave.Error) as exc:
        raise ValueError(f"Failed to read WAV for truth meters: {path}") from exc

    if audio_format == 1:
        int_samples = bytes_to_int_samples_pcm(frames, bits_per_sample, channels)
        float_samples = pcm_int_to_float64(int_samples, bits_per_sample)
    else:
        float_samples = bytes_to_float_samples_ieee(frames, bits_per_sample, channels)

    if not float_samples:
        return np.zeros((0, channels), dtype=np.float64), sample_rate_hz

    samples = np.asarray(float_samples, dtype=np.float64)
    total = (len(samples) // channels) * channels
    if total != len(samples):
        samples = samples[:total]
    return samples.reshape(-1, channels), sample_rate_hz


def _design_lowpass_fir(cutoff: float, taps: int) -> np.ndarray:
    if taps <= 1 or taps % 2 == 0:
        raise ValueError("FIR taps must be an odd integer >= 3.")
    n = np.arange(taps, dtype=np.float64)
    center = (taps - 1) / 2.0
    sinc_arg = 2.0 * cutoff * (n - center)
    kernel = 2.0 * cutoff * np.sinc(sinc_arg)
    window = np.hanning(taps)
    kernel *= window
    norm = np.sum(kernel)
    if abs(norm) < _EPSILON:
        raise ValueError("Invalid FIR design (zero gain).")
    kernel /= norm
    return kernel.astype(np.float64)


def _apply_biquad(samples: np.ndarray, b: Iterable[float], a: Iterable[float]) -> np.ndarray:
    b0, b1, b2 = b
    _, a1, a2 = a
    output = np.zeros_like(samples, dtype=np.float64)
    x1 = 0.0
    x2 = 0.0
    y1 = 0.0
    y2 = 0.0
    for index, x0 in enumerate(samples):
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        output[index] = y0
        x2 = x1
        x1 = x0
        y2 = y1
        y1 = y0
    return output


def _biquad_highpass(fs: int, f0: float, q: float) -> Tuple[np.ndarray, np.ndarray]:
    w0 = 2.0 * math.pi * f0 / fs
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * q)
    b0 = (1.0 + cos_w0) / 2.0
    b1 = -(1.0 + cos_w0)
    b2 = (1.0 + cos_w0) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha
    b = np.array([b0 / a0, b1 / a0, b2 / a0], dtype=np.float64)
    a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)
    return b, a


def _biquad_highshelf(
    fs: int, f0: float, gain_db: float, slope: float
) -> Tuple[np.ndarray, np.ndarray]:
    w0 = 2.0 * math.pi * f0 / fs
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    a = 10.0 ** (gain_db / 40.0)
    alpha = sin_w0 / 2.0 * math.sqrt((a + 1.0 / a) * (1.0 / slope - 1.0) + 2.0)
    b0 = a * ((a + 1.0) + (a - 1.0) * cos_w0 + 2.0 * math.sqrt(a) * alpha)
    b1 = -2.0 * a * ((a - 1.0) + (a + 1.0) * cos_w0)
    b2 = a * ((a + 1.0) + (a - 1.0) * cos_w0 - 2.0 * math.sqrt(a) * alpha)
    a0 = (a + 1.0) - (a - 1.0) * cos_w0 + 2.0 * math.sqrt(a) * alpha
    a1 = 2.0 * ((a - 1.0) - (a + 1.0) * cos_w0)
    a2 = (a + 1.0) - (a - 1.0) * cos_w0 - 2.0 * math.sqrt(a) * alpha
    b = np.array([b0 / a0, b1 / a0, b2 / a0], dtype=np.float64)
    a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)
    return b, a


def _k_weighted(samples: np.ndarray, fs: int) -> np.ndarray:
    hp_b, hp_a = _biquad_highpass(fs, _K_WEIGHTING_HP_F0, _K_WEIGHTING_HP_Q)
    hs_b, hs_a = _biquad_highshelf(
        fs, _K_WEIGHTING_HS_F0, _K_WEIGHTING_HS_GAIN_DB, _K_WEIGHTING_HS_SLOPE
    )
    filtered = _apply_biquad(samples, hp_b, hp_a)
    filtered = _apply_biquad(filtered, hs_b, hs_a)
    return filtered


def _block_energies(
    samples: np.ndarray, fs: int, block_s: float, hop_s: float
) -> list[float]:
    block_size = int(round(block_s * fs))
    hop_size = int(round(hop_s * fs))
    if block_size <= 0 or hop_size <= 0:
        return []
    if samples.shape[0] < block_size:
        return []
    energies: list[float] = []
    for start in range(0, samples.shape[0] - block_size + 1, hop_size):
        block = samples[start : start + block_size]
        block_energy = float(np.mean(block * block, axis=0).sum())
        energies.append(block_energy)
    return energies


def compute_true_peak_dbtp_wav(path: Path) -> float:
    """Compute true-peak (dBTP) using 4x oversampling FIR."""
    samples, _ = _read_wav_float64(path)
    if samples.size == 0:
        return float("-inf")
    kernel = _design_lowpass_fir(cutoff=0.25, taps=_TRUEPEAK_TAPS)
    max_peak = 0.0
    for channel_index in range(samples.shape[1]):
        channel = samples[:, channel_index]
        upsampled = np.zeros(channel.shape[0] * _TRUEPEAK_UPSAMPLE, dtype=np.float64)
        upsampled[:: _TRUEPEAK_UPSAMPLE] = channel
        filtered = np.convolve(upsampled, kernel, mode="same")
        channel_peak = float(np.max(np.abs(filtered)))
        if channel_peak > max_peak:
            max_peak = channel_peak
    if max_peak <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(max_peak)


def compute_lufs_integrated_wav(path: Path) -> float:
    """Compute integrated loudness (LUFS) per ITU-style gating."""
    samples, sample_rate_hz = _read_wav_float64(path)
    if samples.size == 0:
        return float("-inf")

    weighted = np.zeros_like(samples, dtype=np.float64)
    for channel_index in range(samples.shape[1]):
        weighted[:, channel_index] = _k_weighted(samples[:, channel_index], sample_rate_hz)

    energies = _block_energies(weighted, sample_rate_hz, block_s=0.4, hop_s=0.1)
    if not energies:
        return float("-inf")

    abs_threshold = 10.0 ** ((-70.0 - _LOUDNESS_OFFSET) / 10.0)
    energies = [energy for energy in energies if energy > abs_threshold]
    if not energies:
        return float("-inf")

    mean_energy = float(np.mean(energies))
    rel_threshold = mean_energy / 10.0
    gated = [energy for energy in energies if energy > rel_threshold]
    if not gated:
        return float("-inf")

    gated_energy = float(np.mean(gated))
    if gated_energy <= 0.0:
        return float("-inf")
    return _LOUDNESS_OFFSET + 10.0 * math.log10(gated_energy)


def compute_lufs_shortterm_wav(path: Path) -> float:
    """Compute short-term loudness (LUFS) over 3s windows."""
    samples, sample_rate_hz = _read_wav_float64(path)
    if samples.size == 0:
        return float("-inf")

    weighted = np.zeros_like(samples, dtype=np.float64)
    for channel_index in range(samples.shape[1]):
        weighted[:, channel_index] = _k_weighted(samples[:, channel_index], sample_rate_hz)

    energies = _block_energies(weighted, sample_rate_hz, block_s=3.0, hop_s=1.0)
    if not energies:
        return float("-inf")
    mean_energy = float(np.mean(energies))
    if mean_energy <= 0.0:
        return float("-inf")
    return _LOUDNESS_OFFSET + 10.0 * math.log10(mean_energy)
