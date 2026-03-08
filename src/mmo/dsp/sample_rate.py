from __future__ import annotations

from collections import Counter
from typing import Any, Iterator, Mapping, Sequence


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


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _sample_rate_family_hz(sample_rate_hz: int) -> int:
    if sample_rate_hz > 0 and sample_rate_hz % 44_100 == 0:
        return 44_100
    if sample_rate_hz > 0 and sample_rate_hz % 48_000 == 0:
        return 48_000
    return sample_rate_hz


def _normalize_decoder_warning_row(
    *,
    stem_id: str,
    value: Any,
) -> dict[str, Any] | None:
    if isinstance(value, str):
        warning = value.strip()
        if not warning:
            return None
        return {
            "stem_id": stem_id,
            "warning": warning,
        }
    if not isinstance(value, Mapping):
        return None

    warning = _coerce_str(value.get("warning")).strip()
    if not warning:
        return None

    normalized: dict[str, Any] = {
        "warning": warning,
    }
    warning_stem_id = _coerce_str(value.get("stem_id")).strip() or stem_id
    if warning_stem_id:
        normalized["stem_id"] = warning_stem_id

    format_id = _coerce_str(value.get("format")).strip().lower()
    if format_id:
        normalized["format"] = format_id

    detail = _coerce_str(value.get("detail")).strip()
    if detail:
        normalized["detail"] = detail

    return normalized


