from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from mmo.resources import ontology_dir

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None


def load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load YAML files.")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def load_layouts(ontology_layouts_path: Path = Path("ontology/layouts.yaml")) -> Dict[str, Any]:
    data = load_yaml(ontology_layouts_path)
    layouts = data.get("layouts")
    if not isinstance(layouts, dict):
        raise ValueError("layouts.yaml missing 'layouts' mapping")
    result: Dict[str, Any] = {}
    for layout_id, layout_info in layouts.items():
        if layout_id == "_meta":
            continue
        if not isinstance(layout_info, dict):
            raise ValueError(f"Layout entry must be a mapping: {layout_id}")
        channel_order = layout_info.get("channel_order")
        if not isinstance(channel_order, list) or not channel_order:
            raise ValueError(f"Layout {layout_id} missing channel_order list")
        result[layout_id] = layout_info
    return result


def load_downmix_registry(path: Path = Path("ontology/policies/downmix.yaml")) -> Dict[str, Any]:
    return load_yaml(path)


def resolve_downmix_matrix(
    *,
    repo_root: Path | None = None,
    source_layout_id: str,
    target_layout_id: str,
    policy_id: str | None = None,
    layouts_path: Path | None = None,
    registry_path: Path | None = None,
) -> Dict[str, Any]:
    # The ontology layouts and policy packs own channel semantics here. Keep
    # callers from hard-coding their own matrix folklore around this helper.
    layouts_path = layouts_path or (ontology_dir() / "layouts.yaml")
    registry_path = registry_path or (ontology_dir() / "policies" / "downmix.yaml")
    layouts = load_layouts(layouts_path)
    registry = load_downmix_registry(registry_path)
    return resolve_conversion(
        layouts,
        registry,
        repo_root,
        source_layout_id,
        target_layout_id,
        policy_id,
    )


@dataclass
class _Biquad:
    b0: float
    b1: float
    b2: float
    a1: float
    a2: float
    z1: float = 0.0
    z2: float = 0.0

    def process(self, sample: float) -> float:
        y0 = self.b0 * sample + self.z1
        z1 = self.b1 * sample - self.a1 * y0 + self.z2
        z2 = self.b2 * sample - self.a2 * y0
        self.z1 = z1
        self.z2 = z2
        return y0


def _coerce_filter_type(spec: Dict[str, Any]) -> str:
    raw_type = str(spec.get("type", "")).strip().lower()
    if raw_type not in {"lowpass", "highpass"}:
        raise ValueError(f"Unsupported source_pre_filters filter type: {raw_type!r}")
    return raw_type


def _coerce_filter_freq_hz(spec: Dict[str, Any]) -> float:
    freq_hz = spec.get("freq_hz")
    if isinstance(freq_hz, bool) or not isinstance(freq_hz, (int, float)):
        raise ValueError("source_pre_filters filter requires numeric freq_hz")
    freq = float(freq_hz)
    if not math.isfinite(freq) or freq <= 0.0:
        raise ValueError("source_pre_filters freq_hz must be > 0")
    return freq


def _coerce_filter_stage_count(spec: Dict[str, Any]) -> int:
    slope = spec.get("slope_db_per_oct", 12.0)
    if isinstance(slope, bool) or not isinstance(slope, (int, float)):
        raise ValueError("source_pre_filters slope_db_per_oct must be numeric")
    slope_value = abs(float(slope))
    if not math.isfinite(slope_value) or slope_value <= 0.0:
        raise ValueError("source_pre_filters slope_db_per_oct must be > 0")
    # A single biquad contributes ~12 dB/oct. Keep stage count deterministic.
    return max(1, int(round(slope_value / 12.0)))


