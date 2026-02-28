"""Deterministic helpers for the first-class binaural render target."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from mmo.core.pipeline import (
    _apply_output_formats_to_manifest,
    _merge_skipped_entries,
    _normalize_output_formats,
)
from mmo.core.registries.layout_registry import load_layout_registry
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.plugins.subjective.binaural_preview_v0 import build_headphone_preview_manifest

BINAURAL_LAYOUT_ID = "LAYOUT.BINAURAL"
_SOURCE_LAYOUT_HEIGHT = "LAYOUT.7_1_4"
_SOURCE_LAYOUT_SURROUND = "LAYOUT.5_1"
_SOURCE_LAYOUT_STEREO = "LAYOUT.2_0"


@dataclass(frozen=True)
class BinauralSourceSelection:
    source_layout_id: str
    reason: str


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def is_binaural_layout(layout_id: str | None) -> bool:
    return _coerce_str(layout_id).strip() == BINAURAL_LAYOUT_ID


def _layout_info(layout_id: str) -> dict[str, Any] | None:
    clean_layout_id = _coerce_str(layout_id).strip()
    if not clean_layout_id:
        return None
    try:
        return load_layout_registry().get_layout(clean_layout_id)
    except ValueError:
        return None


def _layout_has_heights(layout_id: str) -> bool:
    info = _layout_info(layout_id)
    if not isinstance(info, dict):
        return False

    height_speakers = info.get("height_speakers")
    if isinstance(height_speakers, list):
        if any(isinstance(item, str) and item.strip() for item in height_speakers):
            return True

    channel_order = info.get("channel_order")
    if isinstance(channel_order, list):
        return any(
            isinstance(item, str)
            and item.strip().startswith("SPK.T")
            for item in channel_order
        )
    return False


def _layout_is_surroundish(layout_id: str) -> bool:
    info = _layout_info(layout_id)
    if not isinstance(info, dict):
        return False
    channel_count = _coerce_int(info.get("channel_count")) or 0
    if channel_count > 2:
        return True
    family = _coerce_str(info.get("family")).strip().lower()
    return family in {"surround", "immersive"}


def _iter_channel_counts(
    *,
    report: Mapping[str, Any] | None,
    scene: Mapping[str, Any] | None,
) -> list[int]:
    counts: list[int] = []

    report_session = report.get("session") if isinstance(report, Mapping) else None
    if isinstance(report_session, Mapping):
        stems = report_session.get("stems")
        if isinstance(stems, list):
            for stem in stems:
                if not isinstance(stem, Mapping):
                    continue
                count = _coerce_int(stem.get("channel_count"))
                if isinstance(count, int) and count > 0:
                    counts.append(count)

    scene_source = scene.get("source") if isinstance(scene, Mapping) else None
    if isinstance(scene_source, Mapping):
        scene_stems = scene_source.get("stems")
        if isinstance(scene_stems, list):
            for stem in scene_stems:
                if not isinstance(stem, Mapping):
                    continue
                count = _coerce_int(stem.get("channel_count"))
                if isinstance(count, int) and count > 0:
                    counts.append(count)

    for collection_key in ("objects", "beds"):
        rows = scene.get(collection_key) if isinstance(scene, Mapping) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            count = _coerce_int(row.get("channel_count"))
            if isinstance(count, int) and count > 0:
                counts.append(count)

    return sorted(counts)


def _source_layout_candidates(
    *,
    source_layout_id_hint: str | None,
    report: Mapping[str, Any] | None,
    scene: Mapping[str, Any] | None,
) -> list[str]:
    candidates: list[str] = []

    def _append(value: Any) -> None:
        candidate = _coerce_str(value).strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    _append(source_layout_id_hint)

    if isinstance(report, Mapping):
        report_session = report.get("session")
        if isinstance(report_session, Mapping):
            _append(report_session.get("source_layout_id"))

        report_run_config = report.get("run_config")
        if isinstance(report_run_config, Mapping):
            _append(report_run_config.get("source_layout_id"))
            downmix_cfg = report_run_config.get("downmix")
            if isinstance(downmix_cfg, Mapping):
                _append(downmix_cfg.get("source_layout_id"))

        _append(report.get("source_layout_id"))

    if isinstance(scene, Mapping):
        scene_source = scene.get("source")
        if isinstance(scene_source, Mapping):
            _append(scene_source.get("layout_id"))

        scene_metadata = scene.get("metadata")
        if isinstance(scene_metadata, Mapping):
            _append(scene_metadata.get("source_layout_id"))

        scene_run_config = scene.get("run_config")
        if isinstance(scene_run_config, Mapping):
            _append(scene_run_config.get("source_layout_id"))
            downmix_cfg = scene_run_config.get("downmix")
            if isinstance(downmix_cfg, Mapping):
                _append(downmix_cfg.get("source_layout_id"))

    return candidates


def _scene_mentions_heights(*, report: Mapping[str, Any] | None, scene: Mapping[str, Any] | None) -> bool:
    for layout_id in _source_layout_candidates(
        source_layout_id_hint=None,
        report=report,
        scene=scene,
    ):
        if _layout_has_heights(layout_id):
            return True

    if isinstance(scene, Mapping):
        routing_intent = scene.get("routing_intent")
        if isinstance(routing_intent, Mapping):
            layout_class = _coerce_str(routing_intent.get("suggested_layout_class")).strip().lower()
            if layout_class == "immersive":
                return True
            notes = routing_intent.get("notes")
            if isinstance(notes, list):
                if any(
                    isinstance(note, str) and "height" in note.strip().lower()
                    for note in notes
                ):
                    return True

        for collection_key in ("objects", "beds"):
            rows = scene.get(collection_key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                notes = row.get("notes")
                if not isinstance(notes, list):
                    continue
                if any(
                    isinstance(note, str) and "height" in note.strip().lower()
                    for note in notes
                ):
                    return True

    for channel_count in _iter_channel_counts(report=report, scene=scene):
        if channel_count >= 10:
            return True
    return False


def _scene_mentions_surround(*, report: Mapping[str, Any] | None, scene: Mapping[str, Any] | None) -> bool:
    for layout_id in _source_layout_candidates(
        source_layout_id_hint=None,
        report=report,
        scene=scene,
    ):
        if _layout_is_surroundish(layout_id):
            return True

    if isinstance(scene, Mapping):
        routing_intent = scene.get("routing_intent")
        if isinstance(routing_intent, Mapping):
            layout_class = _coerce_str(routing_intent.get("suggested_layout_class")).strip().lower()
            if layout_class in {"surround", "immersive"}:
                return True

    for channel_count in _iter_channel_counts(report=report, scene=scene):
        if channel_count > 2:
            return True
    return False


def choose_binaural_source_layout(
    *,
    report: Mapping[str, Any] | None = None,
    scene: Mapping[str, Any] | None = None,
    source_layout_id_hint: str | None = None,
) -> BinauralSourceSelection:
    if _layout_has_heights(_coerce_str(source_layout_id_hint).strip()):
        return BinauralSourceSelection(
            source_layout_id=_SOURCE_LAYOUT_HEIGHT,
            reason="source_layout_has_heights",
        )

    if _scene_mentions_heights(report=report, scene=scene):
        return BinauralSourceSelection(
            source_layout_id=_SOURCE_LAYOUT_HEIGHT,
            reason="scene_mentions_heights",
        )

    if _layout_is_surroundish(_coerce_str(source_layout_id_hint).strip()):
        return BinauralSourceSelection(
            source_layout_id=_SOURCE_LAYOUT_SURROUND,
            reason="source_layout_is_surround",
        )

    if _scene_mentions_surround(report=report, scene=scene):
        return BinauralSourceSelection(
            source_layout_id=_SOURCE_LAYOUT_SURROUND,
            reason="scene_mentions_surround",
        )

    return BinauralSourceSelection(
        source_layout_id=_SOURCE_LAYOUT_STEREO,
        reason="fallback_stereo",
    )


def _with_source_layout_hint(
    *,
    renderer_manifests: list[dict[str, Any]],
    source_layout_id: str,
) -> list[dict[str, Any]]:
    normalized_source_layout_id = _coerce_str(source_layout_id).strip()
    cloned_manifests: list[dict[str, Any]] = []
    for manifest in renderer_manifests:
        if not isinstance(manifest, dict):
            continue
        manifest_copy = dict(manifest)
        outputs = manifest.get("outputs")
        if isinstance(outputs, list):
            manifest_outputs: list[dict[str, Any]] = []
            for output in outputs:
                if not isinstance(output, dict):
                    continue
                output_copy = dict(output)
                existing_layout_id = _coerce_str(output_copy.get("layout_id")).strip()
                metadata = output_copy.get("metadata")
                metadata_copy: dict[str, Any] = (
                    dict(metadata)
                    if isinstance(metadata, Mapping)
                    else {}
                )
                if normalized_source_layout_id:
                    if existing_layout_id and existing_layout_id != normalized_source_layout_id:
                        metadata_copy.setdefault("binaural_original_layout_id", existing_layout_id)
                    output_copy["layout_id"] = normalized_source_layout_id
                    metadata_copy["source_layout_id"] = normalized_source_layout_id
                output_copy["metadata"] = metadata_copy
                manifest_outputs.append(output_copy)
            manifest_copy["outputs"] = manifest_outputs
        cloned_manifests.append(manifest_copy)
    return cloned_manifests


def build_binaural_target_manifests(
    *,
    renderer_manifests: list[dict[str, Any]],
    output_dir: Path | None,
    layout_standard: str,
    source_layout_id: str,
    output_formats: Sequence[str] | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    hinted_manifests = _with_source_layout_hint(
        renderer_manifests=renderer_manifests,
        source_layout_id=source_layout_id,
    )
    preview_manifest = build_headphone_preview_manifest(
        renderer_manifests=hinted_manifests,
        output_dir=output_dir,
        layout_standard=layout_standard,
    )

    preview_note = (
        "Binaural virtualization deliverable (conservative ILD/ITD + gating); "
        f"source_layout_id={source_layout_id}."
    )
    existing_note = _coerce_str(preview_manifest.get("notes")).strip()
    preview_manifest["notes"] = (
        f"{existing_note} {preview_note}".strip()
        if existing_note
        else preview_note
    )

    preview_outputs: list[dict[str, Any]] = []
    for output in preview_manifest.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        output_copy = dict(output)
        output_copy["layout_id"] = BINAURAL_LAYOUT_ID
        output_note = _coerce_str(output_copy.get("notes")).strip()
        output_copy["notes"] = (
            f"{output_note} Binaural virtualization deliverable."
            if output_note
            else "Binaural virtualization deliverable."
        )
        metadata = output_copy.get("metadata")
        metadata_copy: dict[str, Any] = dict(metadata) if isinstance(metadata, Mapping) else {}
        metadata_copy["binaural_virtualization"] = True
        metadata_copy["binaural_source_layout_id"] = source_layout_id
        metadata_copy["binaural_requested_layout_id"] = BINAURAL_LAYOUT_ID
        output_copy["metadata"] = metadata_copy
        preview_outputs.append(output_copy)
    preview_manifest["outputs"] = preview_outputs

    desired_formats = _normalize_output_formats(output_formats)
    ffmpeg_cmd = resolve_ffmpeg_cmd() if any(fmt != "wav" for fmt in desired_formats) else None
    transcode_skipped = _apply_output_formats_to_manifest(
        preview_manifest,
        output_dir=output_dir,
        desired_formats=desired_formats,
        ffmpeg_cmd=ffmpeg_cmd,
    )
    preview_manifest["skipped"] = _merge_skipped_entries(
        preview_manifest.get("skipped", []),
        transcode_skipped,
    )

    outputs_count = len(
        [
            row
            for row in preview_manifest.get("outputs", [])
            if isinstance(row, dict)
        ]
    )
    skipped_count = len(
        [
            row
            for row in preview_manifest.get("skipped", [])
            if isinstance(row, dict)
        ]
    )
    return [preview_manifest], {"outputs": outputs_count, "skipped": skipped_count}


__all__ = [
    "BINAURAL_LAYOUT_ID",
    "BinauralSourceSelection",
    "build_binaural_target_manifests",
    "choose_binaural_source_layout",
    "is_binaural_layout",
]
