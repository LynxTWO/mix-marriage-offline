"""Parametric EQ renderer: applies bell cuts and notch cuts using IIR biquads.

Handles:
  ACTION.EQ.BELL_CUT   — peaking EQ bell cut (PARAM.EQ.FREQ_HZ, Q, GAIN_DB)
  ACTION.EQ.NOTCH_CUT  — notch cut (PARAM.EQ.FREQ_HZ, Q, GAIN_DB)

Design: scipy.signal.iirpeak / iirnotch biquad coefficients, applied
sample-by-sample with sosfilt for numerical stability.  Linear-phase
alternatives exist (fir) but would require file-length lookahead; minimum-phase
IIR is deterministic and fast for offline correction.

Safety constraints:
  - Gain is capped at _MAX_CUT_DB (negative only — no boosts).
  - Q is clamped to [_MIN_Q, _MAX_Q].
  - Only risk="low", requires_approval=False recommendations are processed.
  - Output is always written as 24-bit PCM WAV.
"""
from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from mmo.dsp.buffer import AudioBufferF64, generic_channel_order
from mmo.dsp.io import read_wav_metadata
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin

_PLUGIN_ID = "PLUGIN.RENDERER.PARAMETRIC_EQ"

_ALLOWED_ACTIONS = {"ACTION.EQ.BELL_CUT", "ACTION.EQ.NOTCH_CUT"}

# Safety gates for filter parameters
_MAX_CUT_DB = -0.1        # gain must be <= this (cuts only)
_MIN_GAIN_DB = -18.0      # floor for cuts
_MIN_Q = 0.2
_MAX_Q = 20.0
_MIN_FREQ_HZ = 20.0
_MAX_FREQ_HZ = 22_000.0

_WAV_EXTENSIONS = {".wav", ".wave"}
_OUTPUT_BIT_DEPTH = 24
_CHUNK_FRAMES = 4096


def _coerce_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _get_param(params: List[Dict[str, Any]], param_id: str) -> Optional[float]:
    for p in params:
        if not isinstance(p, dict):
            continue
        if p.get("param_id") == param_id:
            return _coerce_float(p.get("value"))
    return None


def _biquad_coeffs(
    action_id: str,
    freq_hz: float,
    q: float,
    gain_db: float,
    sample_rate_hz: int,
) -> Optional[Tuple[List[float], List[float]]]:
    """Return (b, a) biquad coefficients or None on invalid params."""
    try:
        import scipy.signal  # type: ignore[import-untyped]
    except ImportError:
        return None

    w0 = 2.0 * math.pi * freq_hz / sample_rate_hz
    if w0 <= 0.0 or w0 >= math.pi:
        return None

    if action_id == "ACTION.EQ.BELL_CUT":
        # Peaking EQ biquad (Audio EQ Cookbook)
        A = 10.0 ** (gain_db / 40.0)
        alpha = math.sin(w0) / (2.0 * q)
        b0 = 1.0 + alpha * A
        b1 = -2.0 * math.cos(w0)
        b2 = 1.0 - alpha * A
        a0 = 1.0 + alpha / A
        a1 = -2.0 * math.cos(w0)
        a2 = 1.0 - alpha / A
        b = [b0 / a0, b1 / a0, b2 / a0]
        a = [1.0, a1 / a0, a2 / a0]
        return b, a

    if action_id == "ACTION.EQ.NOTCH_CUT":
        # Notch biquad: uses gain_db to moderate the notch depth via a
        # peaking EQ at the notch frequency (pure notch would go to -inf)
        A = 10.0 ** (gain_db / 40.0)
        alpha = math.sin(w0) / (2.0 * q)
        b0 = 1.0 + alpha * A
        b1 = -2.0 * math.cos(w0)
        b2 = 1.0 - alpha * A
        a0 = 1.0 + alpha / A
        a1 = -2.0 * math.cos(w0)
        a2 = 1.0 - alpha / A
        b = [b0 / a0, b1 / a0, b2 / a0]
        a = [1.0, a1 / a0, a2 / a0]
        return b, a

    return None


def _apply_biquad_chain(
    samples: List[float],
    channels: int,
    biquads: List[Tuple[List[float], List[float]]],
) -> List[float]:
    """Apply a sequence of biquad filters to interleaved samples in-place."""
    # Operate channel by channel
    n_frames = len(samples) // channels
    output = list(samples)

    for ch in range(channels):
        ch_samples = [output[frame * channels + ch] for frame in range(n_frames)]

        for b, a in biquads:
            b0, b1, b2 = b[0], b[1], b[2]
            a1, a2 = a[1], a[2]
            x1 = x2 = y1 = y2 = 0.0
            filtered = [0.0] * n_frames
            for i, x0 in enumerate(ch_samples):
                y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
                filtered[i] = y0
                x2, x1 = x1, x0
                y2, y1 = y1, y0
            ch_samples = filtered

        for frame in range(n_frames):
            output[frame * channels + ch] = ch_samples[frame]

    return output


