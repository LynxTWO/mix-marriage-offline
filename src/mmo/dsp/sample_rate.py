from __future__ import annotations

from collections import Counter
from typing import Any, Iterator, Sequence


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        candidate = int(value)
        return candidate if candidate > 0 else None
    if isinstance(value, str) and value.strip():
        try:
            candidate = int(value.strip())
        except ValueError:
            return None
        return candidate if candidate > 0 else None
    return None


def choose_render_sample_rate_hz(
    sample_rates_hz: Sequence[Any],
    *,
    explicit_sample_rate_hz: Any = None,
) -> tuple[int | None, dict[str, Any]]:
    """Choose a deterministic render sample rate.

    Policy:
    - If ``explicit_sample_rate_hz`` is a positive integer, use it.
    - Otherwise choose the sample rate with the highest track count.
    - Ties are resolved by selecting the higher sample rate.
    """

    observed_rates: list[int] = []
    for value in sample_rates_hz:
        coerced = _coerce_positive_int(value)
        if coerced is not None:
            observed_rates.append(coerced)

    explicit = _coerce_positive_int(explicit_sample_rate_hz)
    counts = Counter(observed_rates)
    ordered_counts = sorted(counts.items(), key=lambda item: item[0])
    counts_payload = [
        {"sample_rate_hz": rate, "stem_count": count}
        for rate, count in ordered_counts
    ]

    if explicit is not None:
        return explicit, {
            "selection_policy": "explicit_override",
            "selection_reason": "explicit_sample_rate_hz",
            "selected_sample_rate_hz": explicit,
            "sample_rate_counts": counts_payload,
        }

    if not ordered_counts:
        return None, {
            "selection_policy": "majority_then_higher_tiebreak",
            "selection_reason": "no_decodable_stems",
            "selected_sample_rate_hz": None,
            "sample_rate_counts": [],
        }

    max_count = max(count for _, count in ordered_counts)
    tied_rates = [rate for rate, count in ordered_counts if count == max_count]
    selected_rate = max(tied_rates)
    selection_reason = "majority"
    if len(tied_rates) > 1:
        selection_reason = "tie_higher_sample_rate"

    return selected_rate, {
        "selection_policy": "majority_then_higher_tiebreak",
        "selection_reason": selection_reason,
        "selected_sample_rate_hz": selected_rate,
        "sample_rate_counts": counts_payload,
    }


def iter_resampled_float64_samples(
    float_samples_iter: Iterator[list[float]],
    *,
    channels: int,
    source_sample_rate_hz: int,
    target_sample_rate_hz: int,
    chunk_frames: int = 4096,
) -> Iterator[list[float]]:
    """Resample interleaved float64 samples using deterministic linear interpolation."""

    if channels <= 0:
        raise ValueError("channels must be positive")
    if source_sample_rate_hz <= 0:
        raise ValueError("source_sample_rate_hz must be positive")
    if target_sample_rate_hz <= 0:
        raise ValueError("target_sample_rate_hz must be positive")
    if chunk_frames <= 0:
        raise ValueError("chunk_frames must be positive")

    if source_sample_rate_hz == target_sample_rate_hz:
        for chunk in float_samples_iter:
            if len(chunk) % channels != 0:
                raise ValueError("decoder returned non-frame-aligned sample data")
            if chunk:
                yield [float(sample) for sample in chunk]
        return

    source_rate = int(source_sample_rate_hz)
    target_rate = int(target_sample_rate_hz)
    max_chunk_samples = chunk_frames * channels
    phase_numer = 0  # Next output position numerator in source-frame units.

    source_iter = iter(float_samples_iter)
    buffered_samples: list[float] = []
    buffer_start_frame = 0
    exhausted = False
    output_samples: list[float] = []

    while True:
        while True:
            buffered_frames = len(buffered_samples) // channels
            if buffered_frames <= 0:
                break

            required_frame = phase_numer // target_rate
            if required_frame < buffer_start_frame:
                # Guard rail for any numerical drift in future refactors.
                required_frame = buffer_start_frame
                phase_numer = required_frame * target_rate

            relative_required = required_frame - buffer_start_frame
            if relative_required >= buffered_frames:
                break

            relative_next = relative_required + 1
            if relative_next >= buffered_frames and not exhausted:
                break

            base_offset = int(relative_required) * channels
            if relative_next < buffered_frames:
                next_offset = int(relative_next) * channels
            else:
                # End-of-stream hold to make output length deterministic.
                next_offset = base_offset

            frac_num = phase_numer % target_rate
            frac = float(frac_num) / float(target_rate)
            one_minus_frac = 1.0 - frac

            for channel_index in range(channels):
                a = buffered_samples[base_offset + channel_index]
                b = buffered_samples[next_offset + channel_index]
                output_samples.append((a * one_minus_frac) + (b * frac))

            if len(output_samples) >= max_chunk_samples:
                yield output_samples
                output_samples = []

            phase_numer += source_rate

            next_required = phase_numer // target_rate
            min_keep_frame = max(0, int(next_required) - 1)
            drop_frames = min_keep_frame - buffer_start_frame
            if drop_frames > 0:
                max_drop = max(0, buffered_frames - 1)
                actual_drop = min(drop_frames, max_drop)
                if actual_drop > 0:
                    del buffered_samples[: actual_drop * channels]
                    buffer_start_frame += actual_drop

        if exhausted:
            break

        try:
            chunk = next(source_iter)
        except StopIteration:
            exhausted = True
            continue

        if not chunk:
            continue
        if len(chunk) % channels != 0:
            raise ValueError("decoder returned non-frame-aligned sample data")
        buffered_samples.extend(float(sample) for sample in chunk)

    if output_samples:
        yield output_samples
