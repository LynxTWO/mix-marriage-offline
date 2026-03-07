"""binaural_preview_v0: Conservative headphone virtualization preview renderer.

This module adds a deterministic, layout-aware headphone preview path for
multichannel program material.  It is intentionally conservative:

- Mild ILD/ITD cues only (no aggressive HRTF coloration)
- RMS gate to avoid lifting noise floors
- LFE attenuation to avoid headphone over-emphasis
- Layout-safe speaker routing via ``LayoutContext``
- Standards declared for SMPTE, FILM, LOGIC_PRO, VST3, and AAF

Primary usage is "preview" rendering for headphones, not final release output.
"""

from __future__ import annotations

import math
import re
import wave
from pathlib import Path
from typing import Any, Mapping

from mmo.core.speaker_layout import (
    LayoutStandard,
    SpeakerLayout,
    SpeakerPosition,
    get_preset,
)
from mmo.dsp.io import read_wav_metadata, sha256_file
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.dsp.plugins.base import (
    LayoutContext,
    ProcessContext,
    PluginContext,
    PluginEvidenceCollector,
    optional_float_param,
    parse_bypass_for_stage,
    parse_macro_mix_for_stage,
)

PLUGIN_ID = "binaural_preview_v0"
PREVIEW_RENDERER_ID = "PLUGIN.RENDERER.BINAURAL_PREVIEW_V0"
PREVIEW_ACTION_ID = "ACTION.UTILITY.PREVIEW_HEADPHONES"
PREVIEW_REC_ID = "REC.HEADPHONE_PREVIEW.UNSPECIFIED"

SUPPORTED_STANDARDS = ("SMPTE", "FILM", "LOGIC_PRO", "VST3", "AAF")
PREFERRED_STANDARD = "SMPTE"

_EPSILON = 1e-12

_SUPPORTED_WAV_BITS = (16, 24, 32)
_DEFAULT_LAYOUT_BY_CHANNEL_COUNT: dict[int, str] = {
    2: "LAYOUT.2_0",
    3: "LAYOUT.2_1",
    6: "LAYOUT.5_1",
    8: "LAYOUT.7_1",
    10: "LAYOUT.5_1_4",
    12: "LAYOUT.7_1_4",
}

_STANDARD_FALLBACKS: dict[str, tuple[str, ...]] = {
    "SMPTE": ("SMPTE",),
    "FILM": ("FILM", "SMPTE"),
    "LOGIC_PRO": ("LOGIC_PRO", "SMPTE"),
    "VST3": ("VST3", "SMPTE"),
    # AAF/OMF interchange commonly carries cinema-biased ordering metadata.
    # Prefer FILM mapping first, then fall back to SMPTE when no preset exists.
    "AAF": ("FILM", "SMPTE"),
}

_SPEAKER_AZIMUTH_DEG: dict[SpeakerPosition, float] = {
    SpeakerPosition.M: 0.0,
    SpeakerPosition.FL: -30.0,
    SpeakerPosition.FR: 30.0,
    SpeakerPosition.FC: 0.0,
    SpeakerPosition.LFE: 0.0,
    SpeakerPosition.SL: -110.0,
    SpeakerPosition.SR: 110.0,
    SpeakerPosition.BL: -150.0,
    SpeakerPosition.BR: 150.0,
    SpeakerPosition.TFL: -35.0,
    SpeakerPosition.TFR: 35.0,
    SpeakerPosition.TBL: -145.0,
    SpeakerPosition.TBR: 145.0,
    SpeakerPosition.TFC: 0.0,
    SpeakerPosition.TBC: 180.0,
    SpeakerPosition.TC: 0.0,
    SpeakerPosition.FLW: -60.0,
    SpeakerPosition.FRW: 60.0,
    SpeakerPosition.FLC: -16.0,
    SpeakerPosition.FRC: 16.0,
    SpeakerPosition.BC: 180.0,
}

