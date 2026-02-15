from __future__ import annotations

import json
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from mmo.core.render_targets import list_render_targets
from mmo.dsp.downmix import iter_apply_matrix_to_chunks, resolve_downmix_matrix
from mmo.dsp.float64 import (
    bytes_to_float_samples_ieee,
    bytes_to_int_samples_pcm,
    pcm_int_to_float64,
)
from mmo.dsp.io import read_wav_metadata

_DEFAULT_PREFERRED_TARGET_IDS: tuple[str, ...] = (
    "TARGET.STEREO.2_0",
    "TARGET.SURROUND.7_1",
    "TARGET.SURROUND.5_1",
)
_STEREO_LAYOUT_ID = "LAYOUT.2_0"
_WAV_SUFFIXES = {".wav", ".wave"}
_CHUNK_FRAMES = 4096
_UNKNOWN_TARGET_ID = "TARGET.UNKNOWN"


class TranslationReferenceResolutionError(ValueError):
    """Raised when translation reference audio cannot be deterministically resolved."""


@dataclass(frozen=True)
class _AudioCandidate:
    target_id: str
    audio_path: Path
    source_layout_id: str | None
    downmix_policy_id: str | None
    channel_count: int | None


from mmo.resources import ontology_dir


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object: {path}")
    return payload


def _is_target_id(value: str) -> bool:
    return bool(value) and value.startswith("TARGET.")


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        token = path.resolve().as_posix()
        if token in seen:
            continue
        seen.add(token)
        deduped.append(path.resolve())
    return deduped


def _path_from_result_value(
    value: Any,
    *,
    root_out_dir: Path,
    variant_out_dir: Path | None = None,
) -> Path | None:
    raw = _coerce_str(value).strip()
    if not raw:
        return None
    parsed = Path(raw)
    if parsed.is_absolute():
        return parsed.resolve()
    if variant_out_dir is not None:
        return (variant_out_dir / parsed).resolve()
    return (root_out_dir / parsed).resolve()


def _render_target_lookup() -> dict[str, dict[str, str | None]]:
    lookup: dict[str, dict[str, str | None]] = {}
    for target in list_render_targets(ontology_dir() / "render_targets.yaml"):
        target_id = _coerce_str(target.get("target_id")).strip()
        if not target_id:
            continue
        layout_id = _coerce_str(target.get("layout_id")).strip() or None
        downmix_policy_id = _coerce_str(target.get("downmix_policy_id")).strip() or None
        lookup[target_id] = {
            "layout_id": layout_id,
            "downmix_policy_id": downmix_policy_id,
        }
    return lookup


def _resolve_audio_path(
    *,
    file_path_value: str,
    candidate_roots: list[Path],
) -> Path | None:
    normalized = file_path_value.strip()
    if not normalized:
        return None
    candidate = Path(normalized)
    if candidate.is_absolute():
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
        return None
    for root in candidate_roots:
        resolved = (root / candidate).resolve()
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _is_wav_output(*, file_path: str, output_format: str) -> bool:
    normalized_format = output_format.strip().lower()
    if normalized_format:
        return normalized_format == "wav"
    return Path(file_path).suffix.lower() in _WAV_SUFFIXES


def _output_sort_key(output: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _coerce_str(output.get("format")).strip().lower(),
        _coerce_str(output.get("file_path")).strip(),
        _coerce_str(output.get("output_id")).strip(),
    )