def choose_target_rate_for_session(
    stems_meta: Sequence[Any],
    *,
    explicit_rate: Any = None,
    default: Any = 48_000,
) -> tuple[int, dict[str, Any]]:
    """Choose a deterministic session target sample rate.

    Policy:
    - If ``explicit_rate`` is a positive integer, use it.
    - Otherwise choose the dominant sample-rate family first (44.1k-derived vs
      48k-derived, with exact rates as their own family when neither applies).
    - Within the winning family, choose the exact sample rate by majority, with
      ties resolved upward.
    - If no valid sample rates are available, fall back to ``default``.
    """

    default_rate = _coerce_positive_int(default)
    if default_rate is None:
        raise ValueError("default must be a positive integer")

    observed_rates: list[int] = []
    stem_sample_rates: list[dict[str, Any]] = []
    decoder_warnings: list[dict[str, Any]] = []

    for index, raw_stem_meta in enumerate(stems_meta):
        if not isinstance(raw_stem_meta, Mapping):
            continue

        stem_id = _coerce_str(raw_stem_meta.get("stem_id")).strip()
        if not stem_id:
            stem_id = f"STEM.AUTO.{index + 1:03d}"

        sample_rate_hz = None
        for key in (
            "sample_rate_hz",
            "resolved_sample_rate_hz",
            "decoder_sample_rate_hz",
            "source_sample_rate_hz",
        ):
            sample_rate_hz = _coerce_positive_int(raw_stem_meta.get(key))
            if sample_rate_hz is not None:
                break

        sample_rate_source = _coerce_str(raw_stem_meta.get("sample_rate_source")).strip()
        stem_row: dict[str, Any] = {
            "stem_id": stem_id,
            "sample_rate_hz": sample_rate_hz,
        }
        if sample_rate_source:
            stem_row["sample_rate_source"] = sample_rate_source
        stem_sample_rates.append(stem_row)

        if sample_rate_hz is not None:
            observed_rates.append(sample_rate_hz)

        raw_warnings = raw_stem_meta.get("decoder_warnings")
        if isinstance(raw_warnings, list):
            candidate_warnings = raw_warnings
        elif isinstance(raw_warnings, str):
            candidate_warnings = [raw_warnings]
        else:
            candidate_warnings = []
        for warning in candidate_warnings:
            normalized_warning = _normalize_decoder_warning_row(
                stem_id=stem_id,
                value=warning,
            )
            if normalized_warning is not None:
                decoder_warnings.append(normalized_warning)

    exact_counts = Counter(observed_rates)
    sample_rate_counts = [
        {
            "sample_rate_hz": sample_rate_hz,
            "stem_count": stem_count,
        }
        for sample_rate_hz, stem_count in sorted(exact_counts.items(), key=lambda item: item[0])
    ]

    family_counts = Counter(_sample_rate_family_hz(rate_hz) for rate_hz in observed_rates)
    family_rates: dict[int, list[int]] = {}
    for rate_hz in observed_rates:
        family_hz = _sample_rate_family_hz(rate_hz)
        family_rates.setdefault(family_hz, []).append(rate_hz)
    family_sample_rate_counts = [
        {
            "family_sample_rate_hz": family_hz,
            "stem_count": family_counts[family_hz],
            "max_sample_rate_hz": max(family_rates.get(family_hz) or [family_hz]),
        }
        for family_hz in sorted(family_counts.keys())
    ]

    explicit_sample_rate_hz = _coerce_positive_int(explicit_rate)
    selection_policy = "family_majority_then_exact_majority_then_higher_tiebreak"
    selected_family_sample_rate_hz = _sample_rate_family_hz(default_rate)
    selected_family_reason = "default_sample_rate_hz"

    if explicit_sample_rate_hz is not None:
        selected_sample_rate_hz = explicit_sample_rate_hz
        selection_policy = "explicit_override"
        selection_reason = "explicit_sample_rate_hz"
        selected_family_sample_rate_hz = _sample_rate_family_hz(selected_sample_rate_hz)
        selected_family_reason = "explicit_sample_rate_hz"
    elif not observed_rates:
        selected_sample_rate_hz = default_rate
        selection_reason = "default_sample_rate_hz"
    else:
        max_family_count = max(family_counts.values())
        candidate_families = [
            family_hz
            for family_hz, stem_count in family_counts.items()
            if stem_count == max_family_count
        ]
        selected_family_sample_rate_hz = max(
            candidate_families,
            key=lambda family_hz: (
                max(family_rates.get(family_hz) or [family_hz]),
                family_hz,
            ),
        )
        selected_family_reason = "majority"
        if len(candidate_families) > 1:
            selected_family_reason = "tie_higher_sample_rate_family"

        selected_sample_rate_hz, exact_selection_receipt = choose_render_sample_rate_hz(
            family_rates.get(selected_family_sample_rate_hz, ()),
        )
        if selected_sample_rate_hz is None:
            selected_sample_rate_hz = default_rate
            selection_reason = "default_sample_rate_hz"
        else:
            selection_reason = (
                _coerce_str(exact_selection_receipt.get("selection_reason")).strip()
                or "majority"
            )

    selected_family_exact_counts = Counter(
        family_rates.get(selected_family_sample_rate_hz, ())
    )
    selected_family_sample_rate_counts = [
        {
            "sample_rate_hz": sample_rate_hz,
            "stem_count": stem_count,
        }
        for sample_rate_hz, stem_count in sorted(
            selected_family_exact_counts.items(),
            key=lambda item: item[0],
        )
    ]

    stem_sample_rates.sort(
        key=lambda row: (
            _coerce_str(row.get("stem_id")).strip(),
            int(row.get("sample_rate_hz") or 0),
            _coerce_str(row.get("sample_rate_source")).strip(),
        )
    )
    decoder_warnings.sort(
        key=lambda row: (
            _coerce_str(row.get("stem_id")).strip(),
            _coerce_str(row.get("warning")).strip(),
            _coerce_str(row.get("format")).strip(),
            _coerce_str(row.get("detail")).strip(),
        )
    )

    return selected_sample_rate_hz, {
        "selection_policy": selection_policy,
        "selection_reason": selection_reason,
        "selected_sample_rate_hz": selected_sample_rate_hz,
        "selected_family_sample_rate_hz": selected_family_sample_rate_hz,
        "selected_family_reason": selected_family_reason,
        "sample_rate_counts": sample_rate_counts,
        "family_sample_rate_counts": family_sample_rate_counts,
        "selected_family_sample_rate_counts": selected_family_sample_rate_counts,
        "default_sample_rate_hz": default_rate,
        "stem_count_considered": len(observed_rates),
        "stem_sample_rates": stem_sample_rates,
        "decoder_warnings": decoder_warnings,
    }


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