_BASE_GAIN_DB: dict[SpeakerPosition, float] = {
    SpeakerPosition.M: -1.5,
    SpeakerPosition.FL: 0.0,
    SpeakerPosition.FR: 0.0,
    SpeakerPosition.FC: -1.0,
    SpeakerPosition.SL: -2.0,
    SpeakerPosition.SR: -2.0,
    SpeakerPosition.BL: -2.5,
    SpeakerPosition.BR: -2.5,
    SpeakerPosition.TFL: -3.0,
    SpeakerPosition.TFR: -3.0,
    SpeakerPosition.TBL: -3.5,
    SpeakerPosition.TBR: -3.5,
    SpeakerPosition.TFC: -3.0,
    SpeakerPosition.TBC: -3.5,
    SpeakerPosition.TC: -3.0,
    SpeakerPosition.FLW: -1.0,
    SpeakerPosition.FRW: -1.0,
    SpeakerPosition.FLC: -1.5,
    SpeakerPosition.FRC: -1.5,
    SpeakerPosition.BC: -3.0,
}


def _db_to_gain(db_value: float) -> float:
    return math.pow(10.0, float(db_value) / 20.0)


def _dbfs_rms(samples: Any) -> float:
    mean_square = float((samples * samples).mean()) if samples.size else 0.0
    if mean_square <= _EPSILON:
        return float("-inf")
    return 10.0 * math.log10(mean_square)


def _peak_dbfs(samples: Any) -> float:
    if not samples.size:
        return float("-inf")
    peak = float(abs(samples).max())
    if peak <= _EPSILON:
        return float("-inf")
    return 20.0 * math.log10(peak)


def _normalize_standard(layout_standard: str) -> str:
    candidate = str(layout_standard).strip().upper()
    if candidate in SUPPORTED_STANDARDS:
        return candidate
    return PREFERRED_STANDARD


def _standard_candidates(layout_standard: str) -> tuple[str, ...]:
    normalized = _normalize_standard(layout_standard)
    return _STANDARD_FALLBACKS.get(normalized, (PREFERRED_STANDARD,))


def _bit_depth_for_output(bits_per_sample: int) -> int:
    if bits_per_sample in _SUPPORTED_WAV_BITS:
        return bits_per_sample
    return 24


def _speaker_for_slot(layout_ctx: LayoutContext, slot: int) -> SpeakerPosition:
    layout = layout_ctx.layout
    order = getattr(layout, "channel_order", ())
    if isinstance(order, tuple) and 0 <= slot < len(order):
        pos = order[slot]
        if isinstance(pos, SpeakerPosition):
            return pos
    return SpeakerPosition.M


def _resolve_preview_layout(
    *,
    channel_count: int,
    layout_standard: str,
    layout_id_hint: str | None,
) -> SpeakerLayout:
    normalized_standard = _normalize_standard(layout_standard)
    candidates = _standard_candidates(normalized_standard)

    if isinstance(layout_id_hint, str) and layout_id_hint.strip():
        hint = layout_id_hint.strip()
        for standard in candidates:
            preferred = get_preset(hint, standard)
            if preferred is not None and preferred.num_channels == channel_count:
                return preferred

    if channel_count == 1:
        mono_standard = candidates[0] if candidates else PREFERRED_STANDARD
        return SpeakerLayout(
            layout_id="LAYOUT.1_0",
            standard=LayoutStandard[_normalize_standard(mono_standard)],
            channel_order=(SpeakerPosition.M,),
        )

    layout_id = _DEFAULT_LAYOUT_BY_CHANNEL_COUNT.get(channel_count)
    if not layout_id:
        raise ValueError(
            "Unsupported channel count for headphone preview: "
            f"{channel_count}."
        )

    for standard in candidates:
        preferred = get_preset(layout_id, standard)
        if preferred is not None and preferred.num_channels == channel_count:
            return preferred

    raise ValueError(
        "Unable to resolve a layout preset for headphone preview: "
        f"layout_id={layout_id}, requested_standard={normalized_standard}, "
        f"candidates={candidates}, channels={channel_count}."
    )