def _manifest_audio_candidates(
    *,
    render_manifest: dict[str, Any],
    target_layout_id: str | None,
    candidate_roots: list[Path],
) -> list[tuple[Path, int | None, str | None]]:
    outputs_by_output_id: dict[str, list[dict[str, Any]]] = {}
    outputs_all: list[dict[str, Any]] = []

    for renderer_manifest in _coerce_dict_list(render_manifest.get("renderer_manifests")):
        for output in _coerce_dict_list(renderer_manifest.get("outputs")):
            output_id = _coerce_str(output.get("output_id")).strip()
            if output_id:
                outputs_by_output_id.setdefault(output_id, []).append(output)
            outputs_all.append(output)

    for output_id in list(outputs_by_output_id):
        outputs_by_output_id[output_id] = sorted(
            outputs_by_output_id[output_id],
            key=_output_sort_key,
        )
    outputs_all = sorted(outputs_all, key=_output_sort_key)

    preferred_output_ids: list[str] = []
    if target_layout_id:
        for deliverable in sorted(
            _coerce_dict_list(render_manifest.get("deliverables")),
            key=lambda item: _coerce_str(item.get("deliverable_id")).strip(),
        ):
            deliverable_layout_id = _coerce_str(deliverable.get("target_layout_id")).strip()
            if deliverable_layout_id != target_layout_id:
                continue
            for output_id in sorted(
                {
                    _coerce_str(output_id).strip()
                    for output_id in deliverable.get("output_ids", [])
                    if isinstance(output_id, str) and _coerce_str(output_id).strip()
                }
            ):
                preferred_output_ids.append(output_id)

    resolved: list[tuple[Path, int | None, str | None]] = []
    seen_paths: set[str] = set()

    def _append_output(output: dict[str, Any]) -> None:
        file_path = _coerce_str(output.get("file_path")).strip()
        output_format = _coerce_str(output.get("format")).strip()
        if not file_path or not _is_wav_output(file_path=file_path, output_format=output_format):
            return
        audio_path = _resolve_audio_path(file_path_value=file_path, candidate_roots=candidate_roots)
        if audio_path is None:
            return
        path_token = audio_path.as_posix()
        if path_token in seen_paths:
            return
        seen_paths.add(path_token)
        metadata = _coerce_dict(output.get("metadata"))
        source_layout_id = _coerce_str(output.get("layout_id")).strip() or _coerce_str(
            metadata.get("target_layout_id")
        ).strip()
        resolved.append(
            (
                audio_path,
                _coerce_positive_int(output.get("channel_count")),
                source_layout_id or None,
            )
        )

    for output_id in preferred_output_ids:
        for output in outputs_by_output_id.get(output_id, []):
            _append_output(output)
    for output in outputs_all:
        _append_output(output)

    return resolved


def _collect_candidates_from_deliverables_index(
    *,
    out_dir: Path,
    deliverables_index_path: Path,
    render_targets: dict[str, dict[str, str | None]],
) -> list[_AudioCandidate]:
    if not deliverables_index_path.exists() or deliverables_index_path.is_dir():
        return []

    payload = _load_json_object(deliverables_index_path, label="Deliverables index")
    root_out_dir = _path_from_result_value(
        payload.get("root_out_dir"),
        root_out_dir=out_dir,
    )
    if root_out_dir is None:
        root_out_dir = out_dir.resolve()

    candidates: list[_AudioCandidate] = []
    entries = sorted(
        _coerce_dict_list(payload.get("entries")),
        key=lambda item: (
            _coerce_str(item.get("variant_id")).strip(),
            _coerce_str(item.get("entry_id")).strip(),
            _coerce_str(item.get("label")).strip(),
        ),
    )
    for entry in entries:
        target_id = _coerce_str(entry.get("label")).strip()
        if not _is_target_id(target_id):
            continue

        target_info = render_targets.get(target_id, {})
        fallback_source_layout_id = _coerce_str(target_info.get("layout_id")).strip() or None
        downmix_policy_id = _coerce_str(target_info.get("downmix_policy_id")).strip() or None

        artifacts = _coerce_dict(entry.get("artifacts"))
        candidate_roots: list[Path] = [root_out_dir]
        for artifact_key in ("render_manifest", "report", "bundle", "apply_manifest"):
            artifact_path = _path_from_result_value(
                artifacts.get(artifact_key),
                root_out_dir=root_out_dir,
            )
            if artifact_path is None:
                continue
            candidate_roots.append(artifact_path.parent)
            candidate_roots.append(artifact_path.parent / "render")
        candidate_roots = _dedupe_paths(candidate_roots)

        for deliverable in sorted(
            _coerce_dict_list(entry.get("deliverables")),
            key=lambda item: _coerce_str(item.get("deliverable_id")).strip(),
        ):
            source_layout_id = _coerce_str(deliverable.get("target_layout_id")).strip() or (
                fallback_source_layout_id or ""
            )
            channel_count = _coerce_positive_int(deliverable.get("channel_count"))
            for file_entry in sorted(
                _coerce_dict_list(deliverable.get("files")),
                key=lambda item: (
                    _coerce_str(item.get("format")).strip().lower(),
                    _coerce_str(item.get("path")).strip(),
                    _coerce_str(item.get("sha256")).strip(),
                ),
            ):
                file_path = _coerce_str(file_entry.get("path")).strip()
                output_format = _coerce_str(file_entry.get("format")).strip()
                if not file_path or not _is_wav_output(
                    file_path=file_path,
                    output_format=output_format,
                ):
                    continue
                audio_path = _resolve_audio_path(
                    file_path_value=file_path,
                    candidate_roots=candidate_roots,
                )
                if audio_path is None:
                    continue
                candidates.append(
                    _AudioCandidate(
                        target_id=target_id,
                        audio_path=audio_path,
                        source_layout_id=source_layout_id or None,
                        downmix_policy_id=downmix_policy_id,
                        channel_count=channel_count,
                    )
                )
    return candidates


