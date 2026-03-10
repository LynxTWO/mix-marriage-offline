"""Manifest-driven multichannel plugin-mode runner for semantic regression tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from mmo.dsp.process_context import ProcessContext

_SURROUND_GROUP_NAME = "surrounds"
_HEIGHT_GROUP_NAME = "heights"


class PluginModeRunError(ValueError):
    """Raised when a plugin fixture manifest or invocation is invalid."""


@dataclass(frozen=True)
class PluginModeRunResult:
    """Rendered matrix plus deterministic evidence for one plugin invocation."""

    rendered: np.ndarray
    evidence: dict[str, Any]


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _manifest_capabilities(plugin_entry: Any) -> dict[str, Any]:
    manifest = getattr(plugin_entry, "manifest", None)
    if not isinstance(manifest, dict):
        return {}
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, dict):
        return {}
    return capabilities


def _require_matrix_shape(buf: Any, process_ctx: ProcessContext) -> np.ndarray:
    matrix = np.asarray(buf)
    if matrix.ndim != 2:
        raise PluginModeRunError(
            f"Expected 2-D multichannel buffer, got shape {matrix.shape!r}.",
        )
    if matrix.shape[0] != process_ctx.num_channels:
        raise PluginModeRunError(
            "Buffer channel count does not match ProcessContext: "
            f"{matrix.shape[0]} != {process_ctx.num_channels}",
        )
    return np.array(matrix, copy=True)


def _group_indices(process_ctx: ProcessContext, group_name: str) -> list[int]:
    normalized = group_name.strip().lower()
    if normalized == "front":
        return process_ctx.group_indices("front")
    if normalized == _SURROUND_GROUP_NAME:
        indices = process_ctx.group_indices("surround") + process_ctx.group_indices("rear")
        return sorted(set(indices))
    if normalized == _HEIGHT_GROUP_NAME:
        return process_ctx.group_indices("height")
    if normalized == "all":
        return list(range(process_ctx.num_channels))
    raise PluginModeRunError(f"Unsupported link group: {group_name!r}")


def _base_evidence(plugin_entry: Any, process_ctx: ProcessContext, channel_mode: str) -> dict[str, Any]:
    return {
        "plugin_id": _coerce_str(getattr(plugin_entry, "plugin_id", "")),
        "channel_mode": channel_mode,
        "layout_id": process_ctx.layout_id,
        "layout_standard": process_ctx.layout_standard,
        "channel_order": list(process_ctx.channel_order),
        "seed": process_ctx.seed,
    }


def _validate_capabilities(capabilities: Mapping[str, Any], process_ctx: ProcessContext) -> None:
    max_channels = capabilities.get("max_channels")
    if isinstance(max_channels, int) and process_ctx.num_channels > max_channels:
        raise PluginModeRunError(
            "ProcessContext exceeds plugin max_channels: "
            f"{process_ctx.num_channels} > {max_channels}",
        )
    seed_policy = _coerce_str(capabilities.get("deterministic_seed_policy"))
    if seed_policy == "seed_required" and not isinstance(process_ctx.seed, int):
        raise PluginModeRunError("Plugin requires deterministic seed in ProcessContext.")


def run_plugin_mode(
    plugin_entry: Any,
    buf: Any,
    process_ctx: ProcessContext,
    *,
    params: Mapping[str, Any] | None = None,
    sample_rate_hz: int | None = None,
) -> PluginModeRunResult:
    """Run one plugin fixture according to its manifest-declared channel_mode."""

    capabilities = _manifest_capabilities(plugin_entry)
    channel_mode = _coerce_str(capabilities.get("channel_mode")) or "per_channel"
    sample_rate = sample_rate_hz or process_ctx.sample_rate_hz
    runtime_params = dict(params or {})
    working = _require_matrix_shape(buf, process_ctx)

    _validate_capabilities(capabilities, process_ctx)

    if channel_mode == "per_channel":
        return _run_per_channel(
            plugin_entry,
            working,
            process_ctx,
            params=runtime_params,
            sample_rate_hz=sample_rate,
        )
    if channel_mode == "linked_group":
        return _run_linked_group(
            plugin_entry,
            working,
            process_ctx,
            params=runtime_params,
            sample_rate_hz=sample_rate,
            capabilities=capabilities,
        )
    if channel_mode == "true_multichannel":
        return _run_true_multichannel(
            plugin_entry,
            working,
            process_ctx,
            params=runtime_params,
            sample_rate_hz=sample_rate,
        )
    raise PluginModeRunError(f"Unsupported channel_mode: {channel_mode!r}")


def _run_per_channel(
    plugin_entry: Any,
    working: np.ndarray,
    process_ctx: ProcessContext,
    *,
    params: dict[str, Any],
    sample_rate_hz: int,
) -> PluginModeRunResult:
    processor = getattr(plugin_entry.instance, "process_channel", None)
    if not callable(processor):
        raise PluginModeRunError("per_channel plugin fixture must implement process_channel().")

    call_rows: list[dict[str, Any]] = []
    touched_channel_ids: list[str] = []
    for index, spk_id in enumerate(process_ctx.channel_order):
        rendered_channel, row_evidence = processor(
            working[index].copy(),
            sample_rate_hz,
            dict(params),
            spk_id=spk_id,
            process_ctx=process_ctx,
        )
        working[index] = np.asarray(rendered_channel)
        evidence_row = dict(row_evidence) if isinstance(row_evidence, Mapping) else {}
        evidence_row.setdefault("channel_id", spk_id)
        evidence_row.setdefault("channel_index", index)
        call_rows.append(evidence_row)
        if bool(evidence_row.get("touched")):
            channel_ids = _coerce_str_list(evidence_row.get("channel_ids"))
            if not channel_ids:
                channel_ids = [spk_id]
            touched_channel_ids.extend(channel_ids)

    evidence = _base_evidence(plugin_entry, process_ctx, "per_channel")
    evidence["channel_call_count"] = len(call_rows)
    evidence["channel_ids_touched"] = sorted(set(touched_channel_ids))
    evidence["per_channel_calls"] = call_rows
    return PluginModeRunResult(rendered=working, evidence=evidence)


def _run_linked_group(
    plugin_entry: Any,
    working: np.ndarray,
    process_ctx: ProcessContext,
    *,
    params: dict[str, Any],
    sample_rate_hz: int,
    capabilities: Mapping[str, Any],
) -> PluginModeRunResult:
    processor = getattr(plugin_entry.instance, "process_linked_group", None)
    if not callable(processor):
        raise PluginModeRunError(
            "linked_group plugin fixture must implement process_linked_group().",
        )

    group_name = _coerce_str(params.get("group_name")).lower()
    if not group_name:
        raise PluginModeRunError("linked_group plugin requires params.group_name.")
    supported_groups = _coerce_str_list(capabilities.get("link_groups"))
    if supported_groups and group_name not in supported_groups:
        raise PluginModeRunError(
            f"group_name {group_name!r} is not declared in manifest link_groups.",
        )

    indices = _group_indices(process_ctx, group_name)
    channel_ids = [process_ctx.channel_order[index] for index in indices]
    rendered_group, group_evidence = processor(
        working[indices].copy(),
        sample_rate_hz,
        dict(params),
        group_name=group_name,
        channel_ids=tuple(channel_ids),
        process_ctx=process_ctx,
    )
    working[indices] = np.asarray(rendered_group)

    evidence = _base_evidence(plugin_entry, process_ctx, "linked_group")
    evidence["group_name"] = group_name
    evidence["channel_ids"] = channel_ids
    if isinstance(group_evidence, Mapping):
        evidence.update(dict(group_evidence))
        evidence["group_name"] = group_name
        evidence["channel_ids"] = channel_ids
    return PluginModeRunResult(rendered=working, evidence=evidence)


def _run_true_multichannel(
    plugin_entry: Any,
    working: np.ndarray,
    process_ctx: ProcessContext,
    *,
    params: dict[str, Any],
    sample_rate_hz: int,
) -> PluginModeRunResult:
    processor = getattr(plugin_entry.instance, "process_true_multichannel", None)
    if not callable(processor):
        raise PluginModeRunError(
            "true_multichannel plugin fixture must implement process_true_multichannel().",
        )

    rendered_matrix, plugin_evidence = processor(
        working.copy(),
        sample_rate_hz,
        dict(params),
        process_ctx=process_ctx,
    )
    evidence = _base_evidence(plugin_entry, process_ctx, "true_multichannel")
    if isinstance(plugin_evidence, Mapping):
        evidence.update(dict(plugin_evidence))
    evidence.setdefault("channel_ids_seen", list(process_ctx.channel_order))
    return PluginModeRunResult(rendered=np.asarray(rendered_matrix), evidence=evidence)
