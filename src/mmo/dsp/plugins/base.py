"""Base types and shared helpers for plugin-chain DSP modules."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class PluginValidationError(ValueError):
    """Raised when a plugin stage has invalid runtime parameters."""


@dataclass
class PluginEvidenceCollector:
    """Mutable stage evidence payload that plugins populate deterministically."""

    stage_what: str = "plugin stage applied"
    stage_why: str = ""
    metrics: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] | None = None

    def set(
        self,
        *,
        stage_what: str,
        stage_why: str,
        metrics: list[dict[str, Any]],
        notes: list[str] | None = None,
    ) -> None:
        self.stage_what = stage_what
        self.stage_why = stage_why
        self.metrics = metrics
        self.notes = notes


@dataclass(frozen=True)
class PluginContext:
    """Execution context for a single plugin stage."""

    precision_mode: str
    max_theoretical_quality: bool
    evidence_collector: PluginEvidenceCollector
    stage_index: int


@runtime_checkable
class StereoPlugin(Protocol):
    """Interface for deterministic stereo plugin processors."""

    plugin_id: str

    def process_stereo(
        self,
        buf_f32_or_f64: Any,
        sample_rate: int,
        params: dict[str, Any],
        ctx: PluginContext,
    ) -> Any:
        """Process stereo buffer and populate ``ctx.evidence_collector``."""


def coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, float) and value in (0.0, 1.0):
        return bool(int(value))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def coerce_int(value: Any) -> int | None:
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


def parse_bypass_for_stage(*, plugin_id: str, params: dict[str, Any]) -> bool:
    bypass_raw = params.get("bypass")
    if bypass_raw is None:
        return False
    bypass_value = coerce_bool(bypass_raw)
    if bypass_value is None:
        raise PluginValidationError(
            f"{plugin_id} requires boolean params.bypass when provided.",
        )
    return bypass_value


def parse_macro_mix_for_stage(
    *,
    plugin_id: str,
    params: dict[str, Any],
) -> tuple[float, float]:
    raw_macro_mix = params.get("macro_mix")
    if raw_macro_mix is None:
        return 1.0, 1.0
    macro_mix_input = coerce_float(raw_macro_mix)
    if macro_mix_input is None:
        raise PluginValidationError(
            f"{plugin_id} requires numeric params.macro_mix "
            "in [0.0, 1.0] or [0.0, 100.0].",
        )
    if 0.0 <= macro_mix_input <= 1.0:
        return macro_mix_input, macro_mix_input
    if 0.0 <= macro_mix_input <= 100.0:
        return macro_mix_input / 100.0, macro_mix_input
    raise PluginValidationError(
        f"{plugin_id} requires params.macro_mix "
        "in [0.0, 1.0] or [0.0, 100.0].",
    )


def require_finite_float_param(
    *,
    plugin_id: str,
    params: dict[str, Any],
    param_name: str,
) -> float:
    value = coerce_float(params.get(param_name))
    if value is None or not math.isfinite(value):
        raise PluginValidationError(
            f"{plugin_id} requires numeric params.{param_name}.",
        )
    return float(value)


def optional_int_param(
    *,
    plugin_id: str,
    params: dict[str, Any],
    param_name: str,
    default_value: int,
    minimum_value: int,
    maximum_value: int,
) -> int:
    raw_value = params.get(param_name)
    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool):
        raise PluginValidationError(
            f"{plugin_id} requires integer params.{param_name}.",
        )
    value = coerce_int(raw_value)
    if value is None:
        raise PluginValidationError(
            f"{plugin_id} requires integer params.{param_name}.",
        )
    if value < minimum_value or value > maximum_value:
        raise PluginValidationError(
            f"{plugin_id} requires params.{param_name} in "
            f"[{minimum_value}, {maximum_value}].",
        )
    return value


def optional_float_param(
    *,
    plugin_id: str,
    params: dict[str, Any],
    param_name: str,
    default_value: float,
    minimum_value: float,
    maximum_value: float,
) -> float:
    raw_value = params.get(param_name)
    if raw_value is None:
        return default_value
    value = coerce_float(raw_value)
    if value is None or not math.isfinite(value):
        raise PluginValidationError(
            f"{plugin_id} requires numeric params.{param_name}.",
        )
    if value < minimum_value or value > maximum_value:
        raise PluginValidationError(
            f"{plugin_id} requires params.{param_name} in "
            f"[{minimum_value}, {maximum_value}].",
        )
    return float(value)