def _design_biquad(filter_type: str, freq_hz: float, sample_rate_hz: int) -> _Biquad:
    nyquist = float(sample_rate_hz) / 2.0
    if freq_hz >= nyquist:
        raise ValueError(
            f"source_pre_filters freq_hz must be < Nyquist ({nyquist:.3f} Hz)"
        )
    omega = 2.0 * math.pi * freq_hz / float(sample_rate_hz)
    sin_omega = math.sin(omega)
    cos_omega = math.cos(omega)
    q = 1.0 / math.sqrt(2.0)  # Butterworth stage
    alpha = sin_omega / (2.0 * q)
    if filter_type == "lowpass":
        b0 = (1.0 - cos_omega) / 2.0
        b1 = 1.0 - cos_omega
        b2 = (1.0 - cos_omega) / 2.0
    elif filter_type == "highpass":
        b0 = (1.0 + cos_omega) / 2.0
        b1 = -(1.0 + cos_omega)
        b2 = (1.0 + cos_omega) / 2.0
    else:  # pragma: no cover - guarded by caller
        raise ValueError(f"Unsupported filter type: {filter_type!r}")
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_omega
    a2 = 1.0 - alpha
    if a0 == 0.0:
        raise ValueError("Invalid source_pre_filters biquad design (a0 == 0)")
    inv_a0 = 1.0 / a0
    return _Biquad(
        b0=b0 * inv_a0,
        b1=b1 * inv_a0,
        b2=b2 * inv_a0,
        a1=a1 * inv_a0,
        a2=a2 * inv_a0,
    )


def _build_source_pre_filters(
    *,
    source_pre_filters: Dict[str, Any] | None,
    source_speakers: List[str] | None,
    sample_rate_hz: int | None,
) -> Dict[int, List[_Biquad]]:
    if source_pre_filters is None:
        return {}
    if not isinstance(source_pre_filters, dict):
        raise ValueError("source_pre_filters must be a mapping of speaker_id -> filters")
    if not source_pre_filters:
        return {}
    if sample_rate_hz is None or sample_rate_hz <= 0:
        raise ValueError(
            "sample_rate_hz is required when source_pre_filters are provided"
        )
    if not isinstance(source_speakers, list) or not source_speakers:
        raise ValueError(
            "source_speakers are required when source_pre_filters are provided"
        )

    speaker_to_index = {
        str(speaker_id): index for index, speaker_id in enumerate(source_speakers)
    }
    channel_filters: Dict[int, List[_Biquad]] = {}
    for speaker_id in sorted(source_pre_filters.keys(), key=str):
        # Match filters by declared speaker id, not by caller order. A wrong
        # speaker match here would silently filter the wrong channel.
        if speaker_id not in speaker_to_index:
            raise ValueError(
                f"source_pre_filters speaker_id {speaker_id!r} not in source_speakers"
            )
        chain = source_pre_filters.get(speaker_id)
        if not isinstance(chain, list) or not chain:
            raise ValueError(
                f"source_pre_filters[{speaker_id!r}] must be a non-empty list"
            )
        biquads: List[_Biquad] = []
        for spec in chain:
            if not isinstance(spec, dict):
                raise ValueError(
                    f"source_pre_filters[{speaker_id!r}] entries must be mappings"
                )
            filter_type = _coerce_filter_type(spec)
            freq_hz = _coerce_filter_freq_hz(spec)
            stage_count = _coerce_filter_stage_count(spec)
            for _ in range(stage_count):
                biquads.append(_design_biquad(filter_type, freq_hz, int(sample_rate_hz)))
        channel_filters[speaker_to_index[speaker_id]] = biquads
    return channel_filters


def _apply_source_pre_filters(
    interleaved_samples: List[float],
    *,
    channels: int,
    filter_state: Dict[int, List[_Biquad]],
) -> List[float]:
    if not interleaved_samples or not filter_state:
        return interleaved_samples
    total = len(interleaved_samples) - (len(interleaved_samples) % channels)
    if total <= 0:
        return []
    filtered = list(interleaved_samples[:total])
    frames = total // channels
    for channel_index, chain in filter_state.items():
        if channel_index < 0 or channel_index >= channels:
            continue
        for frame_index in range(frames):
            sample_index = frame_index * channels + channel_index
            value = float(filtered[sample_index])
            for biquad in chain:
                value = biquad.process(value)
            filtered[sample_index] = value
    return filtered


