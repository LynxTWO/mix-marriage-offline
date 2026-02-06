from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

_UNKNOWN_LAYOUT_ID = "LAYOUT.UNKNOWN"


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


def _output_sort_key(output: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        _coerce_str(output.get("format")).strip().lower(),
        _coerce_str(output.get("file_path")).strip(),
        _coerce_str(output.get("output_id")).strip(),
    )


def _group_target_layout_id(output: Dict[str, Any]) -> str:
    metadata = output.get("metadata")
    if not isinstance(metadata, dict):
        return _UNKNOWN_LAYOUT_ID
    if metadata.get("routing_applied") is not True:
        return _UNKNOWN_LAYOUT_ID
    target_layout_id = _coerce_str(metadata.get("target_layout_id")).strip()
    if target_layout_id:
        return target_layout_id
    return _UNKNOWN_LAYOUT_ID


def _group_channel_count(output: Dict[str, Any]) -> int | None:
    channel_count = _coerce_int(output.get("channel_count"))
    if channel_count is None or channel_count < 1:
        return None
    return channel_count


def _group_sort_key(group_key: Tuple[str, int | None]) -> tuple[str, int]:
    layout_id, channel_count = group_key
    channel_sort = channel_count if channel_count is not None else 2**31 - 1
    return (layout_id, channel_sort)


def _deliverable_base_id(layout_id: str, channel_count: int | None) -> str:
    layout_token = layout_id if layout_id != _UNKNOWN_LAYOUT_ID else "UNKNOWN"
    channel_token = f"{channel_count}CH" if channel_count is not None else "UNKNOWNCH"
    return f"DELIV.{layout_token}.{channel_token}"


def collect_outputs_from_renderer_manifests(
    renderer_manifests: Sequence[dict[str, Any]],
) -> List[Dict[str, Any]]:
    outputs: List[Dict[str, Any]] = []
    for manifest in renderer_manifests:
        if not isinstance(manifest, dict):
            continue
        manifest_outputs = manifest.get("outputs")
        if not isinstance(manifest_outputs, list):
            continue
        for output in manifest_outputs:
            if isinstance(output, dict):
                outputs.append(output)
    outputs.sort(key=_output_sort_key)
    return outputs


def build_deliverables_from_outputs(outputs: Sequence[dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, int | None], List[Dict[str, Any]]] = {}
    for output in outputs:
        if not isinstance(output, dict):
            continue
        key = (_group_target_layout_id(output), _group_channel_count(output))
        grouped.setdefault(key, []).append(output)

    provisional: List[Tuple[str, Dict[str, Any]]] = []
    for group_key in sorted(grouped, key=_group_sort_key):
        layout_id, channel_count = group_key
        group_outputs = sorted(grouped[group_key], key=_output_sort_key)

        output_ids = [
            output_id
            for output in group_outputs
            for output_id in [_coerce_str(output.get("output_id")).strip()]
            if output_id
        ]
        if not output_ids:
            continue

        formats = sorted(
            {
                output_format
                for output in group_outputs
                for output_format in [_coerce_str(output.get("format")).strip().lower()]
                if output_format
            }
        )

        deliverable: Dict[str, Any] = {
            "label": (
                f"{layout_id} deliverable"
                if layout_id != _UNKNOWN_LAYOUT_ID
                else "Deliverable"
            ),
            "output_ids": output_ids,
        }
        if layout_id != _UNKNOWN_LAYOUT_ID:
            deliverable["target_layout_id"] = layout_id
        if channel_count is not None:
            deliverable["channel_count"] = channel_count
        if formats:
            deliverable["formats"] = formats

        provisional.append((_deliverable_base_id(layout_id, channel_count), deliverable))

    deliverables: List[Dict[str, Any]] = []
    used_ids: Dict[str, int] = {}
    for base_id, deliverable in provisional:
        count = used_ids.get(base_id, 0) + 1
        used_ids[base_id] = count
        if count == 1:
            deliverable["deliverable_id"] = base_id
        else:
            deliverable["deliverable_id"] = f"{base_id}.{count}"
        deliverables.append(deliverable)

    deliverables.sort(key=lambda item: _coerce_str(item.get("deliverable_id")))
    return deliverables