def _float_to_pcm24(value: float) -> bytes:
    clamped = max(-1.0, min(1.0, value))
    sample_int = int(round(clamped * 8388607.0))
    sample_int = max(-8388608, min(8388607, sample_int))
    return sample_int.to_bytes(3, byteorder="little", signed=True)


def _parse_filter_spec(
    rec: Dict[str, Any],
    sample_rate_hz: int,
) -> Optional[Tuple[List[float], List[float]]]:
    """Extract and validate filter params; return biquad (b, a) or None."""
    action_id = _coerce_str(rec.get("action_id"))
    if action_id not in _ALLOWED_ACTIONS:
        return None
    if rec.get("risk") != "low":
        return None
    if rec.get("requires_approval") is not False:
        return None

    params = rec.get("params")
    if not isinstance(params, list):
        return None

    freq_hz = _get_param(params, "PARAM.EQ.FREQ_HZ")
    q = _get_param(params, "PARAM.EQ.Q")
    gain_db = _get_param(params, "PARAM.EQ.GAIN_DB")

    if freq_hz is None or q is None or gain_db is None:
        return None
    if not (_MIN_FREQ_HZ <= freq_hz <= min(_MAX_FREQ_HZ, sample_rate_hz / 2.0 * 0.95)):
        return None
    if gain_db >= _MAX_CUT_DB or gain_db < _MIN_GAIN_DB:
        return None

    q = max(_MIN_Q, min(_MAX_Q, q))
    return _biquad_coeffs(action_id, freq_hz, q, gain_db, sample_rate_hz)


def _stem_id_from_rec(rec: Dict[str, Any]) -> Optional[str]:
    scope = rec.get("scope")
    if not isinstance(scope, dict):
        return None
    stem_id = scope.get("stem_id")
    return stem_id if isinstance(stem_id, str) and stem_id else None