def _add_shifted(target: Any, source: Any, *, gain: float, delay_samples: int) -> None:
    if abs(gain) <= _EPSILON:
        return
    total = int(source.shape[0])
    delay = int(max(0, delay_samples))
    end = delay + total
    if delay >= target.shape[0] or end <= delay:
        return
    if end > target.shape[0]:
        usable = max(0, target.shape[0] - delay)
        if usable <= 0:
            return
        target[delay:] += source[:usable] * gain
        return
    target[delay:end] += source * gain


def _dry_fold_stereo(
    buf_f32_or_f64: Any,
    layout_ctx: LayoutContext,
) -> Any:
    import numpy as np

    channel_count = int(buf_f32_or_f64.shape[0])
    frame_count = int(buf_f32_or_f64.shape[1])

    left = np.zeros(frame_count, dtype=np.float64)
    right = np.zeros(frame_count, dtype=np.float64)

    for slot in range(channel_count):
        pos = _speaker_for_slot(layout_ctx, slot)
        channel = buf_f32_or_f64[slot].astype(np.float64, copy=False)

        if pos in {SpeakerPosition.FL, SpeakerPosition.FLC, SpeakerPosition.FLW}:
            left += channel
        elif pos in {SpeakerPosition.FR, SpeakerPosition.FRC, SpeakerPosition.FRW}:
            right += channel
        elif pos in {SpeakerPosition.SL, SpeakerPosition.BL, SpeakerPosition.TFL, SpeakerPosition.TBL}:
            left += channel * 0.5
        elif pos in {SpeakerPosition.SR, SpeakerPosition.BR, SpeakerPosition.TFR, SpeakerPosition.TBR}:
            right += channel * 0.5
        elif pos == SpeakerPosition.LFE:
            left += channel * 0.25
            right += channel * 0.25
        else:
            left += channel * 0.7071067811865476
            right += channel * 0.7071067811865476

    folded = np.vstack([left, right])
    peak = float(abs(folded).max()) if folded.size else 0.0
    if peak > 1.0:
        folded = folded * (1.0 / peak)
    return np.clip(folded, -1.0, 1.0)


def _speaker_pan(position: SpeakerPosition) -> float:
    azimuth = _SPEAKER_AZIMUTH_DEG.get(position, 0.0)
    return max(-1.0, min(1.0, azimuth / 150.0))


def _one_pole_lowpass(
    signal: Any,
    *,
    sample_rate_hz: int,
    cutoff_hz: float,
) -> Any:
    import numpy as np

    samples = np.asarray(signal, dtype=np.float64)
    if samples.size == 0:
        return samples
    if sample_rate_hz <= 0:
        return samples.copy()
    cutoff = max(20.0, min(float(cutoff_hz), float(sample_rate_hz) * 0.49))
    alpha = math.exp(-2.0 * math.pi * cutoff / float(sample_rate_hz))
    out = np.empty_like(samples)
    prev = 0.0
    for idx in range(samples.size):
        current = float(samples[idx])
        prev = ((1.0 - alpha) * current) + (alpha * prev)
        out[idx] = prev
    return out


def _conservative_hrtf_pair(
    *,
    channel: Any,
    sample_rate_hz: int,
    position: SpeakerPosition,
    width: float,
    hrtf_amount: float,
) -> tuple[Any, Any]:
    if position == SpeakerPosition.LFE or hrtf_amount <= 0.0:
        return channel, channel

    pan = _speaker_pan(position)
    abs_pan = abs(pan)
    if abs_pan <= 1e-3:
        return channel, channel

    width_clamped = max(0.20, min(1.40, float(width)))
    amount = max(0.0, min(1.0, float(hrtf_amount)))
    shadow_strength = abs_pan * width_clamped * amount
    cutoff_hz = 6800.0 - (4800.0 * shadow_strength)
    far_lowpassed = _one_pole_lowpass(
        channel,
        sample_rate_hz=sample_rate_hz,
        cutoff_hz=cutoff_hz,
    )
    filtered_weight = 0.55 + (0.35 * amount)
    far_ear = (far_lowpassed * filtered_weight) + (channel * (1.0 - filtered_weight))
    return channel, far_ear