def _collect_candidates_from_variant_result(
    *,
    out_dir: Path,
    render_targets: dict[str, dict[str, str | None]],
) -> list[_AudioCandidate]:
    variant_result_path = out_dir / "variant_result.json"
    if not variant_result_path.exists() or variant_result_path.is_dir():
        return []

    payload = _load_json_object(variant_result_path, label="Variant result")
    plan = _coerce_dict(payload.get("plan"))
    variants = _coerce_dict_list(plan.get("variants"))
    by_variant_id: dict[str, dict[str, Any]] = {}
    for variant in sorted(
        variants,
        key=lambda item: _coerce_str(item.get("variant_id")).strip(),
    ):
        variant_id = _coerce_str(variant.get("variant_id")).strip()
        if not variant_id or variant_id in by_variant_id:
            continue
        by_variant_id[variant_id] = variant

    candidates: list[_AudioCandidate] = []
    results = sorted(
        _coerce_dict_list(payload.get("results")),
        key=lambda item: _coerce_str(item.get("variant_id")).strip(),
    )
    for result in results:
        variant_id = _coerce_str(result.get("variant_id")).strip()
        plan_variant = _coerce_dict(by_variant_id.get(variant_id))

        target_id = _coerce_str(plan_variant.get("label")).strip()
        if not _is_target_id(target_id):
            continue
        target_info = render_targets.get(target_id, {})
        fallback_source_layout_id = _coerce_str(target_info.get("layout_id")).strip() or None
        downmix_policy_id = _coerce_str(target_info.get("downmix_policy_id")).strip() or None

        variant_out_dir = _path_from_result_value(
            result.get("out_dir"),
            root_out_dir=out_dir,
        )
        render_manifest_path = _path_from_result_value(
            result.get("render_manifest_path"),
            root_out_dir=out_dir,
            variant_out_dir=variant_out_dir,
        )
        if render_manifest_path is None or not render_manifest_path.exists():
            continue
        if render_manifest_path.is_dir():
            continue

        render_manifest = _load_json_object(
            render_manifest_path,
            label=f"Render manifest ({variant_id or 'unknown'})",
        )
        candidate_roots: list[Path] = []
        if isinstance(variant_out_dir, Path):
            candidate_roots.append(variant_out_dir / "render")
            candidate_roots.append(variant_out_dir)
        candidate_roots.append(render_manifest_path.parent / "render")
        candidate_roots.append(render_manifest_path.parent)
        candidate_roots = _dedupe_paths(candidate_roots)

        target_layout_id = _coerce_str(plan_variant.get("target_layout_id")).strip() or (
            fallback_source_layout_id or ""
        )
        for audio_path, channel_count, source_layout_id in _manifest_audio_candidates(
            render_manifest=render_manifest,
            target_layout_id=target_layout_id or None,
            candidate_roots=candidate_roots,
        ):
            candidates.append(
                _AudioCandidate(
                    target_id=target_id,
                    audio_path=audio_path,
                    source_layout_id=source_layout_id or fallback_source_layout_id,
                    downmix_policy_id=downmix_policy_id,
                    channel_count=channel_count,
                )
            )
    return candidates


def _collect_candidates_from_render_manifest(
    *,
    out_dir: Path,
    render_manifest_path: Path,
) -> list[_AudioCandidate]:
    if not render_manifest_path.exists() or render_manifest_path.is_dir():
        return []

    render_manifest = _load_json_object(render_manifest_path, label="Render manifest")
    candidate_roots = _dedupe_paths(
        [
            out_dir.resolve(),
            render_manifest_path.parent.resolve(),
            (render_manifest_path.parent / "render").resolve(),
        ]
    )
    candidates: list[_AudioCandidate] = []
    for audio_path, channel_count, source_layout_id in _manifest_audio_candidates(
        render_manifest=render_manifest,
        target_layout_id=None,
        candidate_roots=candidate_roots,
    ):
        candidates.append(
            _AudioCandidate(
                target_id=_UNKNOWN_TARGET_ID,
                audio_path=audio_path,
                source_layout_id=source_layout_id,
                downmix_policy_id=None,
                channel_count=channel_count,
            )
        )
    return candidates


