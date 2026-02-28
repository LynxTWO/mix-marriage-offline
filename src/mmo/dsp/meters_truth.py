from __future__ import annotations

from functools import lru_cache
import math
import wave
from pathlib import Path
from typing import Iterable, Tuple

from dataclasses import dataclass

import numpy as np

from mmo.core.loudness_methods import (
    DEFAULT_LOUDNESS_METHOD_ID,
    require_implemented_loudness_method,
)
from mmo.resources import ontology_dir
from mmo.dsp.float64 import (
    bytes_to_float_samples_ieee,
    bytes_to_int_samples_pcm,
    pcm_int_to_float64,
)
from mmo.dsp.io import read_wav_metadata
from mmo.dsp.channel_layout import (
    lufs_weighting_order_and_mode,
)

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

_EPSILON = 1e-12
_TRUEPEAK_UPSAMPLE = 4
_TRUEPEAK_TAPS = 63
_LOUDNESS_OFFSET = -0.691
_TRUEPEAK_PHASE_TAPS = 12
_TRUEPEAK_BLOCK = 262144
_BS1770_5_METHOD_ID = "BS.1770-5"

_SHORT_LABEL_TO_SPK_ID: dict[str, str] = {
    "M": "SPK.M",
    "FL": "SPK.L",
    "FR": "SPK.R",
    "FC": "SPK.C",
    "LFE": "SPK.LFE",
    "LFE2": "SPK.LFE2",
    "BL": "SPK.LRS",
    "BR": "SPK.RRS",
    # Treat SDDS FLC/FRC as front wides for BS.1770-5 Table 4 weighting.
    "FLC": "SPK.LW",
    "FRC": "SPK.RW",
    "BC": "SPK.BC",
    "SL": "SPK.LS",
    "SR": "SPK.RS",
    "TC": "SPK.TC",
    "TFL": "SPK.TFL",
    "TFC": "SPK.TFC",
    "TFR": "SPK.TFR",
    "TBL": "SPK.TRL",
    "TBC": "SPK.TBC",
    "TBR": "SPK.TRR",
}

_DEFAULT_SPEAKER_COORDS: dict[str, tuple[float, float]] = {
    "SPK.M": (0.0, 0.0),
    "SPK.L": (30.0, 0.0),
    "SPK.R": (-30.0, 0.0),
    "SPK.C": (0.0, 0.0),
    "SPK.LFE": (0.0, 0.0),
    "SPK.LFE2": (0.0, 0.0),
    "SPK.LW": (60.0, 0.0),
    "SPK.RW": (-60.0, 0.0),
    "SPK.LS": (110.0, 0.0),
    "SPK.RS": (-110.0, 0.0),
    "SPK.LRS": (150.0, 0.0),
    "SPK.RRS": (-150.0, 0.0),
    "SPK.BC": (180.0, 0.0),
    "SPK.TC": (0.0, 90.0),
    "SPK.TFL": (30.0, 45.0),
    "SPK.TFR": (-30.0, 45.0),
    "SPK.TRL": (150.0, 45.0),
    "SPK.TRR": (-150.0, 45.0),
    "SPK.TFC": (0.0, 45.0),
    "SPK.TBC": (180.0, 45.0),
}


@dataclass
class _BiquadState:
    x1: float = 0.0
    x2: float = 0.0
    y1: float = 0.0
    y2: float = 0.0


@dataclass(frozen=True)
class LoudnessWeightingReceipt:
    method_id: str
    order_csv: str
    mode_str: str
    warnings: tuple[str, ...]


def _is_lfe_label(position_label: str) -> bool:
    return str(position_label).upper().startswith("LFE")


def _is_lfe_speaker_id(speaker_id: str | None) -> bool:
    if speaker_id is None:
        return False
    return speaker_id.upper().startswith("SPK.LFE")


def _bs1770_table4_gain(azimuth_deg: float, elevation_deg: float) -> float:
    abs_phi = abs(float(elevation_deg))
    abs_theta = abs(float(azimuth_deg))
    if abs_phi < 30.0:
        if abs_theta < 60.0:
            return 1.0
        if abs_theta <= 120.0:
            return 1.41
        if abs_theta <= 180.0:
            return 1.0
    return 1.0


