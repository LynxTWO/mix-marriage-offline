from __future__ import annotations

import math
import struct
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from mmo.dsp.float64 import (
    bytes_to_float_samples_ieee,
    bytes_to_int_samples_pcm,
    pcm_int_to_float64,
)
from mmo.dsp.io import read_wav_metadata

_CHUNK_FRAMES = 4096
_WINDOW_SIZE = 4096
_HOP_SIZE = 1024
_EPSILON = 1e-12
_DEFAULT_PRESENCE_CAP_DB = 1.5


def _normalize_profile_ids(
    profile_ids: list[str],
    *,
    profiles: dict[str, Any],
) -> list[str]:
    if not isinstance(profile_ids, list):
        raise ValueError("profile_ids must be a list of profile identifiers.")

    normalized: list[str] = []
    seen: set[str] = set()
    for profile_id in profile_ids:
        if not isinstance(profile_id, str):
            continue
        token = profile_id.strip()
        if not token or token in seen:
            continue
        normalized.append(token)
        seen.add(token)
    if not normalized:
        raise ValueError("At least one translation profile_id is required.")

    known_ids = sorted(profile_id for profile_id in profiles.keys() if isinstance(profile_id, str))
    known_set = set(known_ids)
    unknown = sorted(profile_id for profile_id in normalized if profile_id not in known_set)
    if unknown:
        unknown_label = ", ".join(unknown)
        known_label = ", ".join(known_ids)
        if known_label:
            raise ValueError(
                f"Unknown translation profile_id: {unknown_label}. Known profile_ids: {known_label}"
            )
        raise ValueError(
            f"Unknown translation profile_id: {unknown_label}. No translation profiles are available."
        )
    return normalized


def _iter_wav_float64_chunks(path: Path) -> tuple[int, int, Iterator[list[float]]]:
    metadata = read_wav_metadata(path)
    channels = int(metadata.get("channels", 0) or 0)
    sample_rate_hz = int(metadata.get("sample_rate_hz", 0) or 0)
    audio_format = int(metadata.get("audio_format_resolved", 0) or 0)
    bits_per_sample = int(metadata.get("bits_per_sample", 0) or 0)

    if channels <= 0:
        raise ValueError(f"Invalid channel count in WAV: {path}")
    if channels > 2:
        raise ValueError(
            "Translation auditions require mono or stereo WAV input (1 or 2 channels), "
            f"got {channels}."
        )
    if audio_format == 1 and bits_per_sample not in (16, 24, 32):
        raise ValueError(f"Unsupported PCM bits per sample: {bits_per_sample}")
    if audio_format == 3 and bits_per_sample not in (32, 64):
        raise ValueError(f"Unsupported IEEE float bits per sample: {bits_per_sample}")
    if audio_format not in (1, 3):
        raise ValueError(f"Unsupported WAV format for translation auditions: {audio_format}")

    def _chunks() -> Iterator[list[float]]:
        try:
            with wave.open(str(path), "rb") as handle:
                while True:
                    frames = handle.readframes(_CHUNK_FRAMES)
                    if not frames:
                        break
                    if audio_format == 1:
                        ints = bytes_to_int_samples_pcm(frames, bits_per_sample, channels)
                        if not ints:
                            continue
                        yield pcm_int_to_float64(ints, bits_per_sample)
                    else:
                        floats = bytes_to_float_samples_ieee(frames, bits_per_sample, channels)
                        if not floats:
                            continue
                        yield floats
        except (OSError, wave.Error) as exc:
            raise ValueError(f"Failed to read WAV for translation auditions: {path}") from exc

    return sample_rate_hz, channels, _chunks()


def _load_channels(path: Path) -> tuple[int, list[float], list[float]]:
    sample_rate_hz, channels, chunks = _iter_wav_float64_chunks(path)
    left: list[float] = []
    right: list[float] = []
    for chunk in chunks:
        if not isinstance(chunk, list) or not chunk:
            continue
        if channels == 1:
            left.extend(chunk)
            continue
        total = len(chunk) - (len(chunk) % 2)
        for index in range(0, total, 2):
            left.append(float(chunk[index]))
            right.append(float(chunk[index + 1]))
    if channels == 1:
        right = list(left)
    return sample_rate_hz, left, right