def apply_matrix_to_audio(
    coeffs: List[List[float]],
    source_interleaved: List[float],
    source_channels: int,
    target_channels: int = 2,
    *,
    source_pre_filters: Dict[str, Any] | None = None,
    source_speakers: List[str] | None = None,
    sample_rate_hz: int | None = None,
) -> List[float]:
    if target_channels <= 0:
        raise ValueError("target_channels must be positive")
    if source_channels <= 0:
        raise ValueError("source_channels must be positive")
    if len(coeffs) != target_channels:
        raise ValueError("coeffs row count must match target_channels")
    for row in coeffs:
        if len(row) != source_channels:
            raise ValueError("coeffs row width must match source_channels")

    filter_state = _build_source_pre_filters(
        source_pre_filters=source_pre_filters,
        source_speakers=source_speakers,
        sample_rate_hz=sample_rate_hz,
    )
    # Apply source-side filters before matrix folding so policy-controlled
    # preconditioning is reflected in every target speaker sum.
    filtered_source = _apply_source_pre_filters(
        source_interleaved,
        channels=source_channels,
        filter_state=filter_state,
    )

    total_frames = len(filtered_source) // source_channels
    if total_frames <= 0:
        return []

    output: List[float] = []
    for frame_index in range(total_frames):
        base = frame_index * source_channels
        for target_index in range(target_channels):
            row = coeffs[target_index]
            total = 0.0
            for source_index in range(source_channels):
                total += float(row[source_index]) * float(
                    filtered_source[base + source_index]
                )
            output.append(total)
    return output


def iter_apply_matrix_to_chunks(
    coeffs: List[List[float]],
    chunks_iter,
    source_channels: int,
    target_channels: int = 2,
    chunk_frames: int = 4096,
    *,
    source_pre_filters: Dict[str, Any] | None = None,
    source_speakers: List[str] | None = None,
    sample_rate_hz: int | None = None,
):
    if chunk_frames <= 0:
        raise ValueError("chunk_frames must be positive")
    if target_channels <= 0:
        raise ValueError("target_channels must be positive")
    if source_channels <= 0:
        raise ValueError("source_channels must be positive")
    if len(coeffs) != target_channels:
        raise ValueError("coeffs row count must match target_channels")
    for row in coeffs:
        if len(row) != source_channels:
            raise ValueError("coeffs row width must match source_channels")

    filter_state = _build_source_pre_filters(
        source_pre_filters=source_pre_filters,
        source_speakers=source_speakers,
        sample_rate_hz=sample_rate_hz,
    )
    buffer: List[float] = []
    offset = 0

    def _apply_frames(start: int, frames: int) -> List[float]:
        output: List[float] = []
        for frame_index in range(frames):
            base = start + frame_index * source_channels
            for target_index in range(target_channels):
                row = coeffs[target_index]
                total = 0.0
                for source_index in range(source_channels):
                    total += float(row[source_index]) * float(
                        buffer[base + source_index]
                    )
                output.append(total)
        return output

    for chunk in chunks_iter:
        if not chunk:
            continue
        if offset:
            buffer = buffer[offset:]
            offset = 0
        filtered_chunk = _apply_source_pre_filters(
            list(chunk),
            channels=source_channels,
            filter_state=filter_state,
        )
        buffer.extend(filtered_chunk)
        available_samples = len(buffer) - offset
        available_frames = available_samples // source_channels
        while available_frames >= chunk_frames:
            yield _apply_frames(offset, chunk_frames)
            offset += chunk_frames * source_channels
            available_frames -= chunk_frames

    if offset:
        buffer = buffer[offset:]
        offset = 0
    remaining_frames = len(buffer) // source_channels
    if remaining_frames > 0:
        yield _apply_frames(0, remaining_frames)


def format_coeff_rows(
    coeffs: List[List[float]],
    *,
    decimals: int = 6,
) -> List[List[str]]:
    return [
        [f"{float(value):.{decimals}f}" for value in row]
        for row in coeffs
    ]


