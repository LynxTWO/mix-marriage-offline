from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path
from typing import Any, Dict, List

from mmo.dsp.io import read_wav_metadata, sha256_file
from mmo.dsp.meters import iter_wav_float64_samples
from mmo.plugins.interfaces import Recommendation, RenderManifest, RendererPlugin


_ALLOWED_ACTIONS = {
    "ACTION.UTILITY.GAIN": "PARAM.GAIN.DB",
    "ACTION.UTILITY.TRIM": "PARAM.GAIN.TRIM_DB",
}
_FLOAT_MAX = math.nextafter(1.0, 0.0)


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _extract_gain_db(rec: Dict[str, Any], param_id: str) -> float | None:
    params = rec.get("params")
    if not isinstance(params, list):
        return None
    for param in params:
        if not isinstance(param, dict):
            continue
        if param.get("param_id") != param_id:
            continue
        return _coerce_float(param.get("value"))
    return None


def _iter_applicable_recommendations(
    recommendations: List[Recommendation],
) -> List[Dict[str, Any]]:
    applicable: List[Dict[str, Any]] = []
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        action_id = _coerce_str(rec.get("action_id"))
        param_id = _ALLOWED_ACTIONS.get(action_id)
        if param_id is None:
            continue
        if rec.get("risk") != "low":
            continue
        if rec.get("requires_approval") is not False:
            continue
        target = rec.get("target")
        if not isinstance(target, dict):
            continue
        if target.get("scope") != "stem":
            continue
        stem_id = _coerce_str(target.get("stem_id"))
        if not stem_id:
            continue
        recommendation_id = _coerce_str(rec.get("recommendation_id"))
        if not recommendation_id:
            continue
        gain_db = _extract_gain_db(rec, param_id)
        if gain_db is None or gain_db > 0.0:
            continue
        applicable.append(
            {
                "recommendation_id": recommendation_id,
                "action_id": action_id,
                "stem_id": stem_id,
                "gain_db": gain_db,
            }
        )
    applicable.sort(
        key=lambda item: (
            item["stem_id"],
            item["recommendation_id"],
            item["action_id"],
        )
    )
    return applicable


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