def _parse_segment(
    *,
    segment_s: float | None,
    sample_rate_hz: int,
    total_frames: int,
) -> tuple[int, int, dict[str, float] | None]:
    if segment_s is None:
        return 0, total_frames, None
    if isinstance(segment_s, bool) or not isinstance(segment_s, (int, float)):
        raise ValueError("segment_s must be a positive number of seconds when provided.")
    if not math.isfinite(float(segment_s)) or float(segment_s) <= 0.0:
        raise ValueError("segment_s must be a positive number of seconds when provided.")

    frame_count = int(round(float(segment_s) * float(sample_rate_hz)))
    end_frame = max(1, min(total_frames, frame_count))
    return 0, end_frame, {
        "start_s": 0.0,
        "end_s": round(end_frame / float(sample_rate_hz), 6),
    }


def _clip_sample(sample: float) -> float:
    if sample > 0.999969:
        return 0.999969
    if sample < -1.0:
        return -1.0
    return sample


def _float_to_pcm16(sample: float) -> int:
    clipped = _clip_sample(sample)
    return int(round(clipped * 32767.0))


def _write_stereo_wav_16bit(
    path: Path,
    *,
    sample_rate_hz: int,
    left: list[float],
    right: list[float],
) -> None:
    frame_count = min(len(left), len(right))
    interleaved: list[int] = []
    for index in range(frame_count):
        interleaved.append(_float_to_pcm16(left[index]))
        interleaved.append(_float_to_pcm16(right[index]))

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate_hz)
            handle.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))
    except OSError as exc:
        raise ValueError(f"Failed to write translation audition WAV: {path}: {exc}") from exc


def _is_power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


def _fft_inplace(values: list[complex], *, inverse: bool) -> None:
    size = len(values)
    if not _is_power_of_two(size):
        raise ValueError("FFT length must be a power of two.")

    j = 0
    for index in range(1, size):
        bit = size >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if index < j:
            values[index], values[j] = values[j], values[index]

    direction = 1.0 if inverse else -1.0
    length = 2
    while length <= size:
        half = length // 2
        theta = direction * (2.0 * math.pi / float(length))
        w_step = complex(math.cos(theta), math.sin(theta))
        for offset in range(0, size, length):
            w_value = 1.0 + 0.0j
            for idx in range(half):
                even = values[offset + idx]
                odd = values[offset + idx + half] * w_value
                values[offset + idx] = even + odd
                values[offset + idx + half] = even - odd
                w_value *= w_step
        length *= 2

    if inverse:
        scale = 1.0 / float(size)
        for index in range(size):
            values[index] *= scale


def _hann_window(size: int) -> list[float]:
    if size <= 1:
        return [1.0] * max(1, size)
    return [
        0.5 - 0.5 * math.cos((2.0 * math.pi * idx) / float(size - 1))
        for idx in range(size)
    ]


def _interp_gain_db(points: list[tuple[float, float]], freq_hz: float) -> float:
    if not points:
        return 0.0
    if freq_hz <= points[0][0]:
        return points[0][1]
    if freq_hz >= points[-1][0]:
        return points[-1][1]

    for index in range(len(points) - 1):
        left_freq, left_db = points[index]
        right_freq, right_db = points[index + 1]
        if left_freq <= freq_hz <= right_freq:
            if right_freq <= left_freq:
                return right_db
            ratio = (freq_hz - left_freq) / (right_freq - left_freq)
            return left_db + (right_db - left_db) * ratio
    return points[-1][1]


def _magnitude_curve(
    *,
    sample_rate_hz: int,
    window_size: int,
    points: list[tuple[float, float]],
) -> list[float]:
    half = window_size // 2
    curve = [1.0] * window_size

    sorted_points = sorted((max(0.0, float(freq)), float(gain_db)) for freq, gain_db in points)
    for bin_index in range(half + 1):
        freq_hz = (bin_index * float(sample_rate_hz)) / float(window_size)
        gain_db = _interp_gain_db(sorted_points, freq_hz)
        linear_gain = 10.0 ** (gain_db / 20.0)
        curve[bin_index] = linear_gain
    for bin_index in range(half + 1, window_size):
        curve[bin_index] = curve[window_size - bin_index]
    return curve