@lru_cache(maxsize=1)
def _speaker_coords_from_ontology() -> dict[str, tuple[float, float]]:
    coords = dict(_DEFAULT_SPEAKER_COORDS)
    if yaml is None:
        return coords

    path = ontology_dir() / "speakers.yaml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return coords
    if not isinstance(payload, dict):
        return coords

    speakers = payload.get("speakers")
    if not isinstance(speakers, dict):
        return coords

    for speaker_id, value in speakers.items():
        if not isinstance(speaker_id, str) or not speaker_id.startswith("SPK."):
            continue
        if not isinstance(value, dict):
            continue
        azimuth = value.get("azimuth_deg")
        elevation = value.get("elevation_deg")
        if (
            isinstance(azimuth, bool)
            or not isinstance(azimuth, (int, float))
            or isinstance(elevation, bool)
            or not isinstance(elevation, (int, float))
        ):
            continue
        coords[speaker_id] = (float(azimuth), float(elevation))
    return coords


def _position_label_to_speaker_id(position_label: str) -> str | None:
    normalized = str(position_label).strip().upper()
    if not normalized:
        return None
    return _SHORT_LABEL_TO_SPK_ID.get(normalized)


def _bs1770_weighting_info_with_receipt(
    channels: int,
    wav_channel_mask: int | None,
    channel_layout: str | None = None,
) -> tuple[np.ndarray, str, str, LoudnessWeightingReceipt]:
    weights = np.ones(channels, dtype=np.float64)
    positions, order_csv, mode_str = lufs_weighting_order_and_mode(
        channels, wav_channel_mask, channel_layout
    )
    warnings: list[str] = []
    if positions is None:
        warnings.append(
            (
                "Channel positions unavailable from WAV channel mask/layout; "
                "defaulting all Gi values to 1.0."
            )
        )
        receipt = LoudnessWeightingReceipt(
            method_id=_BS1770_5_METHOD_ID,
            order_csv=order_csv,
            mode_str=mode_str,
            warnings=tuple(warnings),
        )
        return weights, order_csv, mode_str, receipt

    coords_by_speaker = _speaker_coords_from_ontology()

    for idx, pos in enumerate(positions):
        speaker_id = _position_label_to_speaker_id(pos)
        if _is_lfe_label(pos) or _is_lfe_speaker_id(speaker_id):
            weights[idx] = 0.0
            continue

        if speaker_id is None:
            warnings.append(
                (
                    f"CH{idx}: unknown channel position label {pos!r}; "
                    "defaulting Gi=1.0."
                )
            )
            continue

        coords = coords_by_speaker.get(speaker_id)
        if coords is None:
            warnings.append(
                (
                    f"CH{idx}: missing speaker metadata for {speaker_id}; "
                    "defaulting Gi=1.0."
                )
            )
            continue

        azimuth_deg, elevation_deg = coords
        weights[idx] = _bs1770_table4_gain(azimuth_deg, elevation_deg)

    receipt = LoudnessWeightingReceipt(
        method_id=_BS1770_5_METHOD_ID,
        order_csv=order_csv,
        mode_str=mode_str,
        warnings=tuple(warnings),
    )
    return weights, order_csv, mode_str, receipt


def _weighting_info_with_receipt(
    channels: int,
    wav_channel_mask: int | None,
    channel_layout: str | None,
    *,
    method_id: str | None,
) -> tuple[np.ndarray, str, str, LoudnessWeightingReceipt]:
    resolved_method_id = require_implemented_loudness_method(method_id)
    if resolved_method_id == _BS1770_5_METHOD_ID:
        return _bs1770_weighting_info_with_receipt(
            channels,
            wav_channel_mask,
            channel_layout=channel_layout,
        )
    raise RuntimeError(f"Unhandled loudness method_id: {resolved_method_id}")


def loudness_weighting_receipt(
    channels: int,
    wav_channel_mask: int | None,
    channel_layout: str | None = None,
    *,
    method_id: str | None = DEFAULT_LOUDNESS_METHOD_ID,
) -> LoudnessWeightingReceipt:
    _, _, _, receipt = _weighting_info_with_receipt(
        channels,
        wav_channel_mask,
        channel_layout,
        method_id=method_id,
    )
    return receipt