def _render_gain_trim(
    source_path: Path,
    output_path: Path,
    gain_db: float,
    *,
    bits_per_sample: int,
    channels: int,
    sample_rate_hz: int,
) -> None:
    gain_scalar = math.pow(10.0, gain_db / 20.0)
    rng = random.Random(0)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as out_handle:
        out_handle.setnchannels(channels)
        out_handle.setsampwidth(bits_per_sample // 8)
        out_handle.setframerate(sample_rate_hz)

        for float_samples in iter_wav_float64_samples(
            source_path, error_context="render gain/trim"
        ):
            int_samples = _dithered_int_samples(
                float_samples,
                bits_per_sample,
                gain_scalar,
                rng,
            )
            out_handle.writeframes(_int_samples_to_bytes(int_samples, bits_per_sample))


def _resolve_stems_dir(session: Dict[str, Any]) -> Path | None:
    stems_dir = session.get("stems_dir")
    if isinstance(stems_dir, str) and stems_dir:
        return Path(stems_dir)
    return None


def _stem_index(session: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    stems = session.get("stems")
    if not isinstance(stems, list):
        return {}
    indexed: Dict[str, Dict[str, Any]] = {}
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        stem_id = _coerce_str(stem.get("stem_id"))
        if not stem_id or stem_id in indexed:
            continue
        indexed[stem_id] = stem
    return indexed


def _resolve_source_and_relative_path(
    stem: Dict[str, Any],
    stems_dir: Path | None,
) -> tuple[Path | None, Path | None, str | None]:
    file_path_value = _coerce_str(stem.get("file_path"))
    if not file_path_value:
        return None, None, "missing_stem_file_path"

    file_path = Path(file_path_value)
    if file_path.is_absolute():
        if stems_dir is None:
            return file_path, Path(file_path.name), None
        try:
            return file_path, file_path.relative_to(stems_dir), None
        except ValueError:
            return file_path, Path(file_path.name), None

    if stems_dir is None:
        return None, None, "missing_stems_dir"

    return stems_dir / file_path, file_path, None


def _rendered_relative_path(source_relative_path: Path) -> Path:
    return source_relative_path.with_name(
        f"{source_relative_path.stem}.mmo_gaintrim.wav"
    )


def _sorted_skipped(skipped: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    items = sorted(
        skipped,
        key=lambda item: (
            item["recommendation_id"],
            item["action_id"],
            item["reason"],
        ),
    )
    merged: List[Dict[str, str]] = []
    for item in items:
        key = (item["recommendation_id"], item["action_id"], item["reason"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


class GainTrimRenderer(RendererPlugin):
    plugin_id = "PLUGIN.RENDERER.GAIN_TRIM"

    def render(
        self,
        session: Dict[str, Any],
        recommendations: List[Recommendation],
        output_dir: Any = None,
    ) -> RenderManifest:
        applicable = _iter_applicable_recommendations(recommendations)
        manifest: RenderManifest = {
            "renderer_id": self.plugin_id,
            "outputs": [],
            "skipped": [],
        }
        if not applicable:
            return manifest

        out_dir: Path | None = None
        if output_dir is not None:
            out_dir = Path(output_dir)
        if out_dir is None:
            manifest["skipped"] = _sorted_skipped(
                [
                    {
                        "recommendation_id": rec["recommendation_id"],
                        "action_id": rec["action_id"],
                        "reason": "missing_output_dir",
                        "gate_summary": "",
                    }
                    for rec in applicable
                ]
            )
            return manifest

        stems_dir = _resolve_stems_dir(session)
        stems_by_id = _stem_index(session)

        grouped_by_stem: Dict[str, List[Dict[str, Any]]] = {}
        for rec in applicable:
            grouped_by_stem.setdefault(rec["stem_id"], []).append(rec)

        outputs: List[Dict[str, Any]] = []
        skipped: List[Dict[str, str]] = []
        for stem_id in sorted(grouped_by_stem.keys()):
            contributions = grouped_by_stem[stem_id]
            stem = stems_by_id.get(stem_id)
            if stem is None:
                for rec in contributions:
                    skipped.append(
                        {
                            "recommendation_id": rec["recommendation_id"],
                            "action_id": rec["action_id"],
                            "reason": "missing_stem",
                            "gate_summary": "",
                        }
                    )
                continue

            source_path, source_relative_path, resolve_reason = (
                _resolve_source_and_relative_path(stem, stems_dir)
            )
            if resolve_reason is not None or source_path is None or source_relative_path is None:
                reason = resolve_reason or "missing_stem_file_path"
                for rec in contributions:
                    skipped.append(
                        {
                            "recommendation_id": rec["recommendation_id"],
                            "action_id": rec["action_id"],
                            "reason": reason,
                            "gate_summary": "",
                        }
                    )
                continue

            if source_path.suffix.lower() not in {".wav", ".wave"}:
                for rec in contributions:
                    skipped.append(
                        {
                            "recommendation_id": rec["recommendation_id"],
                            "action_id": rec["action_id"],
                            "reason": "unsupported_format",
                            "gate_summary": "",
                        }
                    )
                continue

            try:
                metadata = read_wav_metadata(source_path)
            except ValueError:
                for rec in contributions:
                    skipped.append(
                        {
                            "recommendation_id": rec["recommendation_id"],
                            "action_id": rec["action_id"],
                            "reason": "unsupported_format",
                            "gate_summary": "",
                        }
                    )
                continue

            audio_format = metadata.get("audio_format_resolved")
            bits_per_sample = metadata.get("bits_per_sample")
            channels = metadata.get("channels")
            sample_rate_hz = metadata.get("sample_rate_hz")

            if audio_format != 1 or bits_per_sample not in (16, 24, 32):
                for rec in contributions:
                    skipped.append(
                        {
                            "recommendation_id": rec["recommendation_id"],
                            "action_id": rec["action_id"],
                            "reason": "unsupported_wav_format",
                            "gate_summary": "",
                        }
                    )
                continue
            if not isinstance(channels, int) or not isinstance(sample_rate_hz, int):
                for rec in contributions:
                    skipped.append(
                        {
                            "recommendation_id": rec["recommendation_id"],
                            "action_id": rec["action_id"],
                            "reason": "unsupported_wav_format",
                            "gate_summary": "",
                        }
                    )
                continue

            output_relative_path = _rendered_relative_path(source_relative_path)
            output_path = out_dir / output_relative_path

            applied_gain_db = sum(float(rec["gain_db"]) for rec in contributions)
            _render_gain_trim(
                source_path,
                output_path,
                applied_gain_db,
                bits_per_sample=bits_per_sample,
                channels=channels,
                sample_rate_hz=sample_rate_hz,
            )
            output_sha256 = sha256_file(output_path)

            recommendation_ids = sorted(rec["recommendation_id"] for rec in contributions)
            representative = min(
                contributions,
                key=lambda rec: (rec["recommendation_id"], rec["action_id"]),
            )

            notes = ""
            if len(recommendation_ids) > 1:
                notes = f"Contributing recommendation IDs: {','.join(recommendation_ids)}"

            outputs.append(
                {
                    "output_id": f"OUTPUT.GAIN_TRIM.{stem_id}.{output_sha256[:12]}",
                    "file_path": output_relative_path.as_posix(),
                    "action_id": representative["action_id"],
                    "recommendation_id": representative["recommendation_id"],
                    "target_stem_id": stem_id,
                    "format": "wav",
                    "sample_rate_hz": sample_rate_hz,
                    "bit_depth": bits_per_sample,
                    "channel_count": channels,
                    "sha256": output_sha256,
                    "notes": notes,
                    "metadata": {
                        "applied_gain_db": applied_gain_db,
                        "contributing_recommendation_ids": recommendation_ids,
                    },
                }
            )

        outputs.sort(key=lambda item: (item.get("target_stem_id", ""), item.get("output_id", "")))
        manifest["outputs"] = outputs
        manifest["skipped"] = _sorted_skipped(skipped)
        return manifest
