"""Deterministic DSP hook pipeline with strict bounded-authority enforcement.

This module implements the bus-aware processing hook scaffold for PR8:

1. ``pre_bus_stem`` stage (per-stem hook point)
2. ``bus`` stage (group/bus hook point)
3. ``post_master`` stage (single master hook point)

The hooks are planning stubs: they emit explainable actions/events
(``what``/``why``/``where``/``confidence``) and enforce authority bounds,
but do not perform creative tonal processing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from mmo.resources import schemas_dir

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None


STAGE_PRE_BUS_STEM = "pre_bus_stem"
STAGE_BUS = "bus"
STAGE_POST_MASTER = "post_master"
STAGE_ORDER: tuple[str, ...] = (
    STAGE_PRE_BUS_STEM,
    STAGE_BUS,
    STAGE_POST_MASTER,
)

_DEFAULT_ROLE_ID = "ROLE.OTHER.UNKNOWN"
_DEFAULT_BUS_ID = "BUS.OTHER"
_MASTER_BUS_ID = "BUS.MASTER"

_BUS_GROUP_ORDER: tuple[str, ...] = (
    "DRUMS",
    "BASS",
    "MUSIC",
    "VOX",
    "FX",
    "OTHER",
)
_BUS_GROUP_RANK: dict[str, int] = {
    group_id: index for index, group_id in enumerate(_BUS_GROUP_ORDER)
}

_SCHEMA_CACHE: dict[str, Any] | None = None


@dataclass(frozen=True)
class DspStemSpec:
    """Per-stem hook metadata used by the DSP stub pipeline."""

    stem_id: str
    role_id: str = _DEFAULT_ROLE_ID
    bus_id: str = _DEFAULT_BUS_ID
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DspTargetContext:
    """Normalized context delivered to DSP hook plugins."""

    stage_scope: str
    target_scope: str
    target_id: str
    role_id: str | None
    bus_id: str | None
    stem_ids: tuple[str, ...]
    layout_id: str
    standard: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DspPluginDecision:
    """Plugin decision payload for one target context."""

    applied: bool
    action_id: str | None
    params: dict[str, float]
    what: str
    why: str
    where: tuple[str, ...]
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DspHookPlugin(Protocol):
    """Protocol for deterministic DSP hook plugins."""

    plugin_id: str
    manifest: dict[str, Any]

    def decide(self, context: DspTargetContext) -> DspPluginDecision | None:
        """Return a deterministic decision for this context."""


class ConservativeHpfRumblePlugin:
    """Low-risk pre-bus HPF planner with evidence gating.

    Applies only to non-bass roles when rumble evidence confidence meets a
    conservative threshold. Produces plan actions only; no audio is mutated.
    """

    plugin_id = "DSP.PLUGIN.HPF_RUMBLE_GUARD_V0"
    manifest: dict[str, Any] = {
        "schema_version": "0.1.0",
        "plugin_id": plugin_id,
        "name": "Conservative HPF Rumble Guard",
        "version": "0.1.0",
        "description": (
            "Low-risk high-pass planning for non-bass stems when rumble evidence "
            "is high."
        ),
        "stage_scope": STAGE_PRE_BUS_STEM,
        "authority": {
            "impact_level": "low_risk",
            "requires_evidence": True,
            "allow_on_bass_roles": False,
            "notes": [
                "Conservative cutoff only (20-45 Hz).",
                "No automatic application on bass-designated roles.",
            ],
        },
        "evidence_contract": {
            "metric_key": "rumble_confidence",
            "min_confidence": 0.85,
            "reason": "Rumble evidence must exceed conservative confidence floor.",
        },
        "action": {
            "action_id": "ACTION.DSP.HPF.STEM",
            "parameter_bounds": {
                "cutoff_hz": {"min": 20.0, "max": 45.0},
                "slope_db_per_oct": {"min": 12.0, "max": 18.0},
            },
        },
    }

    def decide(self, context: DspTargetContext) -> DspPluginDecision | None:
        if context.stage_scope != STAGE_PRE_BUS_STEM:
            return None

        role_id = _coerce_str(context.role_id).strip() or _DEFAULT_ROLE_ID
        bus_id = _coerce_str(context.bus_id).strip() or _DEFAULT_BUS_ID
        where = (context.target_id, role_id, bus_id)
        channel_metrics = _channel_metrics(context.evidence)

        if _is_bass_role(role_id):
            return DspPluginDecision(
                applied=False,
                action_id=None,
                params={},
                what="conservative HPF skipped",
                why=(
                    "Guardrail skip: bass-designated roles are excluded from "
                    "automatic HPF planning."
                ),
                where=where,
                confidence=1.0,
                evidence={
                    "codes": ["DSP.HPF_RUMBLE.GUARDRAIL.BASS_ROLE"],
                    "metrics": [
                        {"name": "bass_role", "value": 1.0},
                        *channel_metrics,
                    ],
                },
            )

        rumble_confidence = _rumble_confidence(context.evidence)
        threshold = _coerce_float(
            _coerce_dict(self.manifest.get("evidence_contract")).get("min_confidence")
        )
        if threshold is None:
            threshold = 0.85

        if rumble_confidence < threshold:
            return DspPluginDecision(
                applied=False,
                action_id=None,
                params={},
                what="conservative HPF skipped",
                why=(
                    "Evidence gate not met: rumble confidence is below the "
                    f"required threshold ({threshold:.2f})."
                ),
                where=where,
                confidence=round(rumble_confidence, 3),
                evidence={
                    "codes": ["DSP.HPF_RUMBLE.EVIDENCE_BELOW_THRESHOLD"],
                    "metrics": [
                        {"name": "rumble_confidence", "value": rumble_confidence},
                        {"name": "required_confidence", "value": threshold},
                        *channel_metrics,
                    ],
                },
            )

        # Conservative authority envelope: 25-40 Hz cutoff, fixed 12 dB/oct slope.
        strength = 0.0
        if threshold < 1.0:
            strength = (rumble_confidence - threshold) / (1.0 - threshold)
        strength = max(0.0, min(1.0, strength))
        cutoff_hz = round(25.0 + (15.0 * strength), 1)

        return DspPluginDecision(
            applied=True,
            action_id="ACTION.DSP.HPF.STEM",
            params={
                "cutoff_hz": cutoff_hz,
                "slope_db_per_oct": 12.0,
            },
            what="conservative HPF planned",
            why=(
                "Non-bass stem has high-confidence rumble evidence; planned low-risk "
                "subsonic attenuation only."
            ),
            where=where,
            confidence=round(rumble_confidence, 3),
            evidence={
                "codes": ["DSP.HPF_RUMBLE.ACTION_PLANNED"],
                "metrics": [
                    {"name": "rumble_confidence", "value": rumble_confidence},
                    {"name": "cutoff_hz", "value": cutoff_hz},
                    {"name": "slope_db_per_oct", "value": 12.0},
                    *channel_metrics,
                ],
            },
        )


def default_dsp_hook_plugins() -> tuple[DspHookPlugin, ...]:
    """Return deterministic default DSP hook plugin ordering."""

    return (ConservativeHpfRumblePlugin(),)


def normalize_dsp_stem_specs(raw_value: Any) -> list[DspStemSpec]:
    """Normalize ``options.dsp_stems`` into deterministic stem specs."""

    if not isinstance(raw_value, list):
        return []

    rows: list[DspStemSpec] = []
    for item in raw_value:
        if not isinstance(item, dict):
            continue
        stem_id = _coerce_str(item.get("stem_id")).strip()
        if not stem_id:
            continue

        role_id = _coerce_str(item.get("role_id")).strip() or _DEFAULT_ROLE_ID
        raw_bus_id = _coerce_str(item.get("bus_id")).strip()
        bus_id = _normalize_bus_id(raw_bus_id, role_id=role_id)
        evidence = _normalize_evidence(item.get("evidence"))
        rows.append(
            DspStemSpec(
                stem_id=stem_id,
                role_id=role_id,
                bus_id=bus_id,
                evidence=evidence,
            )
        )

    rows.sort(key=lambda row: row.stem_id)
    deduped: list[DspStemSpec] = []
    seen_stem_ids: set[str] = set()
    for row in rows:
        if row.stem_id in seen_stem_ids:
            continue
        seen_stem_ids.add(row.stem_id)
        deduped.append(row)
    return deduped


def validate_dsp_plugin_manifest(
    manifest: dict[str, Any],
    *,
    schema_path: Path | None = None,
) -> list[str]:
    """Validate a DSP hook plugin manifest with stable error ordering."""

    if not isinstance(manifest, dict):
        return ["[schema] $: manifest must be an object."]

    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate DSP plugin manifests.")

    if schema_path is None:
        schema_path = schemas_dir() / "plugin_manifest.json"

    schema = _load_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(manifest),
        key=lambda err: list(err.path),
    )

    messages: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        messages.append(f"[schema] {path}: {err.message}")

    bounds = _coerce_dict(_coerce_dict(manifest.get("action")).get("parameter_bounds"))
    for param_name in sorted(bounds):
        bound_row = _coerce_dict(bounds.get(param_name))
        minimum = _coerce_float(bound_row.get("min"))
        maximum = _coerce_float(bound_row.get("max"))
        if minimum is None or maximum is None:
            continue
        if minimum > maximum:
            messages.append(
                (
                    "[semantics] action.parameter_bounds."
                    f"{param_name}: min must be <= max."
                )
            )

    return messages


def run_dsp_pipeline_hooks(
    *,
    stem_results: list[Any],
    stem_specs: list[DspStemSpec] | None = None,
    enable_bus_stage: bool = False,
    enable_post_master_stage: bool = False,
    plugins: list[DspHookPlugin] | None = None,
) -> dict[str, Any]:
    """Run deterministic DSP hook stages and return explainable receipt."""

    if not isinstance(stem_results, list):
        stem_results = []

    active_plugins = list(plugins) if plugins is not None else list(default_dsp_hook_plugins())
    active_plugins.sort(key=lambda plugin: _coerce_str(getattr(plugin, "plugin_id", "")))
    _validate_plugins_or_raise(active_plugins)

    plugin_by_stage: dict[str, list[DspHookPlugin]] = {
        stage_scope: [] for stage_scope in STAGE_ORDER
    }
    for plugin in active_plugins:
        stage_scope = _coerce_str(_coerce_dict(plugin.manifest).get("stage_scope")).strip()
        if stage_scope in plugin_by_stage:
            plugin_by_stage[stage_scope].append(plugin)

    stem_rows = _build_effective_stem_rows(stem_results=stem_results, stem_specs=stem_specs)
    layout_id = (
        _coerce_str(stem_rows[0]["layout_id"]).strip() if stem_rows else "LAYOUT.2_0"
    )
    standard = _coerce_str(stem_rows[0]["standard"]).strip() if stem_rows else "SMPTE"

    actions: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    stage_counters: dict[str, dict[str, int]] = {
        stage_scope: {"target_count": 0, "decision_count": 0, "action_count": 0}
        for stage_scope in STAGE_ORDER
    }

    pre_targets = [
        DspTargetContext(
            stage_scope=STAGE_PRE_BUS_STEM,
            target_scope="stem",
            target_id=_coerce_str(row.get("stem_id")).strip(),
            role_id=_coerce_str(row.get("role_id")).strip() or _DEFAULT_ROLE_ID,
            bus_id=_coerce_str(row.get("bus_id")).strip() or _DEFAULT_BUS_ID,
            stem_ids=(_coerce_str(row.get("stem_id")).strip(),),
            layout_id=_coerce_str(row.get("layout_id")).strip() or layout_id,
            standard=_coerce_str(row.get("standard")).strip() or standard,
            evidence=_normalize_evidence(row.get("evidence")),
        )
        for row in stem_rows
        if _coerce_str(row.get("stem_id")).strip()
    ]

    _emit_stage_start(
        events,
        stage_scope=STAGE_PRE_BUS_STEM,
        target_count=len(pre_targets),
    )
    pre_decisions, pre_actions = _run_stage_plugins(
        stage_scope=STAGE_PRE_BUS_STEM,
        targets=pre_targets,
        stage_plugins=plugin_by_stage[STAGE_PRE_BUS_STEM],
    )
    events.extend(pre_decisions)
    actions.extend(pre_actions)
    stage_counters[STAGE_PRE_BUS_STEM] = {
        "target_count": len(pre_targets),
        "decision_count": len(pre_decisions),
        "action_count": len(pre_actions),
    }
    _emit_stage_complete(
        events,
        stage_scope=STAGE_PRE_BUS_STEM,
        counters=stage_counters[STAGE_PRE_BUS_STEM],
    )

    bus_targets = _build_bus_targets(stem_rows, layout_id=layout_id, standard=standard)
    _emit_stage_start(
        events,
        stage_scope=STAGE_BUS,
        target_count=len(bus_targets),
    )
    if not enable_bus_stage:
        events.append(
            _event_dict(
                stage_scope=STAGE_BUS,
                plugin_id="DSP.PIPELINE",
                what="bus DSP stage skipped",
                why="Guardrail: bus-stage DSP is disabled unless explicitly enabled.",
                where=[target.target_id for target in bus_targets] or ["(none)"],
                confidence=1.0,
                evidence={"codes": ["DSP.PIPELINE.BUS.STAGE_DISABLED"]},
            )
        )
    else:
        bus_decisions, bus_actions = _run_stage_plugins(
            stage_scope=STAGE_BUS,
            targets=bus_targets,
            stage_plugins=plugin_by_stage[STAGE_BUS],
        )
        events.extend(bus_decisions)
        actions.extend(bus_actions)
        stage_counters[STAGE_BUS]["decision_count"] = len(bus_decisions)
        stage_counters[STAGE_BUS]["action_count"] = len(bus_actions)
    stage_counters[STAGE_BUS]["target_count"] = len(bus_targets)
    _emit_stage_complete(
        events,
        stage_scope=STAGE_BUS,
        counters=stage_counters[STAGE_BUS],
    )

    master_target = DspTargetContext(
        stage_scope=STAGE_POST_MASTER,
        target_scope="master",
        target_id=_MASTER_BUS_ID,
        role_id=None,
        bus_id=_MASTER_BUS_ID,
        stem_ids=tuple(_coerce_str(row.get("stem_id")).strip() for row in stem_rows),
        layout_id=layout_id,
        standard=standard,
        evidence={
            "bus_count": float(len(bus_targets)),
            "stem_count": float(len(stem_rows)),
        },
    )
    _emit_stage_start(events, stage_scope=STAGE_POST_MASTER, target_count=1)
    if not enable_post_master_stage:
        events.append(
            _event_dict(
                stage_scope=STAGE_POST_MASTER,
                plugin_id="DSP.PIPELINE",
                what="post-master DSP stage skipped",
                why=(
                    "Guardrail: post-master DSP is disabled unless explicitly enabled."
                ),
                where=[_MASTER_BUS_ID],
                confidence=1.0,
                evidence={"codes": ["DSP.PIPELINE.POST_MASTER.STAGE_DISABLED"]},
            )
        )
    else:
        post_decisions, post_actions = _run_stage_plugins(
            stage_scope=STAGE_POST_MASTER,
            targets=[master_target],
            stage_plugins=plugin_by_stage[STAGE_POST_MASTER],
        )
        events.extend(post_decisions)
        actions.extend(post_actions)
        stage_counters[STAGE_POST_MASTER]["decision_count"] = len(post_decisions)
        stage_counters[STAGE_POST_MASTER]["action_count"] = len(post_actions)
    stage_counters[STAGE_POST_MASTER]["target_count"] = 1
    _emit_stage_complete(
        events,
        stage_scope=STAGE_POST_MASTER,
        counters=stage_counters[STAGE_POST_MASTER],
    )

    return {
        "schema_version": "0.1.0",
        "layout_id": layout_id,
        "standard": standard,
        "actions": actions,
        "events": events,
        "stages": {
            stage_scope: stage_counters[stage_scope] for stage_scope in STAGE_ORDER
        },
    }


def _validate_plugins_or_raise(plugins: list[DspHookPlugin]) -> None:
    failures: list[str] = []
    for plugin in plugins:
        manifest = _coerce_dict(getattr(plugin, "manifest", {}))
        plugin_id = _coerce_str(getattr(plugin, "plugin_id", "")).strip() or "(unknown)"
        errors = validate_dsp_plugin_manifest(manifest)
        if errors:
            failures.append(f"{plugin_id}: {'; '.join(errors)}")
    if failures:
        raise ValueError(f"DSP hook plugin manifest validation failed: {' | '.join(failures)}")


def _build_effective_stem_rows(
    *,
    stem_results: list[Any],
    stem_specs: list[DspStemSpec] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    specs = stem_specs or []
    specs_by_stem_id: dict[str, DspStemSpec] = {spec.stem_id: spec for spec in specs}

    normalized_results = sorted(
        stem_results,
        key=lambda row: _coerce_str(getattr(row, "stem_id", "")).strip(),
    )
    for result in normalized_results:
        stem_id = _coerce_str(getattr(result, "stem_id", "")).strip()
        if not stem_id:
            continue

        spec = specs_by_stem_id.get(stem_id)
        role_from_result = _coerce_str(getattr(result, "role_id", "")).strip()
        bus_from_result = _coerce_str(getattr(result, "bus_id", "")).strip()

        role_id = role_from_result or (spec.role_id if spec is not None else _DEFAULT_ROLE_ID)
        if not role_id:
            role_id = _DEFAULT_ROLE_ID

        bus_id = (
            bus_from_result
            or (spec.bus_id if spec is not None else "")
            or _infer_bus_id_for_role(role_id)
        )
        bus_id = _normalize_bus_id(bus_id, role_id=role_id)

        evidence = {}
        if spec is not None:
            evidence.update(_normalize_evidence(spec.evidence))

        num_channels = _coerce_int(getattr(result, "num_channels", None))
        lfe_slots = getattr(result, "lfe_slots", [])
        height_slots = getattr(result, "height_slots", [])
        if num_channels is not None:
            evidence.setdefault("num_channels", float(num_channels))
        if isinstance(lfe_slots, list):
            evidence.setdefault("lfe_slot_count", float(len(lfe_slots)))
        if isinstance(height_slots, list):
            evidence.setdefault("height_slot_count", float(len(height_slots)))

        rows.append(
            {
                "stem_id": stem_id,
                "role_id": role_id,
                "bus_id": bus_id,
                "layout_id": _coerce_str(getattr(result, "layout_id", "")).strip()
                or "LAYOUT.2_0",
                "standard": _coerce_str(getattr(result, "standard", "")).strip()
                or "SMPTE",
                "evidence": evidence,
            }
        )

    if rows:
        return rows

    # If no dispatch results were provided, fall back to explicit stem specs.
    for spec in sorted(specs, key=lambda item: item.stem_id):
        role_id = spec.role_id or _DEFAULT_ROLE_ID
        bus_id = _normalize_bus_id(spec.bus_id, role_id=role_id)
        rows.append(
            {
                "stem_id": spec.stem_id,
                "role_id": role_id,
                "bus_id": bus_id,
                "layout_id": "LAYOUT.2_0",
                "standard": "SMPTE",
                "evidence": _normalize_evidence(spec.evidence),
            }
        )
    return rows


def _build_bus_targets(
    stem_rows: list[dict[str, Any]],
    *,
    layout_id: str,
    standard: str,
) -> list[DspTargetContext]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in stem_rows:
        bus_id = _coerce_str(row.get("bus_id")).strip() or _DEFAULT_BUS_ID
        grouped.setdefault(bus_id, []).append(row)

    targets: list[DspTargetContext] = []
    for bus_id in sorted(grouped.keys(), key=_bus_sort_key):
        entries = grouped[bus_id]
        stem_ids = tuple(
            sorted(
                _coerce_str(entry.get("stem_id")).strip()
                for entry in entries
                if _coerce_str(entry.get("stem_id")).strip()
            )
        )
        roles = tuple(
            sorted(
                {
                    _coerce_str(entry.get("role_id")).strip() or _DEFAULT_ROLE_ID
                    for entry in entries
                }
            )
        )
        rumble_confidences = [
            _rumble_confidence(_coerce_dict(entry.get("evidence"))) for entry in entries
        ]
        evidence = {
            "stem_count": float(len(stem_ids)),
            "role_count": float(len(roles)),
            "rumble_confidence_max": max(rumble_confidences) if rumble_confidences else 0.0,
        }
        targets.append(
            DspTargetContext(
                stage_scope=STAGE_BUS,
                target_scope="bus",
                target_id=bus_id,
                role_id=None,
                bus_id=bus_id,
                stem_ids=stem_ids,
                layout_id=layout_id,
                standard=standard,
                evidence=evidence,
            )
        )
    return targets


def _run_stage_plugins(
    *,
    stage_scope: str,
    targets: list[DspTargetContext],
    stage_plugins: list[DspHookPlugin],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    decision_events: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []

    if not stage_plugins:
        return decision_events, actions

    for target in targets:
        for plugin in stage_plugins:
            decision = plugin.decide(target)
            if decision is None:
                continue

            normalized_event = _event_dict(
                stage_scope=stage_scope,
                plugin_id=_coerce_str(plugin.plugin_id).strip() or "(unknown)",
                what=decision.what,
                why=decision.why,
                where=decision.where,
                confidence=decision.confidence,
                evidence=_coerce_dict(decision.evidence),
            )
            decision_events.append(normalized_event)

            if not decision.applied:
                continue

            refusal_reason = _authority_violation_reason(
                manifest=_coerce_dict(plugin.manifest),
                context=target,
                decision=decision,
            )
            if refusal_reason:
                decision_events.append(
                    _event_dict(
                        stage_scope=stage_scope,
                        plugin_id=_coerce_str(plugin.plugin_id).strip() or "(unknown)",
                        what="DSP action refused by authority",
                        why=refusal_reason,
                        where=decision.where,
                        confidence=1.0,
                        evidence={
                            "codes": ["DSP.PIPELINE.ACTION_REFUSED"],
                        },
                    )
                )
                continue

            action_id = _coerce_str(decision.action_id).strip()
            if not action_id:
                continue
            params = {
                key: value
                for key, value in sorted(decision.params.items())
                if isinstance(key, str)
            }
            actions.append(
                {
                    "plugin_id": _coerce_str(plugin.plugin_id).strip() or "(unknown)",
                    "stage_scope": stage_scope,
                    "target_scope": target.target_scope,
                    "target_id": target.target_id,
                    "action_id": action_id,
                    "params": params,
                    "what": _coerce_str(decision.what).strip(),
                    "why": _coerce_str(decision.why).strip(),
                    "where": list(_normalize_where(decision.where)),
                    "confidence": _clamp_confidence(decision.confidence),
                }
            )

    return decision_events, actions


def _authority_violation_reason(
    *,
    manifest: dict[str, Any],
    context: DspTargetContext,
    decision: DspPluginDecision,
) -> str | None:
    authority = _coerce_dict(manifest.get("authority"))
    impact_level = _coerce_str(authority.get("impact_level")).strip()
    if impact_level != "low_risk":
        return (
            "Only low_risk DSP hooks may auto-plan actions in this stage. "
            f"manifest impact_level={impact_level or '(missing)'}"
        )

    allow_on_bass_roles = authority.get("allow_on_bass_roles")
    if allow_on_bass_roles is False and _is_bass_role(_coerce_str(context.role_id)):
        return "Bass-target action refused: manifest forbids automatic bass-role processing."

    targets = _coerce_dict(manifest.get("targets"))
    include_roles = _coerce_str_list(targets.get("include_roles"))
    exclude_roles = _coerce_str_list(targets.get("exclude_roles"))
    include_buses = _coerce_str_list(targets.get("include_buses"))
    exclude_buses = _coerce_str_list(targets.get("exclude_buses"))

    role_id = _coerce_str(context.role_id).strip()
    bus_id = _coerce_str(context.bus_id).strip()
    if include_roles and role_id and role_id not in include_roles:
        return f"Role {role_id} not in manifest include_roles allowlist."
    if role_id and role_id in exclude_roles:
        return f"Role {role_id} is explicitly excluded by manifest."
    if include_buses and bus_id and bus_id not in include_buses:
        return f"Bus {bus_id} not in manifest include_buses allowlist."
    if bus_id and bus_id in exclude_buses:
        return f"Bus {bus_id} is explicitly excluded by manifest."

    evidence_contract = _coerce_dict(manifest.get("evidence_contract"))
    requires_evidence = authority.get("requires_evidence")
    if requires_evidence is True:
        metric_key = _coerce_str(evidence_contract.get("metric_key")).strip()
        threshold = _coerce_float(evidence_contract.get("min_confidence"))
        if metric_key:
            metric_value = _coerce_float(_coerce_dict(context.evidence).get(metric_key))
            if metric_value is None:
                return (
                    "Evidence-gated action refused: required metric is missing. "
                    f"metric_key={metric_key}"
                )
            if threshold is not None and metric_value < threshold:
                return (
                    "Evidence-gated action refused: metric below threshold. "
                    f"{metric_key}={metric_value:.3f}, threshold={threshold:.3f}"
                )

    bounds = _coerce_dict(_coerce_dict(manifest.get("action")).get("parameter_bounds"))
    for param_name in sorted(decision.params.keys()):
        if param_name not in bounds:
            return (
                "Parameter is outside manifest authority envelope. "
                f"param={param_name}"
            )
        bound_row = _coerce_dict(bounds.get(param_name))
        minimum = _coerce_float(bound_row.get("min"))
        maximum = _coerce_float(bound_row.get("max"))
        param_value = _coerce_float(decision.params.get(param_name))
        if param_value is None:
            return f"Parameter {param_name} must be numeric for authority checks."
        if minimum is not None and param_value < minimum:
            return (
                f"Parameter {param_name}={param_value} violates minimum {minimum}."
            )
        if maximum is not None and param_value > maximum:
            return (
                f"Parameter {param_name}={param_value} violates maximum {maximum}."
            )

    return None


def _emit_stage_start(
    events: list[dict[str, Any]],
    *,
    stage_scope: str,
    target_count: int,
) -> None:
    events.append(
        _event_dict(
            stage_scope=stage_scope,
            plugin_id="DSP.PIPELINE",
            what="DSP stage started",
            why=(
                "Running deterministic DSP hook stage with bounded authority checks."
            ),
            where=[stage_scope],
            confidence=1.0,
            evidence={
                "codes": ["DSP.PIPELINE.STAGE.STARTED"],
                "metrics": [{"name": "target_count", "value": float(target_count)}],
            },
        )
    )


def _emit_stage_complete(
    events: list[dict[str, Any]],
    *,
    stage_scope: str,
    counters: Mapping[str, int],
) -> None:
    events.append(
        _event_dict(
            stage_scope=stage_scope,
            plugin_id="DSP.PIPELINE",
            what="DSP stage completed",
            why="Completed deterministic hook dispatch for the current stage.",
            where=[stage_scope],
            confidence=1.0,
            evidence={
                "codes": ["DSP.PIPELINE.STAGE.COMPLETED"],
                "metrics": [
                    {
                        "name": "target_count",
                        "value": float(_coerce_int(counters.get("target_count")) or 0),
                    },
                    {
                        "name": "decision_count",
                        "value": float(_coerce_int(counters.get("decision_count")) or 0),
                    },
                    {
                        "name": "action_count",
                        "value": float(_coerce_int(counters.get("action_count")) or 0),
                    },
                ],
            },
        )
    )


def _event_dict(
    *,
    stage_scope: str,
    plugin_id: str,
    what: str,
    why: str,
    where: Any,
    confidence: float,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stage_scope": _coerce_str(stage_scope).strip() or STAGE_PRE_BUS_STEM,
        "plugin_id": _coerce_str(plugin_id).strip() or "(unknown)",
        "what": _coerce_str(what).strip(),
        "why": _coerce_str(why).strip(),
        "where": list(_normalize_where(where)),
        "confidence": _clamp_confidence(confidence),
        "evidence": _normalize_evidence_payload(evidence),
    }


def _normalize_evidence_payload(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, dict):
        return {}

    payload: dict[str, Any] = {}
    codes = _coerce_str_list(raw_value.get("codes"))
    if codes:
        payload["codes"] = codes

    ids = _coerce_str_list(raw_value.get("ids"))
    if ids:
        payload["ids"] = ids

    notes = _coerce_str_list(raw_value.get("notes"))
    if notes:
        payload["notes"] = notes

    metrics_raw = raw_value.get("metrics")
    if isinstance(metrics_raw, list):
        metrics: list[dict[str, Any]] = []
        for metric in metrics_raw:
            if not isinstance(metric, dict):
                continue
            name = _coerce_str(metric.get("name") or metric.get("key")).strip()
            value = _coerce_float(metric.get("value"))
            if not name or value is None:
                continue
            row: dict[str, Any] = {"name": name, "value": value}
            unit = _coerce_str(metric.get("unit")).strip()
            if unit:
                row["unit"] = unit
            metrics.append(row)
        if metrics:
            metrics.sort(key=lambda row: row["name"])
            payload["metrics"] = metrics

    paths = _coerce_str_list(raw_value.get("paths"))
    if paths:
        payload["paths"] = paths

    return payload


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _coerce_str(item).strip()
        if text:
            normalized.append(text)
    normalized.sort()
    deduped: list[str] = []
    seen: set[str] = set()
    for item in normalized:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _normalize_where(value: Any) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(value, (list, tuple)):
        raw_values = list(value)
    else:
        raw_values = [value]
    for item in raw_values:
        text = _coerce_str(item).replace("\\", "/").strip()
        if text:
            values.append(text)
    if not values:
        return ("(none)",)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return tuple(deduped)


def _clamp_confidence(value: float) -> float:
    numeric = _coerce_float(value)
    if numeric is None:
        return 0.0
    return max(0.0, min(1.0, round(numeric, 3)))


def _normalize_evidence(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, dict):
        return {}
    normalized: dict[str, Any] = {}
    for raw_key in sorted(raw_value.keys(), key=lambda key: str(key)):
        key = _coerce_str(raw_key).strip()
        if not key:
            continue
        value = raw_value[raw_key]
        if isinstance(value, bool):
            normalized[key] = value
            continue
        numeric = _coerce_float(value)
        if numeric is not None:
            normalized[key] = numeric
            continue
        text = _coerce_str(value).strip()
        if text:
            normalized[key] = text
    return normalized


def _is_bass_role(role_id: str) -> bool:
    normalized = _coerce_str(role_id).strip().upper()
    return normalized.startswith("ROLE.BASS.")


def _infer_bus_id_for_role(role_id: str) -> str:
    normalized = _coerce_str(role_id).strip().upper()
    if normalized.startswith("ROLE.DRUM."):
        return "BUS.DRUMS"
    if normalized.startswith("ROLE.BASS."):
        return "BUS.BASS"
    if normalized.startswith("ROLE.VOCAL.") or normalized.startswith("ROLE.DIALOGUE."):
        return "BUS.VOX"
    if normalized.startswith("ROLE.SFX.") or normalized.startswith("ROLE.FX."):
        return "BUS.FX"
    if normalized.startswith("ROLE.OTHER."):
        return "BUS.OTHER"
    return "BUS.MUSIC"


def _normalize_bus_id(raw_bus_id: str, *, role_id: str) -> str:
    normalized = _coerce_str(raw_bus_id).strip().upper()
    if not normalized:
        return _infer_bus_id_for_role(role_id)
    if normalized.startswith("BUS."):
        return normalized
    return f"BUS.{normalized}"


def _bus_sort_key(bus_id: str) -> tuple[int, str, str]:
    parts = bus_id.split(".")
    group = parts[1] if len(parts) > 1 else "OTHER"
    rank = _BUS_GROUP_RANK.get(group, len(_BUS_GROUP_RANK))
    suffix = parts[-1] if parts else bus_id
    return (rank, suffix, bus_id)


def _rumble_confidence(evidence: Mapping[str, Any]) -> float:
    if evidence.get("infrasonic_rumble") is True:
        return 1.0

    for key in (
        "rumble_confidence",
        "infrasonic_rumble_confidence",
        "subsonic_rumble_confidence",
    ):
        numeric = _coerce_float(evidence.get(key))
        if numeric is not None:
            return max(0.0, min(1.0, numeric))
    return 0.0


def _channel_metrics(evidence: Mapping[str, Any]) -> list[dict[str, float]]:
    metrics: list[dict[str, float]] = []
    for key in ("num_channels", "lfe_slot_count", "height_slot_count"):
        value = _coerce_float(evidence.get(key))
        if value is None:
            continue
        metrics.append({"name": key, "value": value})
    return metrics


def _load_schema(schema_path: Path) -> dict[str, Any]:
    global _SCHEMA_CACHE

    resolved = schema_path.resolve()
    if _SCHEMA_CACHE is not None:
        cache_path = _coerce_str(_SCHEMA_CACHE.get("_path")).strip()
        if cache_path == resolved.as_posix():
            cached = _coerce_dict(_SCHEMA_CACHE.get("schema"))
            if cached:
                return cached

    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Schema JSON must be an object: {resolved.as_posix()}")

    _SCHEMA_CACHE = {
        "_path": resolved.as_posix(),
        "schema": payload,
    }
    return payload


__all__ = [
    "DspStemSpec",
    "DspTargetContext",
    "DspPluginDecision",
    "DspHookPlugin",
    "ConservativeHpfRumblePlugin",
    "default_dsp_hook_plugins",
    "normalize_dsp_stem_specs",
    "validate_dsp_plugin_manifest",
    "run_dsp_pipeline_hooks",
    "STAGE_PRE_BUS_STEM",
    "STAGE_BUS",
    "STAGE_POST_MASTER",
]