def bs1770_weighting_info(
    channels: int,
    wav_channel_mask: int | None,
    channel_layout: str | None = None,
) -> tuple[np.ndarray, str, str]:
    """
    Returns (weights, order_csv, mode_str)
    weights: float64 length=channels
    order_csv: inferred positions CSV or "unknown"
    mode_str: deterministic token
    """
    weights, order_csv, mode_str, _ = _weighting_info_with_receipt(
        channels,
        wav_channel_mask,
        channel_layout,
        method_id=_BS1770_5_METHOD_ID,
    )
    return weights, order_csv, mode_str


def _bs1770_gi_weights(
    channels: int,
    channel_mask: int | None,
    channel_layout: str | None = None,
    *,
    method_id: str | None = DEFAULT_LOUDNESS_METHOD_ID,
) -> tuple[np.ndarray, str, str]:
    weights, order_csv, mode_str, _ = _weighting_info_with_receipt(
        channels,
        channel_mask,
        channel_layout,
        method_id=method_id,
    )
    return weights, order_csv, mode_str


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


def _apply_biquad_stateful(
    samples: np.ndarray, b: Iterable[float], a: Iterable[float], state: _BiquadState
) -> np.ndarray:
    b0, b1, b2 = b
    _, a1, a2 = a
    output = np.zeros_like(samples, dtype=np.float64)
    x1 = state.x1
    x2 = state.x2
    y1 = state.y1
    y2 = state.y2
    for index, x0 in enumerate(samples):
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        output[index] = y0
        x2 = x1
        x1 = x0
        y2 = y1
        y1 = y0
    state.x1 = x1
    state.x2 = x2
    state.y1 = y1
    state.y2 = y2
    return output


