"""Policy registry + pack validator for downmix policies."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None


ISSUE_POLICY_PARSE_ERROR = "ISSUE.VALIDATION.POLICY_PARSE_ERROR"
ISSUE_POLICY_SCHEMA_INVALID = "ISSUE.VALIDATION.POLICY_SCHEMA_INVALID"
ISSUE_POLICY_FILE_MISSING = "ISSUE.VALIDATION.POLICY_FILE_MISSING"
ISSUE_DOWNMIX_POLICY_ID_MISMATCH = "ISSUE.VALIDATION.DOWNMIX_POLICY_ID_MISMATCH"
ISSUE_DOWNMIX_MATRIX_ID_MISSING = "ISSUE.VALIDATION.DOWNMIX_MATRIX_ID_MISSING"
ISSUE_DOWNMIX_LAYOUT_UNKNOWN = "ISSUE.VALIDATION.DOWNMIX_LAYOUT_UNKNOWN"
ISSUE_DOWNMIX_SPEAKER_UNKNOWN = "ISSUE.VALIDATION.DOWNMIX_SPEAKER_UNKNOWN"
ISSUE_DOWNMIX_LAYOUT_SPEAKER_MISMATCH = "ISSUE.VALIDATION.DOWNMIX_LAYOUT_SPEAKER_MISMATCH"
ISSUE_DOWNMIX_COEFFICIENT_INVALID = "ISSUE.VALIDATION.DOWNMIX_COEFFICIENT_INVALID"
ISSUE_DOWNMIX_COEFFICIENT_HIGH = "ISSUE.VALIDATION.DOWNMIX_COEFFICIENT_HIGH"
ISSUE_DOWNMIX_COEFFICIENT_SUM_EXCESSIVE = (
    "ISSUE.VALIDATION.DOWNMIX_COEFFICIENT_SUM_EXCESSIVE"
)


def _add_issue(
    issues: List[Dict[str, Any]],
    issue_id: str,
    severity_label: str,
    message: str,
    evidence: Optional[Dict[str, Any]] = None,
) -> None:
    item: Dict[str, Any] = {
        "issue_id": issue_id,
        "severity_label": severity_label,
        "message": message,
    }
    if evidence:
        item["evidence"] = evidence
    issues.append(item)


def _load_yaml(path: Path, issues: List[Dict[str, Any]]) -> Optional[Any]:
    if yaml is None:
        _add_issue(
            issues,
            ISSUE_POLICY_PARSE_ERROR,
            "error",
            "PyYAML is not installed; cannot parse YAML files.",
            {"file_path": str(path)},
        )
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except Exception as exc:  # pragma: no cover - parse failures vary
        _add_issue(
            issues,
            ISSUE_POLICY_PARSE_ERROR,
            "error",
            f"Failed to parse YAML: {exc}",
            {"file_path": str(path)},
        )
        return None


def _load_layouts(root: Path, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    layouts_path = root / "ontology" / "layouts.yaml"
    data = _load_yaml(layouts_path, issues)
    if not isinstance(data, dict) or "layouts" not in data:
        _add_issue(
            issues,
            ISSUE_POLICY_SCHEMA_INVALID,
            "error",
            "layouts.yaml is missing the root layouts map.",
            {"file_path": str(layouts_path)},
        )
        return {}
    layouts = data.get("layouts")
    return layouts if isinstance(layouts, dict) else {}


def _load_speakers(root: Path, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    speakers_path = root / "ontology" / "speakers.yaml"
    data = _load_yaml(speakers_path, issues)
    if not isinstance(data, dict) or "speakers" not in data:
        _add_issue(
            issues,
            ISSUE_POLICY_SCHEMA_INVALID,
            "error",
            "speakers.yaml is missing the root speakers map.",
            {"file_path": str(speakers_path)},
        )
        return {}
    speakers = data.get("speakers")
    return speakers if isinstance(speakers, dict) else {}


def _layouts_set(layouts: Dict[str, Any]) -> set[str]:
    return {k for k in layouts.keys() if isinstance(k, str)}


def _speakers_set(speakers: Dict[str, Any]) -> set[str]:
    return {k for k in speakers.keys() if isinstance(k, str)}


def _get_channel_order(layouts: Dict[str, Any], layout_id: str) -> Optional[List[str]]:
    layout = layouts.get(layout_id)
    if not isinstance(layout, dict):
        return None
    channel_order = layout.get("channel_order")
    if not isinstance(channel_order, list):
        return None
    return [str(ch) for ch in channel_order]


def _validate_matrix(
    matrix_id: str,
    matrix: Any,
    pack_path: Path,
    layouts: Dict[str, Any],
    speakers: Dict[str, Any],
    issues: List[Dict[str, Any]],
    *,
    strict: bool,
) -> None:
    if not isinstance(matrix, dict):
        _add_issue(
            issues,
            ISSUE_POLICY_SCHEMA_INVALID,
            "error",
            "Matrix entry must be a map.",
            {"file_path": str(pack_path), "matrix_id": matrix_id},
        )
        return

    source_layout_id = matrix.get("source_layout_id")
    target_layout_id = matrix.get("target_layout_id")

    layouts_known = _layouts_set(layouts)
    if source_layout_id not in layouts_known or target_layout_id not in layouts_known:
        _add_issue(
            issues,
            ISSUE_DOWNMIX_LAYOUT_UNKNOWN,
            "error",
            "Matrix references unknown source/target layout.",
            {
                "file_path": str(pack_path),
                "matrix_id": matrix_id,
                "source_layout_id": source_layout_id,
                "target_layout_id": target_layout_id,
            },
        )

    coefficients = matrix.get("coefficients")
    if not isinstance(coefficients, dict):
        _add_issue(
            issues,
            ISSUE_DOWNMIX_COEFFICIENT_INVALID,
            "error",
            "Matrix coefficients must be a map of target speakers to source maps.",
            {"file_path": str(pack_path), "matrix_id": matrix_id},
        )
        return

    speakers_known = _speakers_set(speakers)
    target_layout_channels = (
        set(_get_channel_order(layouts, target_layout_id) or [])
        if target_layout_id in layouts_known
        else None
    )
    source_layout_channels = (
        set(_get_channel_order(layouts, source_layout_id) or [])
        if source_layout_id in layouts_known
        else None
    )

    target_speakers = set(coefficients.keys())
    if target_layout_channels is not None and target_speakers != target_layout_channels:
        _add_issue(
            issues,
            ISSUE_DOWNMIX_LAYOUT_SPEAKER_MISMATCH,
            "error",
            "Target speakers do not match the declared target layout.",
            {
                "file_path": str(pack_path),
                "matrix_id": matrix_id,
                "target_layout_id": target_layout_id,
            },
        )

    for target_spk, source_map in coefficients.items():
        target_is_known = target_spk in speakers_known
        if not target_is_known:
            _add_issue(
                issues,
                ISSUE_DOWNMIX_SPEAKER_UNKNOWN,
                "error",
                "Target speaker is not defined in ontology/speakers.yaml.",
                {
                    "file_path": str(pack_path),
                    "matrix_id": matrix_id,
                    "speaker_id": target_spk,
                },
            )

        if not isinstance(source_map, dict):
            _add_issue(
                issues,
                ISSUE_DOWNMIX_COEFFICIENT_INVALID,
                "error",
                "Coefficient source map must be a map of source speakers to gains.",
                {
                    "file_path": str(pack_path),
                    "matrix_id": matrix_id,
                    "speaker_id": target_spk,
                },
            )
            continue

        sum_abs = 0.0
        for source_spk, coef in source_map.items():
            source_is_known = source_spk in speakers_known
            if not source_is_known:
                _add_issue(
                    issues,
                    ISSUE_DOWNMIX_SPEAKER_UNKNOWN,
                    "error",
                    "Source speaker is not defined in ontology/speakers.yaml.",
                    {
                        "file_path": str(pack_path),
                        "matrix_id": matrix_id,
                        "speaker_id": source_spk,
                    },
                )

            if (
                source_is_known
                and source_layout_channels is not None
                and source_spk not in source_layout_channels
            ):
                _add_issue(
                    issues,
                    ISSUE_DOWNMIX_LAYOUT_SPEAKER_MISMATCH,
                    "error",
                    "Source speaker is not part of the declared source layout.",
                    {
                        "file_path": str(pack_path),
                        "matrix_id": matrix_id,
                        "source_layout_id": source_layout_id,
                        "speaker_id": source_spk,
                    },
                )

            if isinstance(coef, bool) or not isinstance(coef, (int, float)):
                _add_issue(
                    issues,
                    ISSUE_DOWNMIX_COEFFICIENT_INVALID,
                    "error",
                    "Coefficient is not a finite number.",
                    {
                        "file_path": str(pack_path),
                        "matrix_id": matrix_id,
                        "speaker_id": source_spk,
                        "coefficient": coef,
                    },
                )
                continue

            if not math.isfinite(float(coef)):
                _add_issue(
                    issues,
                    ISSUE_DOWNMIX_COEFFICIENT_INVALID,
                    "error",
                    "Coefficient is not a finite number.",
                    {
                        "file_path": str(pack_path),
                        "matrix_id": matrix_id,
                        "speaker_id": source_spk,
                        "coefficient": coef,
                    },
                )
                continue

            coef_value = float(coef)
            if abs(coef_value) > 4.0:
                _add_issue(
                    issues,
                    ISSUE_DOWNMIX_COEFFICIENT_INVALID,
                    "error",
                    "Coefficient exceeds hard limit of abs(coef) <= 4.0.",
                    {
                        "file_path": str(pack_path),
                        "matrix_id": matrix_id,
                        "speaker_id": source_spk,
                        "coefficient": coef_value,
                    },
                )
            elif abs(coef_value) > 2.0:
                _add_issue(
                    issues,
                    ISSUE_DOWNMIX_COEFFICIENT_HIGH,
                    "warn",
                    "Coefficient exceeds soft limit of abs(coef) > 2.0.",
                    {
                        "file_path": str(pack_path),
                        "matrix_id": matrix_id,
                        "speaker_id": source_spk,
                        "coefficient": coef_value,
                    },
                )

            sum_abs += abs(coef_value)

        warn_threshold = 2.5 if strict else 4.0
        if sum_abs > 4.0:
            _add_issue(
                issues,
                ISSUE_DOWNMIX_COEFFICIENT_SUM_EXCESSIVE,
                "error",
                "Sum of absolute coefficients exceeds hard limit (> 4.0).",
                {
                    "file_path": str(pack_path),
                    "matrix_id": matrix_id,
                    "speaker_id": target_spk,
                    "sum_abs": sum_abs,
                },
            )
        elif sum_abs > warn_threshold:
            _add_issue(
                issues,
                ISSUE_DOWNMIX_COEFFICIENT_SUM_EXCESSIVE,
                "warn",
                "Sum of absolute coefficients exceeds soft limit.",
                {
                    "file_path": str(pack_path),
                    "matrix_id": matrix_id,
                    "speaker_id": target_spk,
                    "sum_abs": sum_abs,
                },
            )


def _validate_pack(
    pack_path: Path,
    pack_data: Any,
    policy_id: str,
    layouts: Dict[str, Any],
    speakers: Dict[str, Any],
    issues: List[Dict[str, Any]],
    *,
    strict: bool,
) -> Optional[Dict[str, Any]]:
    if not isinstance(pack_data, dict) or "downmix_policy_pack" not in pack_data:
        _add_issue(
            issues,
            ISSUE_POLICY_PARSE_ERROR,
            "error",
            "Pack root must contain downmix_policy_pack.",
            {"file_path": str(pack_path)},
        )
        return None

    pack = pack_data.get("downmix_policy_pack")
    if not isinstance(pack, dict):
        _add_issue(
            issues,
            ISSUE_POLICY_SCHEMA_INVALID,
            "error",
            "downmix_policy_pack must be a map.",
            {"file_path": str(pack_path)},
        )
        return None

    required_keys = ["policy_id", "pack_version", "matrices"]
    if any(key not in pack for key in required_keys):
        _add_issue(
            issues,
            ISSUE_POLICY_SCHEMA_INVALID,
            "error",
            "downmix_policy_pack is missing required keys.",
            {"file_path": str(pack_path)},
        )
        return None

    if pack.get("policy_id") != policy_id:
        _add_issue(
            issues,
            ISSUE_DOWNMIX_POLICY_ID_MISMATCH,
            "error",
            "Pack policy_id does not match registry entry.",
            {"file_path": str(pack_path), "policy_id": pack.get("policy_id")},
        )

    matrices = pack.get("matrices")
    if not isinstance(matrices, dict):
        _add_issue(
            issues,
            ISSUE_POLICY_SCHEMA_INVALID,
            "error",
            "downmix_policy_pack.matrices must be a map.",
            {"file_path": str(pack_path)},
        )
        return None

    for matrix_id, matrix in matrices.items():
        _validate_matrix(
            matrix_id,
            matrix,
            pack_path,
            layouts,
            speakers,
            issues,
            strict=strict,
        )

    return pack


def validate_registry(registry_path: Path, *, strict: bool = False) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    root = Path(__file__).resolve().parents[1]

    layouts = _load_layouts(root, issues)
    speakers = _load_speakers(root, issues)

    registry = _load_yaml(registry_path, issues)
    if registry is None:
        return _result(registry_path, issues)

    if not isinstance(registry, dict) or "downmix" not in registry:
        _add_issue(
            issues,
            ISSUE_POLICY_PARSE_ERROR,
            "error",
            "Registry root must contain downmix.",
            {"file_path": str(registry_path)},
        )
        return _result(registry_path, issues)

    downmix = registry.get("downmix")
    if not isinstance(downmix, dict):
        _add_issue(
            issues,
            ISSUE_POLICY_SCHEMA_INVALID,
            "error",
            "downmix must be a map.",
            {"file_path": str(registry_path)},
        )
        return _result(registry_path, issues)

    required = ["_meta", "policies", "default_policy_by_source_layout", "conversions"]
    if any(key not in downmix for key in required):
        _add_issue(
            issues,
            ISSUE_POLICY_SCHEMA_INVALID,
            "error",
            "downmix registry is missing required keys.",
            {"file_path": str(registry_path)},
        )

    policies = downmix.get("policies") if isinstance(downmix.get("policies"), dict) else {}
    if not isinstance(downmix.get("policies"), dict):
        _add_issue(
            issues,
            ISSUE_POLICY_SCHEMA_INVALID,
            "error",
            "downmix.policies must be a map.",
            {"file_path": str(registry_path)},
        )

    pack_cache: Dict[str, Dict[str, Any]] = {}
    matrix_index: Dict[str, Tuple[str, Dict[str, Any]]] = {}

    for policy_id, entry in policies.items():
        if not isinstance(policy_id, str) or not policy_id.startswith("POLICY.DOWNMIX."):
            _add_issue(
                issues,
                ISSUE_POLICY_SCHEMA_INVALID,
                "error",
                "Policy registry keys must start with POLICY.DOWNMIX.",
                {"file_path": str(registry_path), "policy_id": policy_id},
            )

        if not isinstance(entry, dict):
            _add_issue(
                issues,
                ISSUE_POLICY_SCHEMA_INVALID,
                "error",
                "Policy entry must be a map.",
                {"file_path": str(registry_path), "policy_id": policy_id},
            )
            continue

        file_rel = entry.get("file")
        if not isinstance(file_rel, str):
            _add_issue(
                issues,
                ISSUE_POLICY_FILE_MISSING,
                "error",
                "Policy entry missing file path.",
                {"file_path": str(registry_path), "policy_id": policy_id},
            )
            continue

        pack_path = registry_path.parent / file_rel
        if not pack_path.exists():
            _add_issue(
                issues,
                ISSUE_POLICY_FILE_MISSING,
                "error",
                "Policy pack file does not exist.",
                {"file_path": str(pack_path), "policy_id": policy_id},
            )
            continue

        pack_data = _load_yaml(pack_path, issues)
        if pack_data is None:
            continue

        pack = _validate_pack(
            pack_path,
            pack_data,
            policy_id,
            layouts,
            speakers,
            issues,
            strict=strict,
        )
        if pack is not None:
            pack_cache[policy_id] = pack
            matrices = pack.get("matrices")
            if isinstance(matrices, dict):
                for matrix_id, matrix in matrices.items():
                    if isinstance(matrix_id, str) and isinstance(matrix, dict):
                        matrix_index.setdefault(matrix_id, (policy_id, matrix))

        supports_source = entry.get("supports_source_layouts")
        supports_target = entry.get("supports_target_layouts")
        layouts_known = _layouts_set(layouts)
        for label, items in (
            ("supports_source_layouts", supports_source),
            ("supports_target_layouts", supports_target),
        ):
            if not isinstance(items, list):
                _add_issue(
                    issues,
                    ISSUE_DOWNMIX_LAYOUT_UNKNOWN,
                    "error",
                    f"{label} must be a list of layout IDs.",
                    {"file_path": str(pack_path), "policy_id": policy_id},
                )
                continue
            for layout_id in items:
                if layout_id not in layouts_known:
                    _add_issue(
                        issues,
                        ISSUE_DOWNMIX_LAYOUT_UNKNOWN,
                        "error",
                        f"Unknown layout id in {label}.",
                        {
                            "file_path": str(pack_path),
                            "policy_id": policy_id,
                            "layout_id": layout_id,
                        },
                    )

    default_map = downmix.get("default_policy_by_source_layout")
    if isinstance(default_map, dict):
        layouts_known = _layouts_set(layouts)
        for layout_id, policy_id in default_map.items():
            if layout_id not in layouts_known:
                _add_issue(
                    issues,
                    ISSUE_DOWNMIX_LAYOUT_UNKNOWN,
                    "error",
                    "Default policy map references unknown layout.",
                    {"file_path": str(registry_path), "layout_id": layout_id},
                )
            if policy_id not in policies:
                _add_issue(
                    issues,
                    ISSUE_DOWNMIX_POLICY_ID_MISMATCH,
                    "error",
                    "Default policy map references unknown policy.",
                    {"file_path": str(registry_path), "policy_id": policy_id},
                )
    else:
        _add_issue(
            issues,
            ISSUE_POLICY_SCHEMA_INVALID,
            "error",
            "default_policy_by_source_layout must be a map.",
            {"file_path": str(registry_path)},
        )

    conversions = downmix.get("conversions")
    if not isinstance(conversions, list):
        _add_issue(
            issues,
            ISSUE_POLICY_SCHEMA_INVALID,
            "error",
            "conversions must be a list.",
            {"file_path": str(registry_path)},
        )
        conversions = []

    layouts_known = _layouts_set(layouts)
    for conversion in conversions:
        if not isinstance(conversion, dict):
            _add_issue(
                issues,
                ISSUE_POLICY_SCHEMA_INVALID,
                "error",
                "Conversion entry must be a map.",
                {"file_path": str(registry_path)},
            )
            continue

        source_layout_id = conversion.get("source_layout_id")
        target_layout_id = conversion.get("target_layout_id")
        policy_id = conversion.get("policy_id")
        matrix_id = conversion.get("matrix_id")

        if source_layout_id not in layouts_known or target_layout_id not in layouts_known:
            _add_issue(
                issues,
                ISSUE_DOWNMIX_LAYOUT_UNKNOWN,
                "error",
                "Conversion references unknown layout.",
                {
                    "file_path": str(registry_path),
                    "source_layout_id": source_layout_id,
                    "target_layout_id": target_layout_id,
                },
            )

        if policy_id not in policies:
            _add_issue(
                issues,
                ISSUE_DOWNMIX_POLICY_ID_MISMATCH,
                "error",
                "Conversion references unknown policy id.",
                {"file_path": str(registry_path), "policy_id": policy_id},
            )
            continue

        pack = pack_cache.get(policy_id)
        if pack is None:
            continue

        matrices = pack.get("matrices") if isinstance(pack, dict) else None
        if not isinstance(matrices, dict) or matrix_id not in matrices:
            _add_issue(
                issues,
                ISSUE_DOWNMIX_MATRIX_ID_MISSING,
                "error",
                "Conversion references a matrix_id not found in the pack.",
                {
                    "file_path": str(registry_path),
                    "policy_id": policy_id,
                    "matrix_id": matrix_id,
                },
            )
            continue

        matrix = matrices.get(matrix_id)
        if isinstance(matrix, dict):
            matrix_source = matrix.get("source_layout_id")
            matrix_target = matrix.get("target_layout_id")
            if matrix_source != source_layout_id or matrix_target != target_layout_id:
                _add_issue(
                    issues,
                    ISSUE_DOWNMIX_LAYOUT_SPEAKER_MISMATCH,
                    "error",
                    "Matrix layout IDs do not match conversion layout IDs.",
                    {
                        "file_path": str(registry_path),
                        "policy_id": policy_id,
                        "matrix_id": matrix_id,
                        "source_layout_id": source_layout_id,
                        "target_layout_id": target_layout_id,
                    },
                )

    composition_paths = downmix.get("composition_paths")
    if isinstance(composition_paths, list):
        for path_entry in composition_paths:
            if not isinstance(path_entry, dict):
                _add_issue(
                    issues,
                    ISSUE_POLICY_SCHEMA_INVALID,
                    "error",
                    "composition_paths entry must be a map.",
                    {"file_path": str(registry_path)},
                )
                continue

            path_source = path_entry.get("source_layout_id")
            path_target = path_entry.get("target_layout_id")
            steps = path_entry.get("steps")
            if not isinstance(steps, list) or not steps:
                _add_issue(
                    issues,
                    ISSUE_POLICY_SCHEMA_INVALID,
                    "error",
                    "composition_paths.steps must be a non-empty list.",
                    {"file_path": str(registry_path)},
                )
                continue

            prev_target = None
            for idx, step in enumerate(steps):
                if not isinstance(step, dict):
                    _add_issue(
                        issues,
                        ISSUE_POLICY_SCHEMA_INVALID,
                        "error",
                        "composition step must be a map.",
                        {"file_path": str(registry_path)},
                    )
                    continue

                step_source = step.get("source_layout_id")
                step_target = step.get("target_layout_id")
                matrix_id = step.get("matrix_id")

                if matrix_id not in matrix_index:
                    _add_issue(
                        issues,
                        ISSUE_DOWNMIX_MATRIX_ID_MISSING,
                        "error",
                        "Composition step references missing matrix_id.",
                        {
                            "file_path": str(registry_path),
                            "matrix_id": matrix_id,
                        },
                    )

                if idx == 0 and step_source != path_source:
                    _add_issue(
                        issues,
                        ISSUE_DOWNMIX_LAYOUT_SPEAKER_MISMATCH,
                        "error",
                        "Composition path source does not match first step source.",
                        {
                            "file_path": str(registry_path),
                            "source_layout_id": path_source,
                            "matrix_id": matrix_id,
                        },
                    )

                if prev_target is not None and step_source != prev_target:
                    _add_issue(
                        issues,
                        ISSUE_DOWNMIX_LAYOUT_SPEAKER_MISMATCH,
                        "error",
                        "Composition path steps are not contiguous.",
                        {
                            "file_path": str(registry_path),
                            "matrix_id": matrix_id,
                        },
                    )

                prev_target = step_target

            if prev_target is not None and prev_target != path_target:
                _add_issue(
                    issues,
                    ISSUE_DOWNMIX_LAYOUT_SPEAKER_MISMATCH,
                    "error",
                    "Composition path target does not match final step target.",
                    {
                        "file_path": str(registry_path),
                        "target_layout_id": path_target,
                    },
                )

    return _result(registry_path, issues)


def _result(registry_path: Path, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    error_count = sum(1 for issue in issues if issue["severity_label"] == "error")
    warn_count = sum(1 for issue in issues if issue["severity_label"] == "warn")
    return {
        "registry_file": str(registry_path),
        "ok": error_count == 0,
        "issue_counts": {"error": error_count, "warn": warn_count},
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate downmix policy registries and referenced policy packs."
    )
    parser.add_argument(
        "registry_file",
        nargs="?",
        default=None,
        help="Path to the downmix registry YAML.",
    )
    parser.add_argument(
        "--registry",
        dest="registry",
        default=None,
        help=(
            "Optional explicit path to the downmix registry YAML. "
            "If provided, this overrides the positional registry_file."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable stricter warnings (including sum_abs soft limits).",
    )
    args = parser.parse_args()

    registry_value = args.registry or args.registry_file or "ontology/policies/downmix.yaml"
    registry_path = Path(registry_value)
    result = validate_registry(registry_path, strict=args.strict)
    print(json.dumps(result, indent=2))
    return 1 if result["issue_counts"]["error"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