def _speaker_binaural_parameters(
    *,
    position: SpeakerPosition,
    sample_rate_hz: int,
    width: float,
    lfe_trim_db: float,
) -> tuple[float, float, int, int, float, int, float]:
    if position == SpeakerPosition.LFE:
        gain = _db_to_gain(lfe_trim_db)
        return gain, gain, 0, 0, 0.0, 0, 0.0

    pan = _speaker_pan(position)
    abs_pan = abs(pan)

    base_gain_db = _BASE_GAIN_DB.get(position, -2.0)
    near_gain = _db_to_gain(base_gain_db)
    far_gain = near_gain * _db_to_gain(-(1.5 + (4.0 * abs_pan * width)))

    max_itd_seconds = 0.00025
    itd_samples = int(round(max_itd_seconds * abs_pan * width * float(sample_rate_hz)))

    if pan < 0.0:
        left_gain = near_gain
        right_gain = far_gain
        left_delay = 0
        right_delay = itd_samples
    elif pan > 0.0:
        left_gain = far_gain
        right_gain = near_gain
        left_delay = itd_samples
        right_delay = 0
    else:
        center_gain = near_gain * 0.92
        left_gain = center_gain
        right_gain = center_gain
        left_delay = 0
        right_delay = 0

    # Mild delayed crossfeed improves externalization without exaggerated effects.
    crossfeed_gain = _db_to_gain(-15.0) * width
    crossfeed_delay = int(round(0.00035 * float(sample_rate_hz)))

    return (
        left_gain,
        right_gain,
        left_delay,
        right_delay,
        crossfeed_gain,
        crossfeed_delay,
        pan,
    )


def _to_pcm_bytes(float_samples: Any, bit_depth: int) -> bytes:
    import numpy as np

    samples64 = np.asarray(float_samples, dtype=np.float64)

    if bit_depth == 16:
        scaled = np.rint(samples64 * float(2**15))
        clamped = np.clip(scaled, -32768.0, 32767.0).astype("<i2")
        return clamped.tobytes()

    if bit_depth == 24:
        scaled = np.rint(samples64 * float(2**23))
        clamped = np.clip(scaled, -8388608.0, 8388607.0).astype(np.int32)
        unsigned = (clamped & 0xFFFFFF).astype(np.uint32)
        data = np.empty(unsigned.size * 3, dtype=np.uint8)
        data[0::3] = (unsigned & 0xFF).astype(np.uint8)
        data[1::3] = ((unsigned >> 8) & 0xFF).astype(np.uint8)
        data[2::3] = ((unsigned >> 16) & 0xFF).astype(np.uint8)
        return data.tobytes()

    if bit_depth == 32:
        scaled = np.rint(samples64 * float(2**31))
        clamped = np.clip(scaled, -2147483648.0, 2147483647.0).astype("<i4")
        return clamped.tobytes()

    raise ValueError(f"Unsupported output bit depth: {bit_depth}")


def _write_stereo_wav(
    *,
    float_stereo: Any,
    output_path: Path,
    sample_rate_hz: int,
    bit_depth: int,
) -> None:
    import numpy as np

    stereo = np.asarray(float_stereo, dtype=np.float64)
    if stereo.ndim != 2 or stereo.shape[0] != 2:
        raise ValueError("Headphone preview expects a (2, frames) stereo matrix.")

    interleaved = stereo.T.reshape(-1)
    pcm_bytes = _to_pcm_bytes(interleaved, bit_depth)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(bit_depth // 8)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(pcm_bytes)


def _preview_output_id(source_output: Mapping[str, Any], sha256: str) -> str:
    stem_token = str(source_output.get("target_stem_id") or "").strip()
    if not stem_token:
        stem_token = str(source_output.get("output_id") or "artifact").strip()
    stem_token = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem_token)
    if not stem_token:
        stem_token = "artifact"
    return f"OUTPUT.BINAURAL_PREVIEW.{stem_token}.{sha256[:12]}"