def k_weighting_biquads(
    sample_rate_hz: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if sample_rate_hz == 48000:
        pre_b = np.array(
            [1.53512485958697, -2.69169618940638, 1.19839281085285],
            dtype=np.float64,
        )
        pre_a = np.array(
            [1.0, -1.69065929318241, 0.73248077421585],
            dtype=np.float64,
        )
        rlb_b = np.array([1.0, -2.0, 1.0], dtype=np.float64)
        rlb_a = np.array(
            [1.0, -1.99004745483398, 0.99007225036621],
            dtype=np.float64,
        )
        return pre_b, pre_a, rlb_b, rlb_a

    f0 = 1681.974450955533
    gain = 3.999843853973347
    q = 0.7071752369554196
    k = math.tan(math.pi * f0 / sample_rate_hz)
    vh = 10.0 ** (gain / 20.0)
    vb = vh ** (0.4996667741545416)
    a0 = 1.0 + k / q + k * k
    pre_b0 = (vh + vb * k / q + k * k) / a0
    pre_b1 = 2.0 * (k * k - vh) / a0
    pre_b2 = (vh - vb * k / q + k * k) / a0
    pre_a1 = 2.0 * (k * k - 1.0) / a0
    pre_a2 = (1.0 - k / q + k * k) / a0
    pre_b = np.array([pre_b0, pre_b1, pre_b2], dtype=np.float64)
    pre_a = np.array([1.0, pre_a1, pre_a2], dtype=np.float64)

    f0 = 38.13547087602444
    q = 0.5003270373238773
    k = math.tan(math.pi * f0 / sample_rate_hz)
    denom = 1.0 + k / q + k * k
    rlb_a1 = 2.0 * (k * k - 1.0) / denom
    rlb_a2 = (1.0 - k / q + k * k) / denom
    rlb_b = np.array([1.0, -2.0, 1.0], dtype=np.float64)
    rlb_a = np.array([1.0, rlb_a1, rlb_a2], dtype=np.float64)
    return pre_b, pre_a, rlb_b, rlb_a


def _k_weighted(samples: np.ndarray, fs: int) -> np.ndarray:
    pre_b, pre_a, rlb_b, rlb_a = k_weighting_biquads(fs)
    filtered = _apply_biquad(samples, pre_b, pre_a)
    filtered = _apply_biquad(filtered, rlb_b, rlb_a)
    return filtered


def _block_energies(
    samples: np.ndarray,
    fs: int,
    block_s: float,
    hop_s: float,
    weights: np.ndarray | None = None,
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
        per_ch = np.mean(block * block, axis=0)
        if weights is None:
            block_energy = float(per_ch.sum())
        else:
            block_energy = float(np.dot(per_ch, weights))
        energies.append(block_energy)
    return energies


class OnlineLufsIntegrated:
    def __init__(
        self,
        sample_rate_hz: int,
        channels: int,
        channel_mask: int | None,
        channel_layout: str | None,
        *,
        method_id: str | None = DEFAULT_LOUDNESS_METHOD_ID,
    ) -> None:
        if channels <= 0:
            raise ValueError("channels must be positive")
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self.method_id = require_implemented_loudness_method(method_id)
        self.weights, _, _ = _bs1770_gi_weights(
            channels,
            channel_mask,
            channel_layout=channel_layout,
            method_id=self.method_id,
        )
        self.block_size = int(round(0.4 * sample_rate_hz))
        self.hop_size = int(round(0.1 * sample_rate_hz))
        self._energies: list[float] = []
        self._buffer = np.zeros((0, channels), dtype=np.float64)
        self._pre_b, self._pre_a, self._rlb_b, self._rlb_a = k_weighting_biquads(
            sample_rate_hz
        )
        self._pre_states = [_BiquadState() for _ in range(channels)]
        self._rlb_states = [_BiquadState() for _ in range(channels)]

    def update(self, chunk_frames: np.ndarray) -> None:
        if chunk_frames.size == 0:
            return
        if chunk_frames.shape[1] != self.channels:
            raise ValueError("chunk_frames channel count mismatch")
        weighted = np.empty_like(chunk_frames, dtype=np.float64)
        for channel_index in range(self.channels):
            channel = chunk_frames[:, channel_index]
            filtered = _apply_biquad_stateful(
                channel, self._pre_b, self._pre_a, self._pre_states[channel_index]
            )
            filtered = _apply_biquad_stateful(
                filtered, self._rlb_b, self._rlb_a, self._rlb_states[channel_index]
            )
            weighted[:, channel_index] = filtered

        if self._buffer.size:
            buffer = np.concatenate([self._buffer, weighted], axis=0)
        else:
            buffer = weighted

        if self.block_size <= 0 or self.hop_size <= 0:
            self._buffer = buffer
            return

        if buffer.shape[0] >= self.block_size:
            block_count = 1 + (buffer.shape[0] - self.block_size) // self.hop_size
            for index in range(block_count):
                start = index * self.hop_size
                block = buffer[start : start + self.block_size]
                per_ch = np.mean(block * block, axis=0)
                block_energy = float(np.dot(per_ch, self.weights))
                self._energies.append(block_energy)
            drop = block_count * self.hop_size
            buffer = buffer[drop:]

        self._buffer = buffer

    def finalize(self) -> float:
        if not self._energies:
            return float("-inf")

        abs_threshold = 10.0 ** ((-70.0 - _LOUDNESS_OFFSET) / 10.0)
        energies = [energy for energy in self._energies if energy > abs_threshold]
        if not energies:
            return float("-inf")

        mean_energy = float(np.mean(energies))
        rel_threshold = mean_energy / 10.0
        energies = [energy for energy in energies if energy > rel_threshold]
        if not energies:
            return float("-inf")

        mean_energy = float(np.mean(energies))
        if mean_energy <= 0.0:
            return float("-inf")
        return _LOUDNESS_OFFSET + 10.0 * math.log10(mean_energy)


def _true_peak_48k_polyphase(channel: np.ndarray) -> float:
    coeffs = np.array(
        [
            [0.0017089843750, -0.0291748046875, -0.0189208984375, -0.0083007812500],
            [0.0109863281250, 0.0292968750000, 0.0330810546875, 0.0148925781250],
            [-0.0196533203125, -0.0517578125000, -0.0582275390625, -0.0266113281250],
            [0.0332031250000, 0.0891113281250, 0.1015625000000, 0.0476074218750],
            [-0.0594482421875, -0.1665039062500, -0.2003173828125, -0.1022949218750],
            [0.1373291015625, 0.4650878906250, 0.7797851562500, 0.9721679687500],
            [0.9721679687500, 0.7797851562500, 0.4650878906250, 0.1373291015625],
            [-0.1022949218750, -0.2003173828125, -0.1665039062500, -0.0594482421875],
            [0.0476074218750, 0.1015625000000, 0.0891113281250, 0.0332031250000],
            [-0.0266113281250, -0.0582275390625, -0.0517578125000, -0.0196533203125],
            [0.0148925781250, 0.0330810546875, 0.0292968750000, 0.0109863281250],
            [-0.0083007812500, -0.0189208984375, -0.0291748046875, 0.0017089843750],
        ],
        dtype=np.float64,
    )
    phase_taps = coeffs.T
    history_len = _TRUEPEAK_PHASE_TAPS - 1
    max_peak = 0.0
    history = np.zeros(history_len, dtype=np.float64)
    index = 0
    while index < channel.shape[0]:
        end = min(index + _TRUEPEAK_BLOCK, channel.shape[0])
        block = channel[index:end]
        work = np.concatenate([history, block])
        for phase in range(_TRUEPEAK_UPSAMPLE):
            conv = np.convolve(work, phase_taps[phase], mode="full")
            block_out = conv[history_len : history_len + block.shape[0]]
            phase_peak = float(np.max(np.abs(block_out))) if block_out.size else 0.0
            if phase_peak > max_peak:
                max_peak = phase_peak
        if block.shape[0] >= history_len:
            history = block[-history_len:]
        else:
            history = np.concatenate([history[block.shape[0] :], block])
        index = end
    return max_peak


class OnlineTruePeak:
    def __init__(self, sample_rate_hz: int, channels: int) -> None:
        if channels <= 0:
            raise ValueError("channels must be positive")
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self._max_peak = 0.0
        self._atten = 0.25
        self._gain_comp = 20.0 * math.log10(float(_TRUEPEAK_UPSAMPLE))
        self._kernel = None
        self._phase_taps = None
        self._histories: list[np.ndarray] = []
        self._fir_states: list[np.ndarray] = []
        self._skip_outputs: list[int] = []
        self._pad = (_TRUEPEAK_TAPS - 1) // 2

        if sample_rate_hz == 48000:
            coeffs = np.array(
                [
                    [0.0017089843750, -0.0291748046875, -0.0189208984375, -0.0083007812500],
                    [0.0109863281250, 0.0292968750000, 0.0330810546875, 0.0148925781250],
                    [-0.0196533203125, -0.0517578125000, -0.0582275390625, -0.0266113281250],
                    [0.0332031250000, 0.0891113281250, 0.1015625000000, 0.0476074218750],
                    [-0.0594482421875, -0.1665039062500, -0.2003173828125, -0.1022949218750],
                    [0.1373291015625, 0.4650878906250, 0.7797851562500, 0.9721679687500],
                    [0.9721679687500, 0.7797851562500, 0.4650878906250, 0.1373291015625],
                    [-0.1022949218750, -0.2003173828125, -0.1665039062500, -0.0594482421875],
                    [0.0476074218750, 0.1015625000000, 0.0891113281250, 0.0332031250000],
                    [-0.0266113281250, -0.0582275390625, -0.0517578125000, -0.0196533203125],
                    [0.0148925781250, 0.0330810546875, 0.0292968750000, 0.0109863281250],
                    [-0.0083007812500, -0.0189208984375, -0.0291748046875, 0.0017089843750],
                ],
                dtype=np.float64,
            )
            self._phase_taps = coeffs.T
            history_len = _TRUEPEAK_PHASE_TAPS - 1
            self._histories = [
                np.zeros(history_len, dtype=np.float64) for _ in range(channels)
            ]
        else:
            self._kernel = _design_lowpass_fir(cutoff=0.25, taps=_TRUEPEAK_TAPS)
            self._fir_states = [
                np.zeros(_TRUEPEAK_TAPS - 1, dtype=np.float64) for _ in range(channels)
            ]
            self._skip_outputs = [self._pad for _ in range(channels)]

    def _update_true_peak_48k(self, channel: np.ndarray, channel_index: int) -> None:
        if channel.size == 0:
            return
        history = self._histories[channel_index]
        history_len = _TRUEPEAK_PHASE_TAPS - 1
        work = np.concatenate([history, channel])
        for phase in range(_TRUEPEAK_UPSAMPLE):
            conv = np.convolve(work, self._phase_taps[phase], mode="full")
            block_out = conv[history_len : history_len + channel.shape[0]]
            if block_out.size:
                phase_peak = float(np.max(np.abs(block_out)))
                if phase_peak > self._max_peak:
                    self._max_peak = phase_peak
        if channel.shape[0] >= history_len:
            history = channel[-history_len:]
        else:
            history = np.concatenate([history[channel.shape[0] :], channel])
        self._histories[channel_index] = history

    def _update_true_peak_fir(self, channel: np.ndarray, channel_index: int) -> None:
        if channel.size == 0:
            return
        upsampled = np.zeros(channel.shape[0] * _TRUEPEAK_UPSAMPLE, dtype=np.float64)
        upsampled[:: _TRUEPEAK_UPSAMPLE] = channel
        state = self._fir_states[channel_index]
        work = np.concatenate([state, upsampled])
        conv = np.convolve(work, self._kernel, mode="full")
        start = state.shape[0]
        end = start + upsampled.shape[0]
        output = conv[start:end]
        skip = self._skip_outputs[channel_index]
        if skip:
            if skip >= output.size:
                self._skip_outputs[channel_index] = skip - output.size
                output = np.zeros(0, dtype=np.float64)
            else:
                output = output[skip:]
                self._skip_outputs[channel_index] = 0
        if output.size:
            peak = float(np.max(np.abs(output)))
            if peak > self._max_peak:
                self._max_peak = peak
        self._fir_states[channel_index] = work[-(_TRUEPEAK_TAPS - 1) :]

    def update(self, chunk_frames: np.ndarray) -> None:
        if chunk_frames.size == 0:
            return
        if chunk_frames.shape[1] != self.channels:
            raise ValueError("chunk_frames channel count mismatch")
        for channel_index in range(self.channels):
            channel = chunk_frames[:, channel_index] * self._atten
            if self.sample_rate_hz == 48000:
                self._update_true_peak_48k(channel, channel_index)
            else:
                self._update_true_peak_fir(channel, channel_index)

    def finalize(self) -> float:
        if self.sample_rate_hz != 48000 and self._kernel is not None:
            tail = np.zeros(self._pad, dtype=np.float64)
            for channel_index in range(self.channels):
                self._update_true_peak_fir(tail, channel_index)
        if self._max_peak <= 0.0:
            return float("-inf")
        return 20.0 * math.log10(self._max_peak) + self._gain_comp


def compute_true_peak_dbtp_wav(path: Path) -> float:
    """Compute true-peak (dBTP) using 4x oversampling FIR."""
    samples, sample_rate_hz = _read_wav_float64(path)
    return compute_true_peak_dbtp_float64(samples, sample_rate_hz)


def compute_true_peak_dbtp_float64(
    samples: np.ndarray, sample_rate_hz: int
) -> float:
    """Compute true-peak (dBTP) from float64 samples."""
    if samples.size == 0:
        return float("-inf")
    atten = 0.25
    gain_comp = 20.0 * math.log10(float(_TRUEPEAK_UPSAMPLE))
    max_peak = 0.0
    kernel = None
    if sample_rate_hz != 48000:
        kernel = _design_lowpass_fir(cutoff=0.25, taps=_TRUEPEAK_TAPS)
    for channel_index in range(samples.shape[1]):
        channel = samples[:, channel_index] * atten
        if sample_rate_hz == 48000:
            channel_peak = _true_peak_48k_polyphase(channel)
        else:
            upsampled = np.zeros(
                channel.shape[0] * _TRUEPEAK_UPSAMPLE, dtype=np.float64
            )
            upsampled[:: _TRUEPEAK_UPSAMPLE] = channel
            filtered = np.convolve(upsampled, kernel, mode="same")
            channel_peak = float(np.max(np.abs(filtered))) if filtered.size else 0.0
        if channel_peak > max_peak:
            max_peak = channel_peak
    if max_peak <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(max_peak) + gain_comp


def compute_true_peak_dbtp_from_chunks(
    chunks: Iterable[np.ndarray], sample_rate_hz: int
) -> float:
    iterator = iter(chunks)
    for first in iterator:
        if first.size == 0:
            continue
        accumulator = OnlineTruePeak(sample_rate_hz, channels=first.shape[1])
        accumulator.update(first)
        for chunk in iterator:
            accumulator.update(chunk)
        return accumulator.finalize()
    return float("-inf")


def compute_lufs_integrated_wav(
    path: Path,
    *,
    method_id: str | None = DEFAULT_LOUDNESS_METHOD_ID,
) -> float:
    """Compute integrated loudness (LUFS) per ITU-style gating."""
    metadata = read_wav_metadata(path)
    channels = int(metadata["channels"])
    channel_mask = metadata.get("channel_mask")
    samples, sample_rate_hz = _read_wav_float64(path)
    return compute_lufs_integrated_float64(
        samples,
        sample_rate_hz,
        channels,
        channel_mask=channel_mask,
        channel_layout=None,
        method_id=method_id,
    )


def compute_lufs_shortterm_wav(
    path: Path,
    *,
    method_id: str | None = DEFAULT_LOUDNESS_METHOD_ID,
) -> float:
    """Compute short-term loudness (LUFS) over 3s windows."""
    metadata = read_wav_metadata(path)
    channels = int(metadata["channels"])
    channel_mask = metadata.get("channel_mask")
    samples, sample_rate_hz = _read_wav_float64(path)
    return compute_lufs_shortterm_float64(
        samples,
        sample_rate_hz,
        channels,
        channel_mask=channel_mask,
        channel_layout=None,
        method_id=method_id,
    )


def _compute_lufs_from_samples(
    samples: np.ndarray,
    sample_rate_hz: int,
    weights: np.ndarray,
    *,
    block_s: float,
    hop_s: float,
    gated: bool,
) -> float:
    if samples.size == 0:
        return float("-inf")

    weighted = np.zeros_like(samples, dtype=np.float64)
    for channel_index in range(samples.shape[1]):
        weighted[:, channel_index] = _k_weighted(samples[:, channel_index], sample_rate_hz)

    energies = _block_energies(
        weighted, sample_rate_hz, block_s=block_s, hop_s=hop_s, weights=weights
    )
    if not energies:
        return float("-inf")

    if gated:
        abs_threshold = 10.0 ** ((-70.0 - _LOUDNESS_OFFSET) / 10.0)
        energies = [energy for energy in energies if energy > abs_threshold]
        if not energies:
            return float("-inf")

        mean_energy = float(np.mean(energies))
        rel_threshold = mean_energy / 10.0
        energies = [energy for energy in energies if energy > rel_threshold]
        if not energies:
            return float("-inf")

    mean_energy = float(np.mean(energies))
    if mean_energy <= 0.0:
        return float("-inf")
    return _LOUDNESS_OFFSET + 10.0 * math.log10(mean_energy)


def compute_lufs_integrated_float64(
    samples: np.ndarray,
    sample_rate_hz: int,
    channels: int,
    *,
    channel_mask: int | None,
    channel_layout: str | None,
    method_id: str | None = DEFAULT_LOUDNESS_METHOD_ID,
) -> float:
    """Compute integrated loudness (LUFS) from float64 samples."""
    weights, _, _ = _bs1770_gi_weights(
        channels,
        channel_mask,
        channel_layout=channel_layout,
        method_id=method_id,
    )
    return _compute_lufs_from_samples(
        samples,
        sample_rate_hz,
        weights,
        block_s=0.4,
        hop_s=0.1,
        gated=True,
    )


def compute_lufs_integrated_from_chunks(
    chunks: Iterable[np.ndarray],
    sample_rate_hz: int,
    channels: int,
    *,
    channel_mask: int | None,
    channel_layout: str | None,
    method_id: str | None = DEFAULT_LOUDNESS_METHOD_ID,
) -> float:
    accumulator = OnlineLufsIntegrated(
        sample_rate_hz,
        channels,
        channel_mask=channel_mask,
        channel_layout=channel_layout,
        method_id=method_id,
    )
    for chunk in chunks:
        accumulator.update(chunk)
    return accumulator.finalize()


def compute_lufs_shortterm_float64(
    samples: np.ndarray,
    sample_rate_hz: int,
    channels: int,
    *,
    channel_mask: int | None,
    channel_layout: str | None,
    method_id: str | None = DEFAULT_LOUDNESS_METHOD_ID,
) -> float:
    """Compute short-term loudness (LUFS) from float64 samples."""
    weights, _, _ = _bs1770_gi_weights(
        channels,
        channel_mask,
        channel_layout=channel_layout,
        method_id=method_id,
    )
    return _compute_lufs_from_samples(
        samples,
        sample_rate_hz,
        weights,
        block_s=3.0,
        hop_s=1.0,
        gated=False,
    )
