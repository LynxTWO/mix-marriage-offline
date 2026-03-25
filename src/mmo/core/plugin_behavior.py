from __future__ import annotations

import math
from typing import Any

from mmo.plugins.interfaces import PluginBehaviorContract

_DEFAULT_AUTO_APPLY_MAX_INTEGRATED_LUFS_DELTA = 0.1
_DEFAULT_AUTO_APPLY_MAX_TRUE_PEAK_DELTA_DB = 0.1


def _coerce_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        candidate = float(value)
        if math.isfinite(candidate):
            return candidate
    return None


def _supported_contexts(capabilities: Any) -> tuple[str, ...]:
    if hasattr(capabilities, "supported_contexts"):
        raw_value = getattr(capabilities, "supported_contexts")
        if isinstance(raw_value, tuple):
            return tuple(
                item for item in raw_value if isinstance(item, str) and item.strip()
            )
    if isinstance(capabilities, dict):
        raw_value = capabilities.get("supported_contexts")
        if isinstance(raw_value, list):
            return tuple(
                item for item in raw_value if isinstance(item, str) and item.strip()
            )
    return ()


def _as_behavior_contract(value: Any) -> PluginBehaviorContract | None:
    if isinstance(value, PluginBehaviorContract):
        return value
    if not isinstance(value, dict):
        return None
    return PluginBehaviorContract(
        loudness_behavior=_coerce_string(value.get("loudness_behavior")),
        max_integrated_lufs_delta=_coerce_float(value.get("max_integrated_lufs_delta")),
        peak_behavior=_coerce_string(value.get("peak_behavior")),
        max_true_peak_delta_db=_coerce_float(value.get("max_true_peak_delta_db")),
        phase_behavior=_coerce_string(value.get("phase_behavior")),
        stereo_image_behavior=_coerce_string(value.get("stereo_image_behavior")),
        gain_compensation=_coerce_string(value.get("gain_compensation")),
        rationale=_coerce_string(value.get("rationale")),
    )


def effective_behavior_contract(
    *,
    plugin_type: str,
    capabilities: Any,
    behavior_contract: Any,
) -> PluginBehaviorContract | None:
    explicit_contract = _as_behavior_contract(behavior_contract)
    auto_apply = "auto_apply" in _supported_contexts(capabilities)
    should_default = auto_apply and plugin_type in {"renderer", "resolver"}

    if explicit_contract is None and not should_default:
        return None

    base = explicit_contract or PluginBehaviorContract()
    if not should_default:
        return base

    return PluginBehaviorContract(
        loudness_behavior=base.loudness_behavior or "preserve",
        max_integrated_lufs_delta=(
            base.max_integrated_lufs_delta
            if base.max_integrated_lufs_delta is not None
            else _DEFAULT_AUTO_APPLY_MAX_INTEGRATED_LUFS_DELTA
        ),
        peak_behavior=base.peak_behavior or "bounded",
        max_true_peak_delta_db=(
            base.max_true_peak_delta_db
            if base.max_true_peak_delta_db is not None
            else _DEFAULT_AUTO_APPLY_MAX_TRUE_PEAK_DELTA_DB
        ),
        phase_behavior=base.phase_behavior,
        stereo_image_behavior=base.stereo_image_behavior,
        gain_compensation=base.gain_compensation or "required",
        rationale=base.rationale,
    )


def validate_behavior_contract_definition(
    *,
    plugin_type: str,
    capabilities: Any,
    behavior_contract: Any,
) -> list[str]:
    explicit_contract = _as_behavior_contract(behavior_contract)
    if explicit_contract is None:
        return []

    errors: list[str] = []
    needs_rationale = False
    if (
        explicit_contract.max_integrated_lufs_delta is not None
        and explicit_contract.max_integrated_lufs_delta
        > _DEFAULT_AUTO_APPLY_MAX_INTEGRATED_LUFS_DELTA
    ):
        needs_rationale = True
    if (
        explicit_contract.max_true_peak_delta_db is not None
        and explicit_contract.max_true_peak_delta_db
        > _DEFAULT_AUTO_APPLY_MAX_TRUE_PEAK_DELTA_DB
    ):
        needs_rationale = True

    if needs_rationale and not _coerce_string(explicit_contract.rationale):
        errors.append(
            "behavior_contract entries looser than the conservative 0.1/0.1 "
            "auto-apply defaults must include behavior_contract.rationale."
        )

    return errors


def evaluate_behavior_contract(
    *,
    plugin_type: str,
    capabilities: Any,
    behavior_contract: Any,
    metrics_delta: dict[str, Any],
) -> dict[str, Any]:
    contract = effective_behavior_contract(
        plugin_type=plugin_type,
        capabilities=capabilities,
        behavior_contract=behavior_contract,
    )
    if contract is None:
        return {
            "ok": True,
            "applied": False,
            "contract": None,
            "violations": [],
        }

    violations: list[dict[str, Any]] = []
    integrated_lufs_delta = _coerce_float(metrics_delta.get("integrated_lufs"))
    if (
        contract.max_integrated_lufs_delta is not None
        and integrated_lufs_delta is not None
        and abs(integrated_lufs_delta) > contract.max_integrated_lufs_delta
    ):
        violations.append(
            {
                "metric": "integrated_lufs",
                "value": integrated_lufs_delta,
                "max_abs_delta": contract.max_integrated_lufs_delta,
            }
        )

    true_peak_delta = _coerce_float(metrics_delta.get("true_peak_dbtp"))
    if (
        contract.max_true_peak_delta_db is not None
        and true_peak_delta is not None
        and abs(true_peak_delta) > contract.max_true_peak_delta_db
    ):
        violations.append(
            {
                "metric": "true_peak_dbtp",
                "value": true_peak_delta,
                "max_abs_delta": contract.max_true_peak_delta_db,
            }
        )

    return {
        "ok": len(violations) == 0,
        "applied": True,
        "contract": contract.to_dict(),
        "violations": violations,
    }


__all__ = [
    "effective_behavior_contract",
    "evaluate_behavior_contract",
    "validate_behavior_contract_definition",
]