def _source_path_and_preview_file_path(
    *,
    source_file_path: str,
    output_dir: Path | None,
) -> tuple[Path | None, str | None, Path | None]:
    source_path = Path(source_file_path)
    if source_path.is_absolute():
        preview_path = source_path.with_name(f"{source_path.stem}.headphones.wav")
        return source_path, preview_path.as_posix(), preview_path

    if output_dir is None:
        return None, None, None

    preview_rel = source_path.with_name(f"{source_path.stem}.headphones.wav")
    return output_dir / source_path, preview_rel.as_posix(), output_dir / preview_rel


class BinauralPreviewV0Plugin:
    """Conservative deterministic binaural virtualization for headphone preview."""

    plugin_id = PLUGIN_ID
    supported_standards = SUPPORTED_STANDARDS
    preferred_standard = PREFERRED_STANDARD

    def process_multichannel(
        self,
        buf_f32_or_f64: Any,
        sample_rate: int,
        params: dict[str, Any],
        ctx: PluginContext,
        layout_ctx: LayoutContext,
        process_ctx: ProcessContext | None = None,
    ) -> Any:
        del process_ctx
        import numpy as np

        gate_rms_dbfs = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="gate_rms_dbfs",
            default_value=-58.0,
            minimum_value=-90.0,
            maximum_value=-20.0,
        )
        virtualize_width = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="virtualize_width",
            default_value=0.85,
            minimum_value=0.20,
            maximum_value=1.40,
        )
        lfe_trim_db = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="lfe_trim_db",
            default_value=-12.0,
            minimum_value=-30.0,
            maximum_value=0.0,
        )
        output_headroom_db = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="output_headroom_db",
            default_value=1.0,
            minimum_value=0.3,
            maximum_value=6.0,
        )
        hrtf_amount = optional_float_param(
            plugin_id=PLUGIN_ID,
            params=params,
            param_name="hrtf_amount",
            default_value=0.55,
            minimum_value=0.0,
            maximum_value=1.0,
        )
        bypass = parse_bypass_for_stage(plugin_id=PLUGIN_ID, params=params)
        macro_mix, macro_mix_input = parse_macro_mix_for_stage(
            plugin_id=PLUGIN_ID,
            params=params,
        )

        dry = _dry_fold_stereo(buf_f32_or_f64, layout_ctx)
        if bypass:
            ctx.evidence_collector.set(
                stage_what="plugin stage bypassed",
                stage_why="Bypass enabled; returned deterministic dry stereo fold.",
                metrics=[
                    {"name": "stage_index", "value": ctx.stage_index},
                    {"name": "gate_rms_dbfs", "value": gate_rms_dbfs},
                    {"name": "virtualize_width", "value": virtualize_width},
                    {"name": "hrtf_amount", "value": hrtf_amount},
                    {"name": "lfe_trim_db", "value": lfe_trim_db},
                    {"name": "macro_mix", "value": macro_mix},
                    {"name": "macro_mix_input", "value": macro_mix_input},
                    {"name": "bypass", "value": 1.0},
                ],
                notes=[
                    f"layout_standard={layout_ctx.layout.standard.value}",
                    "Gate reference: GATE.DOWNMIX_SIMILARITY_MEASURED verified post-render.",
                ],
            )
            return dry.astype(buf_f32_or_f64.dtype.type, copy=False)

        frame_count = int(buf_f32_or_f64.shape[1])
        channel_count = int(buf_f32_or_f64.shape[0])
        max_itd = int(round(0.00025 * virtualize_width * float(sample_rate)))
        crossfeed_delay = int(round(0.00035 * float(sample_rate)))
        max_delay = max(0, max_itd + crossfeed_delay)

        left = np.zeros(frame_count + max_delay, dtype=np.float64)
        right = np.zeros(frame_count + max_delay, dtype=np.float64)

        processed_channels = 0
        gated_channels = 0
        hrtf_shaped_channels = 0

        for slot in range(channel_count):
            channel = buf_f32_or_f64[slot].astype(np.float64, copy=False)
            channel_rms_dbfs = _dbfs_rms(channel)
            if channel_rms_dbfs < gate_rms_dbfs:
                gated_channels += 1
                continue

            position = _speaker_for_slot(layout_ctx, slot)
            (
                left_gain,
                right_gain,
                left_delay,
                right_delay,
                crossfeed_gain,
                crossfeed_delay_samples,
                pan,
            ) = _speaker_binaural_parameters(
                position=position,
                sample_rate_hz=sample_rate,
                width=virtualize_width,
                lfe_trim_db=lfe_trim_db,
            )

            near_channel, far_channel = _conservative_hrtf_pair(
                channel=channel,
                sample_rate_hz=sample_rate,
                position=position,
                width=virtualize_width,
                hrtf_amount=hrtf_amount,
            )
            if position != SpeakerPosition.LFE and abs(pan) > 1e-3 and hrtf_amount > 0.0:
                hrtf_shaped_channels += 1

            if pan < 0.0:
                left_source = near_channel
                right_source = far_channel
            elif pan > 0.0:
                left_source = far_channel
                right_source = near_channel
            else:
                left_source = near_channel
                right_source = near_channel

            _add_shifted(left, left_source, gain=left_gain, delay_samples=left_delay)
            _add_shifted(right, right_source, gain=right_gain, delay_samples=right_delay)

            if crossfeed_gain > 0.0 and position != SpeakerPosition.LFE:
                _add_shifted(
                    left,
                    right_source,
                    gain=left_gain * crossfeed_gain,
                    delay_samples=right_delay + crossfeed_delay_samples,
                )
                _add_shifted(
                    right,
                    left_source,
                    gain=right_gain * crossfeed_gain,
                    delay_samples=left_delay + crossfeed_delay_samples,
                )

            processed_channels += 1

        wet = np.vstack([left[:frame_count], right[:frame_count]])

        # Preserve conservative headroom for headphone audition.
        wet_peak = float(abs(wet).max()) if wet.size else 0.0
        target_peak = _db_to_gain(-output_headroom_db)
        if wet_peak > target_peak and wet_peak > _EPSILON:
            wet *= target_peak / wet_peak

        if macro_mix <= 0.0:
            rendered = dry
            stage_why = "macro_mix=0 preserved dry stereo fold output."
        elif macro_mix >= 1.0:
            rendered = wet
            stage_why = (
                "Conservative binaural virtualization applied "
                f"to {processed_channels} channel(s), gated {gated_channels}."
            )
        else:
            rendered = np.clip((dry * (1.0 - macro_mix)) + (wet * macro_mix), -1.0, 1.0)
            stage_why = (
                "Conservative binaural virtualization blended with dry fold at "
                f"macro_mix={macro_mix:.2f} ({processed_channels} processed, "
                f"{gated_channels} gated)."
            )

        rendered = np.clip(rendered, -1.0, 1.0)
        peak_dbfs = _peak_dbfs(rendered)

        ctx.evidence_collector.set(
            stage_what="plugin stage applied",
            stage_why=stage_why,
            metrics=[
                {"name": "stage_index", "value": ctx.stage_index},
                {"name": "gate_rms_dbfs", "value": gate_rms_dbfs},
                {"name": "virtualize_width", "value": virtualize_width},
                {"name": "hrtf_amount", "value": hrtf_amount},
                {"name": "lfe_trim_db", "value": lfe_trim_db},
                {"name": "output_headroom_db", "value": output_headroom_db},
                {"name": "processed_channels", "value": float(processed_channels)},
                {"name": "gated_channels", "value": float(gated_channels)},
                {"name": "hrtf_shaped_channels", "value": float(hrtf_shaped_channels)},
                {"name": "output_peak_dbfs", "value": peak_dbfs},
                {"name": "macro_mix", "value": macro_mix},
                {"name": "macro_mix_input", "value": macro_mix_input},
                {"name": "bypass", "value": 0.0},
            ],
            notes=[
                f"layout_standard={layout_ctx.layout.standard.value}",
                "Designed for headphone preview only; keep release masters unvirtualized.",
                "Gate reference: GATE.DOWNMIX_SIMILARITY_MEASURED verified post-render.",
            ],
        )
        return rendered.astype(buf_f32_or_f64.dtype.type, copy=False)