def format_matrix_csv(
    matrix: Dict[str, Any],
    *,
    decimals: int = 6,
) -> str:
    source_speakers = matrix.get("source_speakers")
    target_speakers = matrix.get("target_speakers")
    coeffs = matrix.get("coeffs")
    if not isinstance(source_speakers, list) or not isinstance(target_speakers, list):
        raise ValueError("Matrix missing speaker order lists")
    if not isinstance(coeffs, list):
        raise ValueError("Matrix missing coeffs list")
    if len(coeffs) != len(target_speakers):
        raise ValueError("Matrix coeff row count does not match target speakers")
    for row in coeffs:
        if not isinstance(row, list):
            raise ValueError("Matrix coeff rows must be lists")
        if len(row) != len(source_speakers):
            raise ValueError("Matrix coeff row width does not match source speakers")

    formatted = format_coeff_rows(coeffs, decimals=decimals)
    rows = [",".join(["target_speaker", *source_speakers])]
    for target_speaker, row in zip(target_speakers, formatted):
        rows.append(",".join([target_speaker, *row]))
    return "\n".join(rows) + "\n"


def render_matrix(
    matrix: Dict[str, Any],
    *,
    output_format: str = "json",
) -> str:
    if output_format == "json":
        return json.dumps(matrix, indent=2, sort_keys=True) + "\n"
    if output_format == "csv":
        return format_matrix_csv(matrix)
    raise ValueError(f"Unsupported output format: {output_format}")


def load_policy_pack(registry: Dict[str, Any], policy_id: str, repo_root: Path | None = None) -> Dict[str, Any]:
    policies = registry.get("downmix", {}).get("policies", {})
    if policy_id not in policies:
        raise ValueError(f"Unknown policy_id: {policy_id}")
    pack_file = policies[policy_id].get("file")
    if not isinstance(pack_file, str) or not pack_file:
        raise ValueError(f"Policy {policy_id} missing file path")
    pack_path = ontology_dir() / "policies" / pack_file
    pack = load_yaml(pack_path)
    pack_meta = pack.get("downmix_policy_pack")
    if not isinstance(pack_meta, dict):
        raise ValueError(f"Policy pack missing downmix_policy_pack: {pack_path}")
    pack_policy_id = pack_meta.get("policy_id")
    if pack_policy_id != policy_id:
        raise ValueError(
            f"Policy pack {pack_path} policy_id mismatch: {pack_policy_id} != {policy_id}"
        )
    return pack


def _matrix_definition(pack: Dict[str, Any], matrix_id: str) -> Dict[str, Any]:
    pack_meta = pack.get("downmix_policy_pack")
    if not isinstance(pack_meta, dict):
        raise ValueError("Policy pack missing downmix_policy_pack.")
    matrices = pack_meta.get("matrices")
    if not isinstance(matrices, dict):
        raise ValueError("Policy pack missing matrices mapping.")
    matrix = matrices.get(matrix_id)
    if not isinstance(matrix, dict):
        raise ValueError(f"Matrix not found: {matrix_id}")
    return matrix