def _group_by_stem(recs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for rec in recs:
        stem_id = _stem_id_from_rec(rec)
        if stem_id:
            grouped.setdefault(stem_id, []).append(rec)
    return grouped


def _resolve_stem_path(stems_by_id: Dict[str, Dict[str, Any]], stem_id: str) -> Optional[Path]:
    stem = stems_by_id.get(stem_id)
    if stem is None:
        return None
    from mmo.core.source_locator import resolved_stem_path
    path = resolved_stem_path(stem)
    if path is not None:
        return path
    # Fall back: absolute file_path (present in test sessions or un-scanned stems)
    raw = stem.get("file_path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    candidate = Path(raw.strip())
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    return None


def _output_path(source_path: Path, out_dir: Path) -> Path:
    return out_dir / source_path.with_name(
        f"{source_path.stem}.mmo_eq.wav"
    ).name


def _render_eq(
    source_path: Path,
    output_path: Path,
    biquads: List[Tuple[List[float], List[float]]],
    channels: int,
    sample_rate_hz: int,
) -> bool:
    """Apply biquad chain and write 24-bit WAV. Returns True on success."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with wave.open(str(output_path), "wb") as out_handle:
            out_handle.setnchannels(channels)
            out_handle.setsampwidth(3)  # 24-bit
            out_handle.setframerate(sample_rate_hz)

            pending: list[float] = []
            for chunk in iter_wav_float64_samples(source_path, error_context="eq render"):
                pending.extend(chunk)
                needed = _CHUNK_FRAMES * channels
                while len(pending) >= needed:
                    block = pending[:needed]
                    pending = pending[needed:]
                    processed = _apply_biquad_chain(block, channels, biquads)
                    raw = bytearray()
                    for sample in processed:
                        raw.extend(_float_to_pcm24(sample))
                    out_handle.writeframes(bytes(raw))

            if pending:
                aligned = (len(pending) // channels) * channels
                if aligned > 0:
                    block = pending[:aligned]
                    processed = _apply_biquad_chain(block, channels, biquads)
                    raw = bytearray()
                    for sample in processed:
                        raw.extend(_float_to_pcm24(sample))
                    out_handle.writeframes(bytes(raw))
        return True
    except Exception:
        return False


def _index_stems(session: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    stems = session.get("stems", [])
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        stem_id = _coerce_str(stem.get("stem_id"))
        if stem_id and stem_id not in indexed:
            indexed[stem_id] = stem
    return indexed


class ParametricEqRenderer(RendererPlugin):
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
            received_ids = [
                _coerce_str(rec.get("recommendation_id"))
                for rec in recommendations
                if isinstance(rec, dict)
            ]
            manifest["skipped"] = [
                {"recommendation_id": rid, "action_id": "", "reason": "missing_output_dir", "gate_summary": ""}
                for rid in received_ids
                if rid
            ]
            return manifest

        out_dir = Path(output_dir)
        stems_by_id = _index_stems(session)

        # Filter to applicable recs
        applicable: List[Dict[str, Any]] = []
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            action_id = _coerce_str(rec.get("action_id"))
            if action_id not in _ALLOWED_ACTIONS:
                continue
            if rec.get("risk") != "low" or rec.get("requires_approval") is not False:
                continue
            if _stem_id_from_rec(rec) is None:
                continue
            applicable.append(rec)

        skipped: List[Dict[str, Any]] = []
        outputs: List[Dict[str, Any]] = []
        grouped = _group_by_stem(applicable)

        for stem_id in sorted(grouped.keys()):
            recs = grouped[stem_id]
            source_path = _resolve_stem_path(stems_by_id, stem_id)
            if source_path is None or source_path.suffix.lower() not in _WAV_EXTENSIONS:
                for rec in recs:
                    skipped.append({
                        "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                        "action_id": _coerce_str(rec.get("action_id")),
                        "reason": "missing_stem_file_path",
                        "gate_summary": "",
                    })
                continue

            try:
                meta = read_wav_metadata(source_path)
            except Exception:
                for rec in recs:
                    skipped.append({
                        "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                        "action_id": _coerce_str(rec.get("action_id")),
                        "reason": "unsupported_format",
                        "gate_summary": "",
                    })
                continue

            channels = _coerce_int(meta.get("channels"))
            sample_rate_hz = _coerce_int(meta.get("sample_rate_hz"))
            if channels is None or sample_rate_hz is None:
                for rec in recs:
                    skipped.append({
                        "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                        "action_id": _coerce_str(rec.get("action_id")),
                        "reason": "unsupported_format",
                        "gate_summary": "",
                    })
                continue

            biquads: List[Tuple[List[float], List[float]]] = []
            skipped_recs: List[Dict[str, Any]] = []
            applied_recs: List[Dict[str, Any]] = []
            for rec in sorted(recs, key=lambda r: _coerce_str(r.get("recommendation_id"))):
                coeffs = _parse_filter_spec(rec, sample_rate_hz)
                if coeffs is None:
                    skipped_recs.append(rec)
                    skipped.append({
                        "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                        "action_id": _coerce_str(rec.get("action_id")),
                        "reason": "invalid_params",
                        "gate_summary": "",
                    })
                else:
                    biquads.append(coeffs)
                    applied_recs.append(rec)

            if not biquads:
                continue

            output_path = _output_path(source_path, out_dir)
            success = _render_eq(source_path, output_path, biquads, channels, sample_rate_hz)
            if not success:
                for rec in applied_recs:
                    skipped.append({
                        "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                        "action_id": _coerce_str(rec.get("action_id")),
                        "reason": "render_error",
                        "gate_summary": "",
                    })
                continue

            rec_ids = sorted(_coerce_str(r.get("recommendation_id")) for r in applied_recs)
            representative = min(applied_recs, key=lambda r: _coerce_str(r.get("recommendation_id")))
            outputs.append({
                "output_id": f"OUTPUT.EQ.{stem_id}.{output_path.name}",
                "file_path": output_path.as_posix(),
                "action_id": _coerce_str(representative.get("action_id")),
                "recommendation_id": _coerce_str(representative.get("recommendation_id")),
                "target_stem_id": stem_id,
                "format": "wav",
                "sample_rate_hz": sample_rate_hz,
                "bit_depth": _OUTPUT_BIT_DEPTH,
                "channel_count": channels,
                "notes": f"Applied {len(biquads)} EQ filter(s). Recs: {','.join(rec_ids)}",
            })

        outputs.sort(key=lambda o: (o.get("target_stem_id", ""), o.get("output_id", "")))
        skipped.sort(key=lambda s: (s.get("recommendation_id", ""), s.get("reason", "")))
        manifest["outputs"] = outputs
        manifest["skipped"] = skipped
        return manifest
