"""Compressor renderer: applies ACTION.DYN.COMPRESSOR recommendations to stems.

Uses the existing simple_compressor_v0 DSP plugin (feed-forward, no lookahead)
via the AudioBufferF64 interface.  Output is always 24-bit PCM WAV.

Safety constraints:
  - Only risk="low" or risk="medium" with requires_approval=False are processed.
  - Ratio is capped at _MAX_RATIO (4:1) to prevent brickwall destruction.
  - Makeup gain is capped at _MAX_MAKEUP_DB (+6 dB) to prevent clip risk.
  - After processing, peak is checked; if it would clip the output is rejected
    and flagged as skipped with reason "clip_risk".
"""
from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from mmo.dsp.io import read_wav_metadata
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin

_PLUGIN_ID = "PLUGIN.RENDERER.COMPRESSOR"
_ALLOWED_ACTIONS = {"ACTION.DYN.COMPRESSOR"}
_WAV_EXTENSIONS = {".wav", ".wave"}
_OUTPUT_BIT_DEPTH = 24

# Safety gates
_MAX_RATIO = 4.0
_MIN_RATIO = 1.01
_MAX_THRESHOLD_DB = -3.0   # don't compress everything
_MIN_THRESHOLD_DB = -40.0
_MAX_MAKEUP_DB = 6.0
_MIN_MAKEUP_DB = -12.0
_MAX_ATTACK_MS = 300.0
_MIN_ATTACK_MS = 0.1
_MAX_RELEASE_MS = 2000.0
_MIN_RELEASE_MS = 10.0
_CLIP_CEILING = 0.9999     # reject output if any sample exceeds this
_CHUNK_FRAMES = 4096


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _get_param(params: List[Dict[str, Any]], param_id: str) -> Optional[float]:
    for p in params:
        if isinstance(p, dict) and p.get("param_id") == param_id:
            return _coerce_float(p.get("value"))
    return None


def _stem_id_from_rec(rec: Dict[str, Any]) -> Optional[str]:
    scope = rec.get("scope")
    if not isinstance(scope, dict):
        return None
    stem_id = scope.get("stem_id")
    return stem_id if isinstance(stem_id, str) and stem_id else None