def render_headphone_preview_wav(
    *,
    source_path: Path,
    output_path: Path,
    layout_standard: str,
    layout_id_hint: str | None = None,
    gate_rms_dbfs: float = -58.0,
    virtualize_width: float = 0.85,
    hrtf_amount: float = 0.55,
    lfe_trim_db: float = -12.0,
    output_headroom_db: float = 1.0,
) -> dict[str, Any]:
    """Render a deterministic stereo headphone preview WAV from a WAV source."""
    import numpy as np

    metadata = read_wav_metadata(source_path)
    audio_format = int(metadata.get("audio_format_resolved") or 0)
    bits_per_sample = int(metadata.get("bits_per_sample") or 0)
    channel_count = int(metadata.get("channels") or 0)
    sample_rate_hz = int(metadata.get("sample_rate_hz") or 0)

    if audio_format not in (1, 3):
        raise ValueError(
            f"Unsupported WAV audio format for headphone preview: {audio_format}"
        )
    if channel_count <= 0 or sample_rate_hz <= 0:
        raise ValueError("Invalid WAV metadata for headphone preview.")

    layout = _resolve_preview_layout(
        channel_count=channel_count,
        layout_standard=layout_standard,
        layout_id_hint=layout_id_hint,
    )

    chunks: list[float] = []
    for chunk in iter_wav_float64_samples(
        source_path,
        error_context="headphone preview",
    ):
        chunks.extend(chunk)

    samples = np.asarray(chunks, dtype=np.float64)
    if samples.size % channel_count != 0:
        raise ValueError("WAV sample stream is not frame-aligned.")
    multichannel = samples.reshape(-1, channel_count).T

    plugin = BinauralPreviewV0Plugin()
    evidence = PluginContext(
        precision_mode="float64",
        max_theoretical_quality=False,
        evidence_collector=PluginEvidenceCollector(),
        stage_index=1,
    )
    layout_ctx = LayoutContext(layout=layout)

    rendered = plugin.process_multichannel(
        multichannel,
        sample_rate_hz,
        {
            "gate_rms_dbfs": gate_rms_dbfs,
            "virtualize_width": virtualize_width,
            "hrtf_amount": hrtf_amount,
            "lfe_trim_db": lfe_trim_db,
            "output_headroom_db": output_headroom_db,
            "macro_mix": 1.0,
            "bypass": False,
        },
        evidence,
        layout_ctx,
    )

    output_bit_depth = _bit_depth_for_output(bits_per_sample)
    _write_stereo_wav(
        float_stereo=rendered,
        output_path=output_path,
        sample_rate_hz=sample_rate_hz,
        bit_depth=output_bit_depth,
    )

    return {
        "layout_id": layout.layout_id,
        "layout_standard": layout.standard.value,
        "sample_rate_hz": sample_rate_hz,
        "bit_depth": output_bit_depth,
        "channel_count": 2,
        "frame_count": int(rendered.shape[1]),
        "peak_dbfs": _peak_dbfs(rendered.astype(np.float64, copy=False)),
        "sha256": sha256_file(output_path),
        "stage_what": evidence.evidence_collector.stage_what,
        "stage_why": evidence.evidence_collector.stage_why,
        "stage_metrics": list(evidence.evidence_collector.metrics),
        "stage_notes": list(evidence.evidence_collector.notes or []),
    }