def _normalize_preference_ids(prefer_target_ids: list[str] | None) -> list[str]:
    source = prefer_target_ids if isinstance(prefer_target_ids, list) else list(
        _DEFAULT_PREFERRED_TARGET_IDS
    )
    normalized: list[str] = []
    seen: set[str] = set()
    for item in source:
        token = item.strip() if isinstance(item, str) else ""
        if not token or token in seen:
            continue
        normalized.append(token)
        seen.add(token)
    return normalized


def _target_order(
    *,
    target_ids: set[str],
    prefer_target_ids: list[str] | None,
) -> list[str]:
    preferred = _normalize_preference_ids(prefer_target_ids)
    ordered: list[str] = []
    seen: set[str] = set()
    for target_id in preferred:
        if target_id in target_ids and target_id not in seen:
            ordered.append(target_id)
            seen.add(target_id)
    for target_id in sorted(target_ids):
        if target_id in seen:
            continue
        ordered.append(target_id)
        seen.add(target_id)
    return ordered


def _candidate_sort_key(candidate: _AudioCandidate) -> tuple[int, str, str, str]:
    channel_sort = candidate.channel_count if isinstance(candidate.channel_count, int) else 0
    return (
        -channel_sort,
        candidate.audio_path.as_posix(),
        candidate.source_layout_id or "",
        candidate.downmix_policy_id or "",
    )


def _iter_wav_float64_chunks(path: Path) -> tuple[int, int, Iterator[list[float]]]:
    metadata = read_wav_metadata(path)
    channels = int(metadata.get("channels", 0) or 0)
    sample_rate_hz = int(metadata.get("sample_rate_hz", 0) or 0)
    audio_format = int(metadata.get("audio_format_resolved", 0) or 0)
    bits_per_sample = int(metadata.get("bits_per_sample", 0) or 0)

    if channels <= 0:
        raise ValueError(f"Invalid channel count in WAV: {path}")
    if audio_format == 1 and bits_per_sample not in (16, 24, 32):
        raise ValueError(f"Unsupported PCM bits per sample: {bits_per_sample}")
    if audio_format == 3 and bits_per_sample not in (32, 64):
        raise ValueError(f"Unsupported IEEE float bits per sample: {bits_per_sample}")
    if audio_format not in (1, 3):
        raise ValueError(f"Unsupported WAV format: {audio_format}")

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
            raise ValueError(f"Failed to read WAV: {path}: {exc}") from exc

    return sample_rate_hz, channels, _chunks()


def _clip_pcm16(value: float) -> float:
    if value > 0.999969:
        return 0.999969
    if value < -1.0:
        return -1.0
    return value


def _float_to_pcm16(value: float) -> int:
    return int(round(_clip_pcm16(value) * 32767.0))


def _pcm16_bytes(samples: list[float]) -> bytes:
    if not samples:
        return b""
    ints = [_float_to_pcm16(value) for value in samples]
    return struct.pack(f"<{len(ints)}h", *ints)


def _render_downmix_reference_stereo(
    *,
    source_audio_path: Path,
    out_path: Path,
    source_layout_id: str,
    downmix_policy_id: str | None,
    repo_root: Path | None = None,
) -> None:
    sample_rate_hz, source_channels, source_chunks = _iter_wav_float64_chunks(source_audio_path)
    matrix = resolve_downmix_matrix(
        repo_root=None,
        source_layout_id=source_layout_id,
        target_layout_id=_STEREO_LAYOUT_ID,
        policy_id=downmix_policy_id,
    )
    source_speakers = matrix.get("source_speakers")
    if not isinstance(source_speakers, list) or not source_speakers:
        raise TranslationReferenceResolutionError(
            f"Downmix matrix is missing source_speakers for {source_layout_id}."
        )
    if len(source_speakers) != source_channels:
        raise TranslationReferenceResolutionError(
            "Downmix matrix source channel count does not match source audio channels: "
            f"matrix={len(source_speakers)} source={source_channels}"
        )

    coeffs = matrix.get("coeffs")
    if not isinstance(coeffs, list):
        raise TranslationReferenceResolutionError("Downmix matrix is missing coeffs.")
    if len(coeffs) != 2:
        raise TranslationReferenceResolutionError("Downmix matrix target must be stereo (2 channels).")

    folded_chunks = iter_apply_matrix_to_chunks(
        coeffs,
        source_chunks,
        source_channels,
        target_channels=2,
        chunk_frames=_CHUNK_FRAMES,
    )

    tmp_path = out_path.parent / f"{out_path.name}.tmp"
    try:
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(tmp_path), "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate_hz)
            for chunk in folded_chunks:
                if not chunk:
                    continue
                total = len(chunk) - (len(chunk) % 2)
                if total <= 0:
                    continue
                handle.writeframes(_pcm16_bytes(chunk[:total]))
        tmp_path.replace(out_path)
    except Exception as exc:  # noqa: BLE001 - deterministic soft failure path
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise TranslationReferenceResolutionError(
            f"Failed to render downmix translation reference WAV: {out_path}: {exc}"
        ) from exc