def _shape_channel(
    samples: list[float],
    *,
    sample_rate_hz: int,
    response_points: list[tuple[float, float]],
) -> list[float]:
    if not samples:
        return []

    if _WINDOW_SIZE <= 0 or _HOP_SIZE <= 0:
        raise ValueError("Invalid transform window settings.")
    if _HOP_SIZE > _WINDOW_SIZE:
        raise ValueError("Transform hop size must be <= window size.")

    window = _hann_window(_WINDOW_SIZE)
    response = _magnitude_curve(
        sample_rate_hz=sample_rate_hz,
        window_size=_WINDOW_SIZE,
        points=response_points,
    )

    sample_count = len(samples)
    overlap_acc = [0.0] * (sample_count + _WINDOW_SIZE)
    norm_acc = [0.0] * (sample_count + _WINDOW_SIZE)

    frame_starts = list(range(0, sample_count, _HOP_SIZE))
    for start in frame_starts:
        frame = [0.0] * _WINDOW_SIZE
        for idx in range(_WINDOW_SIZE):
            source_idx = start + idx
            if source_idx >= sample_count:
                break
            frame[idx] = samples[source_idx] * window[idx]

        spectrum = [complex(value, 0.0) for value in frame]
        _fft_inplace(spectrum, inverse=False)
        for index in range(_WINDOW_SIZE):
            spectrum[index] *= response[index]
        _fft_inplace(spectrum, inverse=True)

        for idx in range(_WINDOW_SIZE):
            position = start + idx
            window_value = window[idx]
            overlap_acc[position] += spectrum[idx].real * window_value
            norm_acc[position] += window_value * window_value

    shaped = [0.0] * sample_count
    for index in range(sample_count):
        norm = norm_acc[index]
        if norm > _EPSILON:
            shaped[index] = overlap_acc[index] / norm
        else:
            shaped[index] = overlap_acc[index]
    return shaped


def _stereo_mono_collapse(left: list[float], right: list[float]) -> tuple[list[float], list[float]]:
    collapsed = [
        (left_value + right_value) * 0.5
        for left_value, right_value in zip(left, right)
    ]
    return collapsed, list(collapsed)


def _apply_response(
    *,
    left: list[float],
    right: list[float],
    sample_rate_hz: int,
    response_points: list[tuple[float, float]],
) -> tuple[list[float], list[float]]:
    shaped_left = _shape_channel(left, sample_rate_hz=sample_rate_hz, response_points=response_points)
    shaped_right = _shape_channel(
        right,
        sample_rate_hz=sample_rate_hz,
        response_points=response_points,
    )
    return shaped_left, shaped_right


def _presence_cap_db(left: list[float], right: list[float]) -> float:
    peak = max([abs(value) for value in left + right], default=0.0)
    if peak <= _EPSILON:
        return _DEFAULT_PRESENCE_CAP_DB
    headroom_db = -20.0 * math.log10(max(peak, _EPSILON))
    return max(0.0, min(_DEFAULT_PRESENCE_CAP_DB, headroom_db - 0.5))


def _profile_points(profile_id: str, *, presence_cap_db: float) -> list[tuple[float, float]]:
    if profile_id == "TRANS.DEVICE.PHONE":
        return [
            (0.0, -60.0),
            (180.0, -18.0),
            (300.0, 0.0),
            (3400.0, 0.0),
            (4200.0, -18.0),
            (8000.0, -54.0),
            (22050.0, -72.0),
        ]
    if profile_id == "TRANS.DEVICE.SMALL_SPEAKER":
        return [
            (0.0, -36.0),
            (90.0, -9.0),
            (150.0, 0.0),
            (10000.0, 0.0),
            (13000.0, -9.0),
            (17000.0, -30.0),
            (22050.0, -54.0),
        ]
    if profile_id == "TRANS.DEVICE.EARBUDS":
        return [
            (0.0, 0.0),
            (1800.0, 0.0),
            (2600.0, presence_cap_db),
            (5000.0, presence_cap_db),
            (7000.0, 0.0),
            (12000.0, -1.0),
            (22050.0, -2.0),
        ]
    if profile_id == "TRANS.DEVICE.CAR":
        return [
            (0.0, 1.5),
            (80.0, 1.5),
            (120.0, 1.0),
            (300.0, 0.0),
            (700.0, -1.0),
            (2500.0, -1.5),
            (6000.0, -0.8),
            (12000.0, 0.0),
            (22050.0, 0.0),
        ]
    return []