def build_matrix(
    layouts: Dict[str, Any],
    pack: Dict[str, Any],
    matrix_id: str,
) -> Dict[str, Any]:
    matrix_def = _matrix_definition(pack, matrix_id)
    source_layout_id = matrix_def.get("source_layout_id")
    target_layout_id = matrix_def.get("target_layout_id")
    if not isinstance(source_layout_id, str) or not isinstance(target_layout_id, str):
        raise ValueError(f"Matrix {matrix_id} missing source/target layout IDs")

    if source_layout_id not in layouts:
        raise ValueError(f"Unknown source layout: {source_layout_id}")
    if target_layout_id not in layouts:
        raise ValueError(f"Unknown target layout: {target_layout_id}")

    source_order = layouts[source_layout_id].get("channel_order")
    target_order = layouts[target_layout_id].get("channel_order")
    if not isinstance(source_order, list) or not isinstance(target_order, list):
        raise ValueError("Layouts missing channel_order lists")

    coefficients = matrix_def.get("coefficients")
    if not isinstance(coefficients, dict):
        raise ValueError(f"Matrix {matrix_id} missing coefficients mapping")
    target_set = set(target_order)
    source_set = set(source_order)
    source_pre_filters_def = matrix_def.get("source_pre_filters")
    source_pre_filters: Dict[str, Any] = {}
    if source_pre_filters_def is not None:
        if not isinstance(source_pre_filters_def, dict):
            raise ValueError(f"Matrix {matrix_id} source_pre_filters must be a mapping")
        for source_speaker, chain in source_pre_filters_def.items():
            if source_speaker not in source_set:
                raise ValueError(
                    f"Unknown source_pre_filters speaker {source_speaker} in {matrix_id}"
                )
            if not isinstance(chain, list) or not chain:
                raise ValueError(
                    f"Matrix {matrix_id} source_pre_filters[{source_speaker}] must be a non-empty list"
                )
            source_pre_filters[str(source_speaker)] = [
                dict(spec) if isinstance(spec, dict) else spec for spec in chain
            ]

    for target_speaker, source_map in coefficients.items():
        if target_speaker not in target_set:
            raise ValueError(f"Unknown target speaker {target_speaker} in {matrix_id}")
        if not isinstance(source_map, dict):
            raise ValueError(
                f"Matrix {matrix_id} coefficients for {target_speaker} must be a mapping"
            )
        for source_speaker in source_map:
            if source_speaker not in source_set:
                raise ValueError(
                    f"Unknown source speaker {source_speaker} in {matrix_id}"
                )

    coeffs: List[List[float]] = []
    for target_speaker in target_order:
        source_map = coefficients.get(target_speaker, {})
        row: List[float] = []
        for source_speaker in source_order:
            value = source_map.get(source_speaker, 0.0)
            row.append(float(value))
        coeffs.append(row)

    return {
        "matrix_id": matrix_id,
        "source_layout_id": source_layout_id,
        "target_layout_id": target_layout_id,
        "source_speakers": list(source_order),
        "target_speakers": list(target_order),
        "coeffs": coeffs,
        "source_pre_filters": source_pre_filters,
    }


def compose_matrices(A: Dict[str, Any], B: Dict[str, Any]) -> Dict[str, Any]:
    a_coeffs = A.get("coeffs")
    b_coeffs = B.get("coeffs")
    if not isinstance(a_coeffs, list) or not isinstance(b_coeffs, list):
        raise ValueError("Matrices missing coeffs lists")

    source_speakers = list(A.get("source_speakers") or [])
    mid_speakers = list(A.get("target_speakers") or [])
    b_source_speakers = list(B.get("source_speakers") or [])
    target_speakers = list(B.get("target_speakers") or [])

    if mid_speakers != b_source_speakers:
        raise ValueError("Matrix composition requires matching mid speaker order")

    if not source_speakers or not target_speakers or not mid_speakers:
        raise ValueError("Matrix composition requires non-empty speaker lists")

    target_count = len(target_speakers)
    source_count = len(source_speakers)
    mid_count = len(mid_speakers)

    coeffs: List[List[float]] = []
    eps = 1e-12
    for t in range(target_count):
        row: List[float] = []
        for s in range(source_count):
            total = 0.0
            for m in range(mid_count):
                total += float(b_coeffs[t][m]) * float(a_coeffs[m][s])
            if abs(total) < eps:
                total = 0.0
            row.append(total)
        coeffs.append(row)

    return {
        "source_layout_id": A.get("source_layout_id"),
        "target_layout_id": B.get("target_layout_id"),
        "source_speakers": source_speakers,
        "target_speakers": target_speakers,
        "coeffs": coeffs,
        "source_pre_filters": dict(A.get("source_pre_filters") or {}),
    }


def _find_policy_pack_for_matrix(
    registry: Dict[str, Any],
    matrix_id: str,
    repo_root: Path | None,
    cache: Dict[str, Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]] | Tuple[None, None]:
    policies = registry.get("downmix", {}).get("policies", {})
    for policy_id in sorted(policies.keys()):
        if policy_id not in cache:
            cache[policy_id] = load_policy_pack(registry, policy_id, repo_root)
        pack = cache[policy_id]
        matrices = pack.get("downmix_policy_pack", {}).get("matrices", {})
        if isinstance(matrices, dict) and matrix_id in matrices:
            return policy_id, pack
    return None, None