def _resolve_stem_path(stems_by_id: Dict[str, Dict[str, Any]], stem_id: str) -> Optional[Path]:
    stem = stems_by_id.get(stem_id)
    if stem is None:
        return None
    from mmo.core.source_locator import resolved_stem_path  # noqa: PLC0415
    path = resolved_stem_path(stem)
    if path is not None:
        return path
    raw = stem.get("file_path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw.strip())
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    return None


def _index_stems(session: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for stem in session.get("stems", []):
        if not isinstance(stem, dict):
            continue
        stem_id = _coerce_str(stem.get("stem_id"))
        if stem_id and stem_id not in indexed:
            indexed[stem_id] = stem
    return indexed


def _parse_comp_params(rec: Dict[str, Any], sample_rate_hz: int) -> Optional[Dict[str, float]]:
    """Validate and clamp compressor params from a recommendation."""
    if rec.get("action_id") not in _ALLOWED_ACTIONS:
        return None
    risk = _coerce_str(rec.get("risk"))
    if risk not in {"low", "medium"}:
        return None
    if rec.get("requires_approval") is not False:
        return None

    params = rec.get("params")
    if not isinstance(params, list):
        return None

    threshold_db = _get_param(params, "PARAM.COMP.THRESHOLD_DB")
    ratio = _get_param(params, "PARAM.COMP.RATIO")
    attack_ms = _get_param(params, "PARAM.COMP.ATTACK_MS")
    release_ms = _get_param(params, "PARAM.COMP.RELEASE_MS")

    if any(v is None for v in (threshold_db, ratio, attack_ms, release_ms)):
        return None

    # These bounds protect stems from destructive settings. They are safety
    # limits, not a promise to honor every incoming recommendation literally.
    threshold_db = max(_MIN_THRESHOLD_DB, min(_MAX_THRESHOLD_DB, threshold_db))  # type: ignore[arg-type]
    ratio = max(_MIN_RATIO, min(_MAX_RATIO, ratio))  # type: ignore[arg-type]
    attack_ms = max(_MIN_ATTACK_MS, min(_MAX_ATTACK_MS, attack_ms))  # type: ignore[arg-type]
    release_ms = max(_MIN_RELEASE_MS, min(_MAX_RELEASE_MS, release_ms))  # type: ignore[arg-type]

    makeup_db_raw = _get_param(params, "PARAM.COMP.MAKEUP_DB")
    makeup_db = max(_MIN_MAKEUP_DB, min(_MAX_MAKEUP_DB, makeup_db_raw if makeup_db_raw is not None else 0.0))

    return {
        "threshold_db": threshold_db,
        "ratio": ratio,
        "attack_ms": attack_ms,
        "release_ms": release_ms,
        "makeup_db": makeup_db,
    }


def _apply_compression(
    samples: List[float],
    channels: int,
    sample_rate_hz: int,
    threshold_db: float,
    ratio: float,
    attack_ms: float,
    release_ms: float,
    makeup_db: float,
) -> List[float]:
    """Apply feed-forward RMS compressor sample-by-sample. Returns interleaved floats."""
    attack_coeff = math.exp(-1.0 / max(attack_ms / 1000.0 * sample_rate_hz, 1.0))
    release_coeff = math.exp(-1.0 / max(release_ms / 1000.0 * sample_rate_hz, 1.0))
    makeup = math.pow(10.0, makeup_db / 20.0)

    n_frames = len(samples) // channels
    output = [0.0] * (n_frames * channels)
    envelope_db = -120.0

    for fi in range(n_frames):
        src_off = fi * channels
        # RMS across channels for this frame
        frame_sq = sum(samples[src_off + c] ** 2 for c in range(channels)) / channels
        rms = math.sqrt(max(frame_sq, 1e-30))
        det_db = 20.0 * math.log10(rms)

        coeff = attack_coeff if det_db > envelope_db else release_coeff
        envelope_db = coeff * envelope_db + (1.0 - coeff) * det_db

        over_db = envelope_db - threshold_db
        gr_db = max(0.0, over_db * (1.0 - 1.0 / ratio))
        gain = makeup * math.pow(10.0, -gr_db / 20.0)

        for c in range(channels):
            output[fi * channels + c] = max(-1.0, min(1.0, samples[src_off + c] * gain))

    return output


def _float_to_pcm24(value: float) -> bytes:
    clamped = max(-1.0, min(1.0, value))
    sample_int = max(-8388608, min(8388607, int(round(clamped * 8388607.0))))
    return sample_int.to_bytes(3, byteorder="little", signed=True)


def _render_compressed(
    source_path: Path,
    output_path: Path,
    channels: int,
    sample_rate_hz: int,
    comp_params: Dict[str, float],
) -> str:
    """Apply compression and write 24-bit WAV. Returns "" on success or error reason."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pending: list[float] = []
    peak = 0.0
    all_output: list[float] = []

    try:
        # Buffer the full output in memory so clip-risk can reject the stem
        # before any partially-written hot file reaches disk.
        for chunk in iter_wav_float64_samples(source_path, error_context="compressor render"):
            pending.extend(chunk)
            needed = _CHUNK_FRAMES * channels
            while len(pending) >= needed:
                block = pending[:needed]
                pending = pending[needed:]
                processed = _apply_compression(
                    block, channels, sample_rate_hz, **comp_params
                )
                all_output.extend(processed)
                peak = max(peak, max(abs(s) for s in processed))

        if pending:
            aligned = (len(pending) // channels) * channels
            if aligned > 0:
                processed = _apply_compression(
                    pending[:aligned], channels, sample_rate_hz, **comp_params
                )
                all_output.extend(processed)
                peak = max(peak, max(abs(s) for s in processed))
    except Exception as exc:
        return f"render_error: {exc}"

    if peak > _CLIP_CEILING:
        return "clip_risk"

    try:
        with wave.open(str(output_path), "wb") as out_handle:
            out_handle.setnchannels(channels)
            out_handle.setsampwidth(3)
            out_handle.setframerate(sample_rate_hz)
            raw = bytearray()
            for sample in all_output:
                raw.extend(_float_to_pcm24(sample))
            out_handle.writeframes(bytes(raw))
    except Exception as exc:
        return f"write_error: {exc}"

    return ""


def _output_path(source_path: Path, out_dir: Path) -> Path:
    return out_dir / source_path.with_name(f"{source_path.stem}.mmo_comp.wav").name


class CompressorRenderer(RendererPlugin):
    plugin_id = _PLUGIN_ID

    def render(
        self,
        session: Dict[str, Any],
        recommendations: List[Recommendation],
        output_dir: Any = None,
    ) -> RenderManifest:
        manifest: RenderManifest = {
            "renderer_id": self.plugin_id,
            "outputs": [],
            "skipped": [],
        }

        if output_dir is None:
            manifest["skipped"] = [
                {"recommendation_id": _coerce_str(rec.get("recommendation_id")),
                 "action_id": _coerce_str(rec.get("action_id")),
                 "reason": "missing_output_dir", "gate_summary": ""}
                for rec in recommendations if isinstance(rec, dict)
                and _coerce_str(rec.get("action_id")) in _ALLOWED_ACTIONS
            ]
            return manifest

        out_dir = Path(output_dir)
        stems_by_id = _index_stems(session)

        applicable = [
            rec for rec in recommendations
            if isinstance(rec, dict)
            and _coerce_str(rec.get("action_id")) in _ALLOWED_ACTIONS
            and _stem_id_from_rec(rec) is not None
        ]

        # One stem yields one output file. Stable grouping keeps repeated runs
        # from changing which recommendation becomes the representative row.
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for rec in applicable:
            stem_id = _stem_id_from_rec(rec)
            if stem_id:
                grouped.setdefault(stem_id, []).append(rec)

        outputs: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        for stem_id in sorted(grouped.keys()):
            recs = grouped[stem_id]
            # This corrective path is intentionally WAV-only. The safer
            # multiformat renderers already own FFmpeg-backed rewrite rules.
            source_path = _resolve_stem_path(stems_by_id, stem_id)
            if source_path is None or source_path.suffix.lower() not in _WAV_EXTENSIONS:
                for rec in recs:
                    skipped.append({"recommendation_id": _coerce_str(rec.get("recommendation_id")),
                                    "action_id": _coerce_str(rec.get("action_id")),
                                    "reason": "missing_stem_file_path", "gate_summary": ""})
                continue

            try:
                meta = read_wav_metadata(source_path)
            except Exception:
                for rec in recs:
                    skipped.append({"recommendation_id": _coerce_str(rec.get("recommendation_id")),
                                    "action_id": _coerce_str(rec.get("action_id")),
                                    "reason": "unsupported_format", "gate_summary": ""})
                continue

            channels = _coerce_int(meta.get("channels"))
            sample_rate_hz = _coerce_int(meta.get("sample_rate_hz"))
            if not channels or not sample_rate_hz:
                for rec in recs:
                    skipped.append({"recommendation_id": _coerce_str(rec.get("recommendation_id")),
                                    "action_id": _coerce_str(rec.get("action_id")),
                                    "reason": "unsupported_format", "gate_summary": ""})
                continue

            # Use the first valid recommendation in deterministic order so the
            # same stem does not flip between conflicting compressor settings.
            comp_params: Optional[Dict[str, float]] = None
            representative: Optional[Dict[str, Any]] = None
            for rec in sorted(recs, key=lambda r: _coerce_str(r.get("recommendation_id"))):
                comp_params = _parse_comp_params(rec, sample_rate_hz)
                if comp_params is not None:
                    representative = rec
                    break

            if comp_params is None or representative is None:
                for rec in recs:
                    skipped.append({"recommendation_id": _coerce_str(rec.get("recommendation_id")),
                                    "action_id": _coerce_str(rec.get("action_id")),
                                    "reason": "invalid_params", "gate_summary": ""})
                continue

            output_path = _output_path(source_path, out_dir)
            error_reason = _render_compressed(source_path, output_path, channels, sample_rate_hz, comp_params)
            if error_reason:
                for rec in recs:
                    skipped.append({"recommendation_id": _coerce_str(rec.get("recommendation_id")),
                                    "action_id": _coerce_str(rec.get("action_id")),
                                    "reason": error_reason, "gate_summary": ""})
                continue

            rec_ids = sorted(_coerce_str(r.get("recommendation_id")) for r in recs)
            outputs.append({
                "output_id": f"OUTPUT.COMP.{stem_id}.{output_path.name}",
                "file_path": output_path.as_posix(),
                "action_id": _coerce_str(representative.get("action_id")),
                "recommendation_id": _coerce_str(representative.get("recommendation_id")),
                "target_stem_id": stem_id,
                "format": "wav",
                "sample_rate_hz": sample_rate_hz,
                "bit_depth": _OUTPUT_BIT_DEPTH,
                "channel_count": channels,
                "notes": (
                    f"threshold={comp_params['threshold_db']:.1f}dB "
                    f"ratio={comp_params['ratio']:.1f}:1 "
                    f"attack={comp_params['attack_ms']:.0f}ms "
                    f"release={comp_params['release_ms']:.0f}ms "
                    f"makeup={comp_params['makeup_db']:+.1f}dB"
                ),
            })

        outputs.sort(key=lambda o: (o.get("target_stem_id", ""), o.get("output_id", "")))
        skipped.sort(key=lambda s: (s.get("recommendation_id", ""), s.get("reason", "")))
        manifest["outputs"] = outputs
        manifest["skipped"] = skipped
        return manifest
