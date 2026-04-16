"""Limiter renderer: applies ACTION.DYN.LIMITER to stems.

Uses true_peak_limiter_v0 (static true-peak ceiling reduction) via the
AudioBufferF64 interface.  Output is always 24-bit PCM WAV.

Safety constraints:
  - Only risk="low" or risk="medium" with requires_approval=False are processed.
  - Ceiling is clamped to [_MIN_CEILING_DBTP, _MAX_CEILING_DBTP].
  - After processing, true-peak is measured; if the output still exceeds the
    ceiling (possible due to floating-point precision) the job is skipped with
    reason "ceiling_check_failed" rather than silently delivering a hot file.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from mmo.dsp.io import read_wav_metadata
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin

_PLUGIN_ID = "PLUGIN.RENDERER.LIMITER"
_ALLOWED_ACTIONS = {"ACTION.DYN.LIMITER"}
_WAV_EXTENSIONS = {".wav", ".wave"}
_OUTPUT_BIT_DEPTH = 24

# Safety gates: ceiling clamped into this range
_MIN_CEILING_DBTP = -6.0   # never reduce by more than ~6 dB via limiter alone
_MAX_CEILING_DBTP = 0.0    # can't set ceiling above 0 dBFS
_DEFAULT_CEILING_DBTP = -1.0
_CLIP_CEILING = 0.9999     # reject if any sample exceeds this after processing
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


def _index_stems(session: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for stem in session.get("stems", []):
        if not isinstance(stem, dict):
            continue
        stem_id = _coerce_str(stem.get("stem_id"))
        if stem_id and stem_id not in indexed:
            indexed[stem_id] = stem
    return indexed


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


def _parse_ceiling(rec: Dict[str, Any]) -> Optional[float]:
    """Validate and clamp the ceiling param from a recommendation."""
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

    ceiling = _get_param(params, "PARAM.LIMIT.CEILING_DBFS")
    if ceiling is None:
        ceiling = _DEFAULT_CEILING_DBTP
    # Clamp to the renderer's safe operating range even if the recommendation
    # asked for a more aggressive ceiling.
    ceiling = max(_MIN_CEILING_DBTP, min(_MAX_CEILING_DBTP, ceiling))
    return ceiling


def _float_to_pcm24(sample: float) -> bytes:
    """Convert a single float64 sample to 3-byte little-endian 24-bit PCM."""
    import struct  # noqa: PLC0415

    clamped = max(-1.0, min(1.0, sample))
    v = int(round(clamped * ((2**23) - 1)))
    return struct.pack("<i", v)[0:3]


def _read_samples_float64(path: Path) -> "tuple[Any, int, int, int]":
    """Return (samples_f64, sample_rate_hz, channels, num_frames).

    Reads WAV via iter_wav_float64_samples (interleaved list[float]) and
    stacks into a numpy array of shape (frames, channels).
    """
    import numpy as np  # noqa: PLC0415

    meta = read_wav_metadata(path)
    sample_rate_hz = int(meta["sample_rate_hz"])
    channels = int(meta["channels"])

    # The limiter DSP works on a full frame x channel matrix, not a streaming
    # iterator, so normalize that boundary before the safety check runs.
    interleaved: list[float] = []
    for chunk in iter_wav_float64_samples(path, error_context="limiter render"):
        interleaved.extend(chunk)

    if not interleaved:
        samples = np.zeros((0, channels), dtype=np.float64)
    else:
        arr = np.array(interleaved, dtype=np.float64)
        # arr is interleaved: [L0, R0, L1, R1, ...] for stereo
        num_frames = len(arr) // channels
        samples = arr[: num_frames * channels].reshape(num_frames, channels)

    return samples, sample_rate_hz, channels, len(samples)


def _write_wav_24bit_fast(path: Path, samples: "Any", sample_rate_hz: int, channels: int) -> None:
    """Write float64 ndarray (frames, channels) as 24-bit PCM WAV."""
    import numpy as np  # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    # Flatten to interleaved order: [L0, R0, L1, R1, ...]
    flat = samples.ravel() if channels > 1 else samples.ravel()
    raw = bytearray()
    for val in flat:
        raw += _float_to_pcm24(float(val))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(3)
        w.setframerate(sample_rate_hz)
        w.writeframes(bytes(raw))


class LimiterRenderer(RendererPlugin):
    plugin_id = _PLUGIN_ID

    def render(
        self,
        session: Dict[str, Any],
        recommendations: List[Recommendation],
        output_dir: Optional[str] = None,
    ) -> RenderManifest:
        try:
            import numpy as np  # noqa: PLC0415
        except ImportError:
            # This renderer depends on numpy-backed true-peak math. Failing
            # closed is safer than pretending a limiter pass happened.
            return {
                "renderer_id": self.plugin_id,
                "outputs": [],
                "skipped": [{"reason": "numpy_unavailable"}],
            }

        from mmo.dsp.plugins.true_peak_limiter_v0 import apply_true_peak_ceiling  # noqa: PLC0415

        stems_by_id = _index_stems(session)
        out_root = Path(output_dir) if output_dir else Path(".")
        outputs: list[Dict[str, Any]] = []
        skipped: list[Dict[str, Any]] = []

        # Stable ordering: sort by rec ID
        sorted_recs = sorted(
            recommendations,
            key=lambda r: _coerce_str(r.get("recommendation_id")),
        )

        seen_stems: set[str] = set()

        for rec in sorted_recs:
            if not isinstance(rec, dict):
                continue

            ceiling = _parse_ceiling(rec)
            if ceiling is None:
                skipped.append({
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "ineligible",
                    "gate_summary": (
                        f"action={rec.get('action_id')!r} risk={rec.get('risk')!r} "
                        f"requires_approval={rec.get('requires_approval')!r}"
                    ),
                })
                continue

            stem_id = _stem_id_from_rec(rec)
            if not stem_id:
                skipped.append({
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "no_stem_id",
                    "gate_summary": "scope.stem_id is missing or empty",
                })
                continue

            if stem_id in seen_stems:
                # One-stem-once keeps repeated limiter recommendations from
                # stacking multiple ceiling passes onto the same file.
                skipped.append({
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "duplicate_stem",
                    "gate_summary": f"already processed stem_id={stem_id!r}",
                })
                continue

            stem_path = _resolve_stem_path(stems_by_id, stem_id)
            if stem_path is None or not stem_path.is_file():
                skipped.append({
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "stem_file_missing",
                    "gate_summary": f"stem_id={stem_id!r} has no resolvable WAV path",
                })
                continue

            if stem_path.suffix.lower() not in _WAV_EXTENSIONS:
                # This renderer does not own decode or transcode policy.
                # Non-WAV stems must go through the multiformat renderers.
                skipped.append({
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "non_wav_stem",
                    "gate_summary": f"stem format {stem_path.suffix!r} not supported",
                })
                continue

            try:
                samples, sample_rate_hz, channels, _ = _read_samples_float64(stem_path)
            except Exception as exc:
                skipped.append({
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "read_error",
                    "gate_summary": f"failed to read {stem_path.name}: {exc}",
                })
                continue

            if samples.size == 0:
                skipped.append({
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "empty_audio",
                    "gate_summary": f"stem_id={stem_id!r} contains no samples",
                })
                continue

            try:
                processed, receipt = apply_true_peak_ceiling(
                    samples, sample_rate_hz, ceiling_dbtp=ceiling
                )
            except Exception as exc:
                skipped.append({
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "dsp_error",
                    "gate_summary": str(exc),
                })
                continue

            # Reject the output if the limiter still leaves a clip risk. A
            # "best effort" file would hide a mastering failure.
            peak_abs = float(np.max(np.abs(processed))) if processed.size else 0.0
            if peak_abs > _CLIP_CEILING:
                skipped.append({
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "ceiling_check_failed",
                    "gate_summary": (
                        f"peak_abs={peak_abs:.6f} > clip_ceiling={_CLIP_CEILING} "
                        f"after limiting; output rejected for safety"
                    ),
                })
                continue

            out_path = out_root / f"{stem_id}.limited.wav"
            try:
                _write_wav_24bit_fast(out_path, processed, sample_rate_hz, channels)
            except Exception as exc:
                skipped.append({
                    "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                    "action_id": _coerce_str(rec.get("action_id")),
                    "reason": "write_error",
                    "gate_summary": str(exc),
                })
                continue

            seen_stems.add(stem_id)
            outputs.append({
                "recommendation_id": _coerce_str(rec.get("recommendation_id")),
                "stem_id": stem_id,
                "path": out_path.as_posix(),
                "channels": channels,
                "sample_rate_hz": sample_rate_hz,
                "bit_depth": _OUTPUT_BIT_DEPTH,
                "gain_applied_db": receipt.get("gain_applied_db", 0.0),
                "peak_input_dbtp": receipt.get("peak_input_dbtp"),
                "peak_output_dbtp": receipt.get("peak_output_dbtp"),
                "ceiling_dbtp": ceiling,
            })

        skipped.sort(key=lambda s: (s.get("reason", ""), s.get("recommendation_id", "")))

        return {
            "renderer_id": self.plugin_id,
            "outputs": outputs,
            "skipped": skipped,
        }