def build_headphone_preview_manifest(
    *,
    renderer_manifests: list[dict[str, Any]],
    output_dir: Path | None,
    layout_standard: str,
) -> dict[str, Any]:
    """Build a renderer-manifest block for headphone preview outputs."""
    outputs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for manifest in renderer_manifests:
        if not isinstance(manifest, dict):
            continue
        for output in manifest.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            source_format = str(output.get("format") or "").strip().lower()
            recommendation_id = str(output.get("recommendation_id") or PREVIEW_REC_ID).strip() or PREVIEW_REC_ID
            action_id = str(output.get("action_id") or PREVIEW_ACTION_ID).strip() or PREVIEW_ACTION_ID

            if source_format != "wav":
                skipped.append(
                    {
                        "recommendation_id": recommendation_id,
                        "action_id": action_id,
                        "reason": "preview_source_format_unsupported",
                        "gate_summary": "",
                    }
                )
                continue

            source_file_path = str(output.get("file_path") or "").strip()
            if not source_file_path:
                skipped.append(
                    {
                        "recommendation_id": recommendation_id,
                        "action_id": action_id,
                        "reason": "preview_source_missing_path",
                        "gate_summary": "",
                    }
                )
                continue

            source_path, preview_file_path, preview_path = _source_path_and_preview_file_path(
                source_file_path=source_file_path,
                output_dir=output_dir,
            )
            if source_path is None or preview_path is None or preview_file_path is None:
                skipped.append(
                    {
                        "recommendation_id": recommendation_id,
                        "action_id": action_id,
                        "reason": "preview_output_root_missing",
                        "gate_summary": "",
                    }
                )
                continue
            if not source_path.exists() or not source_path.is_file():
                skipped.append(
                    {
                        "recommendation_id": recommendation_id,
                        "action_id": action_id,
                        "reason": "preview_source_missing_file",
                        "gate_summary": "",
                    }
                )
                continue

            layout_id_hint = str(output.get("layout_id") or "").strip() or None
            metadata = output.get("metadata")
            if layout_id_hint is None and isinstance(metadata, Mapping):
                layout_id_hint = (
                    str(metadata.get("target_layout_id") or "").strip()
                    or str(metadata.get("source_layout_id") or "").strip()
                    or None
                )

            try:
                render_info = render_headphone_preview_wav(
                    source_path=source_path,
                    output_path=preview_path,
                    layout_standard=layout_standard,
                    layout_id_hint=layout_id_hint,
                )
            except ValueError:
                skipped.append(
                    {
                        "recommendation_id": recommendation_id,
                        "action_id": action_id,
                        "reason": "preview_render_failed",
                        "gate_summary": "",
                    }
                )
                continue

            preview_output: dict[str, Any] = {
                "output_id": _preview_output_id(output, render_info["sha256"]),
                "file_path": preview_file_path,
                "action_id": action_id,
                "recommendation_id": recommendation_id,
                "layout_id": "LAYOUT.2_0",
                "format": "wav",
                "codec": "pcm",
                "sample_rate_hz": int(render_info["sample_rate_hz"]),
                "bit_depth": int(render_info["bit_depth"]),
                "channel_count": 2,
                "sha256": render_info["sha256"],
                "notes": "Headphone preview (conservative binaural virtualization).",
                "metadata": {
                    "preview_of_output_id": str(output.get("output_id") or ""),
                    "preview_source_path": source_path.resolve().as_posix(),
                    "preview_requested_layout_standard": _normalize_standard(layout_standard),
                    "preview_layout_id_used": str(render_info["layout_id"]),
                    "preview_layout_standard_used": str(render_info["layout_standard"]),
                    "preview_stage_what": str(render_info["stage_what"]),
                    "preview_stage_why": str(render_info["stage_why"]),
                    "preview_stage_metrics": list(render_info.get("stage_metrics") or []),
                },
            }

            target_stem_id = str(output.get("target_stem_id") or "").strip()
            if target_stem_id:
                preview_output["target_stem_id"] = target_stem_id
            target_bus_id = str(output.get("target_bus_id") or "").strip()
            if target_bus_id:
                preview_output["target_bus_id"] = target_bus_id

            outputs.append(preview_output)

    outputs.sort(
        key=lambda row: (
            str(row.get("target_stem_id") or ""),
            str(row.get("file_path") or ""),
            str(row.get("output_id") or ""),
        )
    )
    skipped.sort(
        key=lambda row: (
            str(row.get("recommendation_id") or ""),
            str(row.get("action_id") or ""),
            str(row.get("reason") or ""),
        )
    )

    return {
        "renderer_id": PREVIEW_RENDERER_ID,
        "outputs": outputs,
        "skipped": skipped,
        "notes": (
            "Conservative headphone preview renderer. "
            "Deterministic binaural virtualization with RMS gating."
        ),
    }
