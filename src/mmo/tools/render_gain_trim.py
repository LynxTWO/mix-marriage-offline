"""Render conservative gain/trim recommendations into new WAV files."""

from __future__ import annotations

import argparse
import json
import math
import random
import struct
import sys
import wave
from pathlib import Path
from typing import Iterable

from mmo.dsp.io import read_wav_metadata
from mmo.dsp.meters import iter_wav_float64_samples


_ALLOWED_ACTIONS = {
    "ACTION.UTILITY.GAIN": "PARAM.GAIN.DB",
    "ACTION.UTILITY.TRIM": "PARAM.GAIN.TRIM_DB",
}
_FLOAT_MAX = math.nextafter(1.0, 0.0)


def _load_report(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        raise ValueError(f"Failed to read report: {path}") from exc


def _stem_lookup(report: dict) -> dict[str, dict[str, Path]]:
    stems = report.get("session", {}).get("stems", [])
    stem_map: dict[str, dict[str, Path]] = {}
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        stem_id = stem.get("stem_id")
        file_path = stem.get("file_path")
        if not stem_id or not file_path:
            continue
        relative_path = Path(file_path)
        stem_map[stem_id] = {
            "relative_path": relative_path,
            "file_path": relative_path,
        }
    return stem_map


def _resolve_stem_path(stems_dir: Path, file_path: Path) -> tuple[Path, Path]:
    if file_path.is_absolute():
        return file_path, Path(file_path.name)
    return stems_dir / file_path, file_path


def _extract_gain_db(rec: dict) -> float | None:
    action_id = rec.get("action_id")
    param_id = _ALLOWED_ACTIONS.get(action_id)
    if not param_id:
        return None
    for param in rec.get("params", []):
        if not isinstance(param, dict):
            continue
        if param.get("param_id") == param_id:
            try:
                return float(param.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def _iter_safe_recommendations(report: dict) -> Iterable[tuple[str, float]]:
    for rec in report.get("recommendations", []):
        if not isinstance(rec, dict):
            continue
        if rec.get("action_id") not in _ALLOWED_ACTIONS:
            continue
        if rec.get("risk") != "low":
            continue
        if rec.get("requires_approval") is not False:
            continue
        target = rec.get("target", {})
        if not isinstance(target, dict):
            continue
        if target.get("scope") != "stem":
            continue
        stem_id = target.get("stem_id")
        if not stem_id:
            continue
        gain_db = _extract_gain_db(rec)
        if gain_db is None or gain_db > 0.0:
            continue
        yield stem_id, gain_db


def _clamp_sample(value: float) -> float:
    if value < -1.0:
        return -1.0
    if value > _FLOAT_MAX:
        return _FLOAT_MAX
    return value


def _dithered_int_samples(
    float_samples: list[float],
    bits_per_sample: int,
    gain_scalar: float,
    rng: random.Random,
) -> list[int]:
    divisor = float(2 ** (bits_per_sample - 1))
    min_int = -int(divisor)
    max_int = int(divisor) - 1
    output: list[int] = []
    for sample in float_samples:
        value = _clamp_sample(sample * gain_scalar)
        noise = (rng.random() - rng.random()) / divisor
        value = _clamp_sample(value + noise)
        scaled = int(round(value * divisor))
        if scaled < min_int:
            scaled = min_int
        elif scaled > max_int:
            scaled = max_int
        output.append(scaled)
    return output


def _int_samples_to_bytes(samples: list[int], bits_per_sample: int) -> bytes:
    if bits_per_sample == 16:
        return struct.pack(f"<{len(samples)}h", *samples)
    if bits_per_sample == 24:
        data = bytearray(len(samples) * 3)
        for index, sample in enumerate(samples):
            value = sample & 0xFFFFFF
            offset = index * 3
            data[offset : offset + 3] = bytes(
                (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)
            )
        return bytes(data)
    if bits_per_sample == 32:
        return struct.pack(f"<{len(samples)}i", *samples)
    raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")


def _render_gain_trim(path: Path, out_path: Path, gain_db: float) -> None:
    metadata = read_wav_metadata(path)
    audio_format = metadata["audio_format_resolved"]
    if audio_format != 1:
        raise ValueError(f"Unsupported WAV format for rendering: {audio_format}")

    bits_per_sample = metadata["bits_per_sample"]
    channels = metadata["channels"]
    sample_rate_hz = metadata["sample_rate_hz"]
    if bits_per_sample not in (16, 24, 32):
        raise ValueError(f"Unsupported bits per sample: {bits_per_sample}")

    gain_scalar = math.pow(10.0, gain_db / 20.0)
    rng = random.Random(0)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as out_handle:
        out_handle.setnchannels(channels)
        out_handle.setsampwidth(bits_per_sample // 8)
        out_handle.setframerate(sample_rate_hz)

        for float_samples in iter_wav_float64_samples(
            path, error_context="render gain/trim"
        ):
            int_samples = _dithered_int_samples(
                float_samples, bits_per_sample, gain_scalar, rng
            )
            out_handle.writeframes(_int_samples_to_bytes(int_samples, bits_per_sample))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render conservative gain/trim recommendations to new WAV files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("stems_dir", help="Directory containing input stems.")
    parser.add_argument("--report", required=True, help="Path to report JSON.")
    parser.add_argument("--out-dir", required=True, help="Directory for rendered WAV files.")
    args = parser.parse_args()

    stems_dir = Path(args.stems_dir)
    report_path = Path(args.report)
    out_dir = Path(args.out_dir)

    report = _load_report(report_path)
    stem_map = _stem_lookup(report)

    gains: dict[str, float] = {}
    for stem_id, gain_db in _iter_safe_recommendations(report):
        gains[stem_id] = gains.get(stem_id, 0.0) + gain_db

    for stem_id, gain_db in gains.items():
        stem_info = stem_map.get(stem_id)
        if stem_info is None:
            raise ValueError(f"Unknown stem_id in report: {stem_id}")
        file_path = stem_info["file_path"]
        source_path, relative_path = _resolve_stem_path(stems_dir, file_path)
        out_path = out_dir / relative_path
        _render_gain_trim(source_path, out_path, gain_db)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