def resolve_conversion(
    layouts: Dict[str, Any],
    registry: Dict[str, Any],
    repo_root: Path | None,
    source_layout_id: str,
    target_layout_id: str,
    policy_id: str | None = None,
) -> Dict[str, Any]:
    defaults = registry.get("downmix", {}).get("default_policy_by_source_layout", {})
    if policy_id is None:
        policy_id = defaults.get(source_layout_id)
    if not policy_id:
        raise ValueError(f"No default policy for source layout {source_layout_id}")

    conversions = registry.get("downmix", {}).get("conversions", [])
    direct_entry = None
    for entry in conversions:
        if not isinstance(entry, dict):
            continue
        if entry.get("source_layout_id") != source_layout_id:
            continue
        if entry.get("target_layout_id") != target_layout_id:
            continue
        entry_policy = entry.get("policy_id")
        if entry_policy and entry_policy != policy_id:
            continue
        direct_entry = entry
        break

    composition_entry = None
    composition_paths = registry.get("downmix", {}).get("composition_paths", [])
    for entry in composition_paths:
        if not isinstance(entry, dict):
            continue
        if entry.get("source_layout_id") != source_layout_id:
            continue
        if entry.get("target_layout_id") != target_layout_id:
            continue
        composition_entry = entry
        break

    use_composition = False
    if composition_entry is not None:
        matrix_id = direct_entry.get("matrix_id") if direct_entry else None
        if isinstance(matrix_id, str) and matrix_id.endswith(".COMPOSED"):
            use_composition = True

    if direct_entry is not None and not use_composition:
        matrix_id = direct_entry.get("matrix_id")
        if not isinstance(matrix_id, str):
            raise ValueError("Direct conversion missing matrix_id")
        entry_policy = direct_entry.get("policy_id") or policy_id
        pack = load_policy_pack(registry, entry_policy, repo_root)
        return build_matrix(layouts, pack, matrix_id)

    if composition_entry is None:
        raise ValueError(
            f"No conversion or composition path for {source_layout_id} -> {target_layout_id}"
        )

    steps = composition_entry.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Composition path missing steps")

    pack_cache: Dict[str, Dict[str, Any]] = {}
    matrices: List[Dict[str, Any]] = []
    used_steps: List[str] = []

    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Composition step must be a mapping")
        matrix_id = step.get("matrix_id")
        if not isinstance(matrix_id, str) or not matrix_id:
            raise ValueError("Composition step missing matrix_id")
        step_policy_id = step.get("policy_id") or policy_id
        pack = load_policy_pack(registry, step_policy_id, repo_root)
        pack_cache.setdefault(step_policy_id, pack)
        matrices_map = pack.get("downmix_policy_pack", {}).get("matrices", {})
        if not (isinstance(matrices_map, dict) and matrix_id in matrices_map):
            found_policy, found_pack = _find_policy_pack_for_matrix(
                registry, matrix_id, repo_root, pack_cache
            )
            if found_pack is None:
                raise ValueError(f"Matrix not found for step: {matrix_id}")
            pack = found_pack

        matrix = build_matrix(layouts, pack, matrix_id)
        step_source = step.get("source_layout_id")
        step_target = step.get("target_layout_id")
        if step_source and step_source != matrix["source_layout_id"]:
            raise ValueError(f"Step {matrix_id} source layout mismatch")
        if step_target and step_target != matrix["target_layout_id"]:
            raise ValueError(f"Step {matrix_id} target layout mismatch")

        matrices.append(matrix)
        used_steps.append(matrix_id)

    composed = matrices[0]
    for next_matrix in matrices[1:]:
        composed = compose_matrices(composed, next_matrix)

    return {
        "matrix_id": f"DMX.COMPOSED.{source_layout_id}_TO_{target_layout_id}",
        "source_layout_id": source_layout_id,
        "target_layout_id": target_layout_id,
        "source_speakers": composed["source_speakers"],
        "target_speakers": composed["target_speakers"],
        "coeffs": composed["coeffs"],
        "source_pre_filters": dict(composed.get("source_pre_filters") or {}),
        "steps": used_steps,
    }