def _profile_notes(profile_id: str, *, presence_cap_db: float) -> list[str]:
    if profile_id == "TRANS.MONO.COLLAPSE":
        return ["Downmixed to mono (L+R)/2 and duplicated to stereo."]
    if profile_id == "TRANS.DEVICE.PHONE":
        return ["Applied deterministic band-limit (~300-3400 Hz)."]
    if profile_id == "TRANS.DEVICE.SMALL_SPEAKER":
        return ["Applied deterministic high-pass (~150 Hz) and low-pass (~10 kHz)."]
    if profile_id == "TRANS.DEVICE.EARBUDS":
        return [f"Applied deterministic presence cap surrogate (+{presence_cap_db:.2f} dB max)."]
    if profile_id == "TRANS.DEVICE.CAR":
        return ["Applied deterministic low emphasis with slight mid attenuation."]
    return ["No audition transform is defined for this profile; wrote pass-through audio."]


def render_translation_auditions(
    *,
    audio_path: Path,
    out_dir: Path,
    profiles: dict,
    profile_ids: list[str],
    segment_s: float | None = None,
) -> dict[str, Any]:
    if not isinstance(audio_path, Path):
        raise ValueError("audio_path must be a pathlib.Path.")
    if not audio_path.exists():
        raise ValueError(f"Audio path does not exist: {audio_path}")
    if not audio_path.is_file():
        raise ValueError(f"Audio path must be a file: {audio_path}")
    if audio_path.suffix.lower() not in {".wav", ".wave"}:
        raise ValueError("Translation auditions currently support WAV input only.")
    if not isinstance(out_dir, Path):
        raise ValueError("out_dir must be a pathlib.Path.")
    if not isinstance(profiles, dict):
        raise ValueError("profiles must be a mapping of profile_id to profile definition.")

    resolved_profile_ids = _normalize_profile_ids(profile_ids, profiles=profiles)

    sample_rate_hz, full_left, full_right = _load_channels(audio_path)
    total_frames = min(len(full_left), len(full_right))
    if total_frames <= 0:
        raise ValueError(f"WAV contains no audio frames for translation audition: {audio_path}")
    start_frame, end_frame, segment_payload = _parse_segment(
        segment_s=segment_s,
        sample_rate_hz=sample_rate_hz,
        total_frames=total_frames,
    )

    left = list(full_left[start_frame:end_frame])
    right = list(full_right[start_frame:end_frame])

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(
            f"Failed to create translation audition output directory: {out_dir}: {exc}"
        ) from exc

    renders: list[dict[str, Any]] = []
    for profile_id in resolved_profile_ids:
        presence_cap_db = _presence_cap_db(left, right)
        notes = _profile_notes(profile_id, presence_cap_db=presence_cap_db)

        if profile_id == "TRANS.MONO.COLLAPSE":
            shaped_left, shaped_right = _stereo_mono_collapse(left, right)
        elif profile_id.startswith("TRANS.DEVICE."):
            response_points = _profile_points(profile_id, presence_cap_db=presence_cap_db)
            if response_points:
                shaped_left, shaped_right = _apply_response(
                    left=left,
                    right=right,
                    sample_rate_hz=sample_rate_hz,
                    response_points=response_points,
                )
            else:
                shaped_left = list(left)
                shaped_right = list(right)
        else:
            shaped_left = list(left)
            shaped_right = list(right)

        wav_path = (out_dir / f"{profile_id}.wav").resolve()
        _write_stereo_wav_16bit(
            wav_path,
            sample_rate_hz=sample_rate_hz,
            left=shaped_left,
            right=shaped_right,
        )
        renders.append(
            {
                "profile_id": profile_id,
                "path": wav_path.as_posix(),
                "notes": notes,
            }
        )

    return {
        "audio_in": audio_path.resolve().as_posix(),
        "segment": segment_payload,
        "renders": renders,
    }
