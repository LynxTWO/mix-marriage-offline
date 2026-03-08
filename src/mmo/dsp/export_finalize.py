from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass, field
from typing import Any


SUPPORTED_DITHER_POLICIES: tuple[str, ...] = ("none", "tpdf", "tpdf_hp")
DEFAULT_EXPORT_RENDER_SEED = 0
UNKNOWN_EXPORT_JOB_ID = "JOB.UNKNOWN"
UNKNOWN_EXPORT_LAYOUT_ID = "LAYOUT.UNKNOWN"
CLAMP_BEHAVIOR_DESCRIPTION = (
    "Clamp float64 input to [-1.0, 1.0) before quantize; clamp signed PCM "
    "integers to the target bit-depth range after rounding."
)
_FLOAT_MAX = math.nextafter(1.0, 0.0)
_SPLITMIX64_INCREMENT = 0x9E3779B97F4A7C15
_SPLITMIX64_MUL_A = 0xBF58476D1CE4E5B9
_SPLITMIX64_MUL_B = 0x94D049BB133111EB
_MASK_U64 = 0xFFFFFFFFFFFFFFFF


def _normalize_id(value: str | None, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _clamp_sample(value: float) -> float:
    if value < -1.0:
        return -1.0
    if value > _FLOAT_MAX:
        return _FLOAT_MAX
    return value


def _pcm_scale(bit_depth: int) -> int:
    if bit_depth not in (16, 24, 32):
        raise ValueError(f"Unsupported PCM bit depth: {bit_depth}")
    return 1 << (bit_depth - 1)


def _normalize_dither_policy(dither_policy: str) -> str:
    policy = str(dither_policy).strip().lower()
    if policy not in SUPPORTED_DITHER_POLICIES:
        allowed = ", ".join(SUPPORTED_DITHER_POLICIES)
        raise ValueError(f"Unsupported dither_policy {dither_policy!r}. Allowed: {allowed}.")
    return policy


def default_dither_policy_for_bit_depth(bit_depth: int) -> str:
    _pcm_scale(bit_depth)
    if bit_depth == 16:
        return "tpdf"
    return "none"


def resolve_dither_policy_for_bit_depth(
    bit_depth: int,
    requested_policy: str | None = None,
) -> str:
    if requested_policy is None:
        return default_dither_policy_for_bit_depth(bit_depth)
    return _normalize_dither_policy(requested_policy)


def derive_export_finalization_seed(
    *,
    job_id: str,
    layout_id: str,
    stem_id: str | None = None,
    render_seed: int = DEFAULT_EXPORT_RENDER_SEED,
) -> int:
    material = "\x1f".join(
        (
            _normalize_id(job_id, UNKNOWN_EXPORT_JOB_ID),
            _normalize_id(layout_id, UNKNOWN_EXPORT_LAYOUT_ID),
            stem_id.strip() if isinstance(stem_id, str) else "",
            str(int(render_seed)),
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def build_export_finalization_receipt(
    *,
    bit_depth: int,
    dither_policy: str,
    job_id: str,
    layout_id: str,
    stem_id: str | None = None,
    render_seed: int = DEFAULT_EXPORT_RENDER_SEED,
    target_peak_dbfs: float | None = None,
) -> dict[str, Any]:
    resolved_policy = resolve_dither_policy_for_bit_depth(bit_depth, dither_policy)
    receipt: dict[str, Any] = {
        "bit_depth": int(bit_depth),
        "dither_policy": resolved_policy,
        "seed_derivation": {
            "algorithm": "sha256_v1",
            "job_id": _normalize_id(job_id, UNKNOWN_EXPORT_JOB_ID),
            "layout_id": _normalize_id(layout_id, UNKNOWN_EXPORT_LAYOUT_ID),
            "render_seed": int(render_seed),
        },
        "clamp_behavior": CLAMP_BEHAVIOR_DESCRIPTION,
        "target_peak_dbfs": (
            round(float(target_peak_dbfs), 6)
            if target_peak_dbfs is not None
            else None
        ),
    }
    if isinstance(stem_id, str) and stem_id.strip():
        receipt["seed_derivation"]["stem_id"] = stem_id.strip()
    return receipt


class _DeterministicRng:
    def __init__(self, seed: int) -> None:
        self._state = int(seed) & _MASK_U64

    def random(self) -> float:
        self._state = (self._state + _SPLITMIX64_INCREMENT) & _MASK_U64
        value = self._state
        value = ((value ^ (value >> 30)) * _SPLITMIX64_MUL_A) & _MASK_U64
        value = ((value ^ (value >> 27)) * _SPLITMIX64_MUL_B) & _MASK_U64
        value ^= value >> 31
        return float((value >> 11) & ((1 << 53) - 1)) / float(1 << 53)


@dataclass
class _ExportFinalizeState:
    channels: int
    rng: _DeterministicRng | None = None
    previous_tpdf_by_channel: list[float] = field(default_factory=list)

    @classmethod
    def from_seed(
        cls,
        *,
        channels: int,
        dither_policy: str,
        seed: int,
    ) -> _ExportFinalizeState:
        rng: _DeterministicRng | None = None
        previous_tpdf_by_channel: list[float] = []
        if dither_policy != "none":
            rng = _DeterministicRng(seed)
            previous_tpdf_by_channel = [0.0] * channels
        return cls(
            channels=channels,
            rng=rng,
            previous_tpdf_by_channel=previous_tpdf_by_channel,
        )


def _tpdf_noise(
    *,
    state: _ExportFinalizeState,
    scale: int,
    channel_index: int,
    dither_policy: str,
) -> float:
    if state.rng is None:
        return 0.0

    raw_tpdf = (state.rng.random() - state.rng.random()) / float(scale)
    if dither_policy != "tpdf_hp":
        return raw_tpdf

    previous = state.previous_tpdf_by_channel[channel_index]
    state.previous_tpdf_by_channel[channel_index] = raw_tpdf
    return raw_tpdf - previous


def _int_samples_to_bytes(samples: list[int], bit_depth: int) -> bytes:
    if bit_depth == 16:
        return struct.pack(f"<{len(samples)}h", *samples)
    if bit_depth == 24:
        output = bytearray(len(samples) * 3)
        for index, sample in enumerate(samples):
            value = sample & 0xFFFFFF
            offset = index * 3
            output[offset : offset + 3] = (
                value & 0xFF,
                (value >> 8) & 0xFF,
                (value >> 16) & 0xFF,
            )
        return bytes(output)
    if bit_depth == 32:
        return struct.pack(f"<{len(samples)}i", *samples)
    raise ValueError(f"Unsupported PCM bit depth: {bit_depth}")


def _export_finalize_bytes(
    samples: list[float],
    *,
    channels: int,
    bit_depth: int,
    dither_policy: str,
    state: _ExportFinalizeState,
) -> bytes:
    if channels <= 0:
        raise ValueError("channels must be > 0")
    if len(samples) % channels != 0:
        raise ValueError("interleaved sample data must be frame-aligned")

    scale = _pcm_scale(bit_depth)
    min_int = -scale
    max_int = scale - 1
    pcm_samples: list[int] = []
    for sample_index, raw_sample in enumerate(samples):
        value = _clamp_sample(float(raw_sample))
        if dither_policy != "none":
            channel_index = sample_index % channels
            value = _clamp_sample(
                value + _tpdf_noise(
                    state=state,
                    scale=scale,
                    channel_index=channel_index,
                    dither_policy=dither_policy,
                )
            )
        quantized = int(round(value * float(scale)))
        if quantized < min_int:
            quantized = min_int
        elif quantized > max_int:
            quantized = max_int
        pcm_samples.append(quantized)
    return _int_samples_to_bytes(pcm_samples, bit_depth)


def export_finalize_interleaved_f64(
    samples: list[float],
    *,
    channels: int,
    bit_depth: int,
    dither_policy: str,
    seed: int,
) -> bytes:
    resolved_policy = resolve_dither_policy_for_bit_depth(bit_depth, dither_policy)
    state = _ExportFinalizeState.from_seed(
        channels=channels,
        dither_policy=resolved_policy,
        seed=seed,
    )
    return _export_finalize_bytes(
        samples,
        channels=channels,
        bit_depth=bit_depth,
        dither_policy=resolved_policy,
        state=state,
    )


class StreamingExportFinalizer:
    def __init__(
        self,
        *,
        channels: int,
        bit_depth: int,
        dither_policy: str,
        seed: int,
    ) -> None:
        self.channels = int(channels)
        self.bit_depth = int(bit_depth)
        self.dither_policy = resolve_dither_policy_for_bit_depth(
            self.bit_depth,
            dither_policy,
        )
        self._state = _ExportFinalizeState.from_seed(
            channels=self.channels,
            dither_policy=self.dither_policy,
            seed=seed,
        )

    def finalize_chunk(self, samples: list[float]) -> bytes:
        return _export_finalize_bytes(
            samples,
            channels=self.channels,
            bit_depth=self.bit_depth,
            dither_policy=self.dither_policy,
            state=self._state,
        )