def _source_channel_count(path: Path, fallback: int | None) -> int | None:
    try:
        metadata = read_wav_metadata(path)
    except ValueError:
        return fallback
    return _coerce_positive_int(metadata.get("channels")) or fallback


def resolve_translation_reference_audio(
    *,
    out_dir: Path,
    deliverables_index_path: Path,
    render_manifest_path: Path | None = None,
    prefer_target_ids: list[str] | None = None,
) -> tuple[Path, dict]:
    resolved_out_dir = out_dir.resolve()
    render_targets = _render_target_lookup()

    candidates: list[_AudioCandidate] = []
    collectors: list[Any] = [
        lambda: _collect_candidates_from_deliverables_index(
            out_dir=resolved_out_dir,
            deliverables_index_path=deliverables_index_path,
            render_targets=render_targets,
        ),
        lambda: _collect_candidates_from_variant_result(
            out_dir=resolved_out_dir,
            render_targets=render_targets,
        ),
    ]
    if isinstance(render_manifest_path, Path):
        collectors.append(
            lambda: _collect_candidates_from_render_manifest(
                out_dir=resolved_out_dir,
                render_manifest_path=render_manifest_path,
            )
        )

    for collector in collectors:
        try:
            candidates.extend(collector())
        except ValueError:
            continue

    deduped_candidates: list[_AudioCandidate] = []
    seen_candidates: set[tuple[str, str]] = set()
    for candidate in sorted(candidates, key=lambda item: (item.target_id, _candidate_sort_key(item))):
        key = (candidate.target_id, candidate.audio_path.as_posix())
        if key in seen_candidates:
            continue
        seen_candidates.add(key)
        deduped_candidates.append(candidate)

    if not deduped_candidates:
        raise TranslationReferenceResolutionError(
            "No suitable audio deliverable found for translation checks."
        )

    by_target_id: dict[str, list[_AudioCandidate]] = {}
    for candidate in deduped_candidates:
        by_target_id.setdefault(candidate.target_id, []).append(candidate)

    ordered_target_ids = _target_order(
        target_ids=set(by_target_id.keys()),
        prefer_target_ids=prefer_target_ids,
    )
    first_failure: str | None = None

    for target_id in ordered_target_ids:
        per_target_candidates = sorted(by_target_id.get(target_id, []), key=_candidate_sort_key)
        for candidate in per_target_candidates:
            source_channels = _source_channel_count(candidate.audio_path, candidate.channel_count)
            if source_channels is None or source_channels <= 0:
                if first_failure is None:
                    first_failure = (
                        "Audio candidate channel count is unavailable: "
                        f"{candidate.audio_path.as_posix()}"
                    )
                continue

            if source_channels <= 2:
                return (
                    candidate.audio_path.resolve(),
                    {
                        "source_target_id": target_id,
                        "method": "native_stereo",
                        "downmix_policy_id": None,
                        "source_channels": source_channels,
                    },
                )

            source_layout_id = (
                candidate.source_layout_id
                or _coerce_str(render_targets.get(target_id, {}).get("layout_id")).strip()
                or None
            )
            if source_layout_id is None:
                if first_failure is None:
                    first_failure = (
                        "Source layout is unavailable for multichannel translation reference: "
                        f"{target_id}"
                    )
                continue

            resolved_output_path = (
                resolved_out_dir
                / "translation_reference"
                / "translation_reference.stereo.wav"
            )
            try:
                _render_downmix_reference_stereo(
                    source_audio_path=candidate.audio_path,
                    out_path=resolved_output_path,
                    source_layout_id=source_layout_id,
                    downmix_policy_id=candidate.downmix_policy_id,
                    repo_root=None,
                )
            except TranslationReferenceResolutionError as exc:
                if first_failure is None:
                    first_failure = str(exc)
                continue

            return (
                resolved_output_path.resolve(),
                {
                    "source_target_id": target_id,
                    "method": "downmix_fallback",
                    "downmix_policy_id": candidate.downmix_policy_id,
                    "source_channels": source_channels,
                },
            )

    if first_failure:
        raise TranslationReferenceResolutionError(
            "No suitable audio deliverable found for translation checks. "
            f"{first_failure}"
        )
    raise TranslationReferenceResolutionError(
        "No suitable audio deliverable found for translation checks."
    )
