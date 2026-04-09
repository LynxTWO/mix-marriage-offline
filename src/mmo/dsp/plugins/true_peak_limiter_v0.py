"""True-peak ceiling reducer v0.

Applies the minimum uniform gain reduction required to bring the true-peak of
a signal below a hard ceiling.  This is a static (not dynamic) gain stage —
identical input always produces identical output.

Design notes:
- True-peak is computed via 4x oversampled polyphase detection (same path as
  the scan pipeline and preflight gate).
- If the signal is already below the ceiling, samples are returned unchanged.
- Output gain is the single smallest value that passes the ceiling: no
  per-sample gain-riding, no release time, no nonlinearity.
- Intended as a safety-net final stage, not a creative dynamics tool.
"""
from __future__ import annotations

import math
from typing import Any


def apply_true_peak_ceiling(
    samples: "Any",  # np.ndarray[float64, shape=(frames, channels)]
    sample_rate_hz: int,
    *,
    ceiling_dbtp: float = -1.0,
) -> "tuple[Any, dict[str, float]]":
    """Apply a static gain reduction to enforce a true-peak ceiling.

    Parameters
    ----------
    samples:
        Float64 array of shape ``(frames, channels)``.  Values must be in
        [-1.0, 1.0] range (normalised).
    sample_rate_hz:
        Sample rate of ``samples``.
    ceiling_dbtp:
        Maximum allowed true-peak level in dBTP.  Default -1.0 dBTP.

    Returns
    -------
    (processed_samples, receipt):
        ``processed_samples`` has the same dtype and shape as ``samples``.
        ``receipt`` is a dict with keys:
            ``gain_applied_db``: gain applied in dB (0.0 if no reduction needed)
            ``peak_input_dbtp``:  measured true-peak of input
            ``peak_output_dbtp``: measured true-peak of output (≤ ceiling)
            ``ceiling_dbtp``:     the ceiling value used
    """
    # Lazy import: numpy not available at entrypoint validation time
    import numpy as np  # noqa: PLC0415
    from mmo.dsp.meters_truth import compute_true_peak_dbtp_float64  # noqa: PLC0415

    if samples.size == 0:
        return samples.copy(), {
            "gain_applied_db": 0.0,
            "peak_input_dbtp": float("-inf"),
            "peak_output_dbtp": float("-inf"),
            "ceiling_dbtp": ceiling_dbtp,
        }

    peak_input_dbtp = compute_true_peak_dbtp_float64(samples, sample_rate_hz)

    if not math.isfinite(peak_input_dbtp) or peak_input_dbtp <= ceiling_dbtp:
        return samples.copy(), {
            "gain_applied_db": 0.0,
            "peak_input_dbtp": round(peak_input_dbtp, 3) if math.isfinite(peak_input_dbtp) else peak_input_dbtp,
            "peak_output_dbtp": round(peak_input_dbtp, 3) if math.isfinite(peak_input_dbtp) else peak_input_dbtp,
            "ceiling_dbtp": ceiling_dbtp,
        }

    # Compute the exact gain ratio that maps peak to ceiling
    peak_linear = 10.0 ** (peak_input_dbtp / 20.0)
    ceiling_linear = 10.0 ** (ceiling_dbtp / 20.0)
    gain = ceiling_linear / peak_linear
    gain_db = 20.0 * math.log10(gain)  # always negative

    processed = (samples * gain).astype(np.float64)

    # Measure output peak to verify (reuse same measurement path)
    peak_output_dbtp = compute_true_peak_dbtp_float64(processed, sample_rate_hz)

    return processed, {
        "gain_applied_db": round(gain_db, 4),
        "peak_input_dbtp": round(peak_input_dbtp, 3),
        "peak_output_dbtp": round(peak_output_dbtp, 3) if math.isfinite(peak_output_dbtp) else peak_output_dbtp,
        "ceiling_dbtp": ceiling_dbtp,
    }
