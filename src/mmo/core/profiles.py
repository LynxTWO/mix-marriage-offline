"""User style/safety profiles for MMO (DoD 4.7).

Profiles translate user "intent and vibe" into safe parameter ranges and
preflight gate threshold overrides.  They live in ``ontology/profiles.yaml``
and are validated against ``schemas/profile.schema.json``.

Public API
----------
- ``load_profiles(path=None)``            — returns sorted dict of all profiles
- ``list_profiles(path=None)``            — returns sorted list of profile summary rows
- ``get_profile(profile_id, path=None)``  — returns one profile or raises ValueError
- ``apply_to_gates(profile, options)``    — merges profile gate_overrides into options dict
- ``validate_against_scene(profile, scene)`` — checks scene compatibility; returns issues list
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

from mmo.resources import ontology_dir, schemas_dir


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_registry_path(path: Path | None) -> Path:
    if path is None:
        return ontology_dir() / "profiles.yaml"
    if path.is_absolute():
        return path
    from mmo.resources import data_root
    return data_root() / path


def _load_yaml_object(path: Path, *, label: str) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load user profile registries.")
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    except OSError as exc:
        raise ValueError(f"Failed to read {label} YAML from {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"{label} YAML is not valid: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} YAML root must be a mapping: {path}")
    return payload


def _load_json_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to load schema from {schema_path}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"Schema JSON must be an object: {schema_path}")
    return schema


def _validate_payload_against_schema(
    payload: dict[str, Any],
    *,
    schema_path: Path,
    payload_name: str,
) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required to validate user profile registries.")
    schema = _load_json_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda err: (list(err.path), err.message),
    )
    if not errors:
        return
    lines: list[str] = []
    for err in errors:
        path = ".".join(str(item) for item in err.path) or "$"
        lines.append(f"- {path}: {err.message}")
    details = "\n".join(lines)
    raise ValueError(f"{payload_name} schema validation failed:\n{details}")


def _profiles_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, dict):
        return {}
    return {
        profile_id: dict(profile_payload)
        for profile_id, profile_payload in raw_profiles.items()
        if isinstance(profile_id, str) and isinstance(profile_payload, dict)
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_profiles(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load and validate all user profiles from the registry.

    Returns a stable dict keyed by ``profile_id``, sorted alphabetically.
    """
    resolved_path = _resolve_registry_path(path)
    payload = _load_yaml_object(resolved_path, label="User profile registry")
    _validate_payload_against_schema(
        payload,
        schema_path=schemas_dir() / "profile.schema.json",
        payload_name="User profile registry",
    )
    profiles = _profiles_map(payload)
    return {profile_id: dict(profiles[profile_id]) for profile_id in sorted(profiles.keys())}


def list_profiles(path: Path | None = None) -> list[dict[str, Any]]:
    """Return a list of summary dicts for all profiles, sorted by profile_id."""
    profiles = load_profiles(path)
    rows: list[dict[str, Any]] = []
    for profile_id in sorted(profiles.keys()):
        entry = profiles[profile_id]
        row: dict[str, Any] = {
            "profile_id": profile_id,
            "label": entry.get("label", ""),
            "description": entry.get("description", ""),
            "style_intent": list(entry.get("style_intent", [])),
        }
        rows.append(row)
    return rows


def get_profile(profile_id: str, path: Path | None = None) -> dict[str, Any]:
    """Return one profile by ID, or raise ``ValueError`` if unknown."""
    normalized = profile_id.strip() if isinstance(profile_id, str) else ""
    if not normalized:
        raise ValueError("profile_id must be a non-empty string.")
    profiles = load_profiles(path)
    payload = profiles.get(normalized)
    if isinstance(payload, dict):
        row: dict[str, Any] = {"profile_id": normalized}
        row.update(payload)
        return row
    known_ids = sorted(profiles.keys())
    if known_ids:
        raise ValueError(
            f"Unknown user profile_id: {normalized}. "
            f"Known profile_ids: {', '.join(known_ids)}"
        )
    raise ValueError(
        f"Unknown user profile_id: {normalized}. No user profiles are available."
    )


def apply_to_gates(
    profile: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    """Merge a profile's ``gate_overrides`` into a preflight *options* dict.

    Returns a new dict — the input ``options`` is not mutated.  Profile values
    take precedence over existing keys in ``options``.

    Parameters
    ----------
    profile:
        A profile dict as returned by :func:`get_profile`.
    options:
        Existing preflight options dict (may be empty).

    Returns
    -------
    dict
        New options dict with profile overrides merged in.
    """
    result = dict(options)
    gate_overrides = profile.get("gate_overrides")
    if isinstance(gate_overrides, dict):
        for key, value in gate_overrides.items():
            if isinstance(key, str) and key:
                result[key] = value
    return result


def validate_against_scene(
    profile: dict[str, Any],
    scene: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check scene compatibility against the profile's safety constraints.

    Inspects scene metadata (confidence, correlation, polarity) against the
    profile's gate_override thresholds and returns a list of issue dicts.
    Each issue has ``severity`` (``"error"`` | ``"warn"`` | ``"info"``),
    ``code``, and ``message`` keys.

    Parameters
    ----------
    profile:
        A profile dict as returned by :func:`get_profile`.
    scene:
        A scene or analysis-report dict.

    Returns
    -------
    list[dict]
        Sorted list of issue dicts; empty when the scene is fully compatible.
    """
    issues: list[dict[str, Any]] = []
    gate_overrides = profile.get("gate_overrides", {})
    if not isinstance(gate_overrides, dict):
        gate_overrides = {}

    # --- Confidence check ---
    conf_warn = float(gate_overrides.get("confidence_warn_below", 0.5))
    conf_error = float(gate_overrides.get("confidence_error_below", 0.2))

    metadata = scene.get("metadata")
    overall_conf: float | None = None
    if isinstance(metadata, dict):
        raw_conf = metadata.get("confidence")
        if isinstance(raw_conf, (int, float)):
            overall_conf = float(raw_conf)

    # Scene metadata owns this check when present. Recommendation confidence is
    # only a fallback for older or partial artifacts that do not carry a scene
    # summary yet.
    recommendations = scene.get("recommendations")
    if overall_conf is None and isinstance(recommendations, list) and recommendations:
        scores: list[float] = []
        for rec in recommendations:
            if isinstance(rec, dict):
                c = rec.get("confidence")
                if isinstance(c, (int, float)):
                    scores.append(float(c))
        if scores:
            overall_conf = sum(scores) / len(scores)

    if overall_conf is not None:
        if overall_conf < conf_error:
            issues.append({
                "severity": "error",
                "code": "PROFILE.SCENE_CONFIDENCE_TOO_LOW",
                "message": (
                    f"Scene confidence {overall_conf:.2f} is below profile error "
                    f"threshold {conf_error:.2f} for profile "
                    f"{profile.get('profile_id', '?')}."
                ),
            })
        elif overall_conf < conf_warn:
            issues.append({
                "severity": "warn",
                "code": "PROFILE.SCENE_CONFIDENCE_LOW",
                "message": (
                    f"Scene confidence {overall_conf:.2f} is below profile warn "
                    f"threshold {conf_warn:.2f} for profile "
                    f"{profile.get('profile_id', '?')}."
                ),
            })

    # Correlation is a scene-wide polarity risk, not a recommendation-quality
    # score. Leave it separate so strong rec confidence cannot hide phase risk.
    # --- Correlation / polarity check ---
    corr_warn = float(gate_overrides.get("correlation_warn_lte", -0.2))
    corr_error = float(gate_overrides.get("correlation_error_lte", -0.6))

    correlation_value: float | None = None
    if isinstance(metadata, dict):
        raw_corr = metadata.get("correlation")
        if isinstance(raw_corr, (int, float)):
            correlation_value = float(raw_corr)

    if correlation_value is not None:
        if correlation_value <= corr_error:
            issues.append({
                "severity": "error",
                "code": "PROFILE.SCENE_CORRELATION_HIGH_RISK",
                "message": (
                    f"Scene correlation {correlation_value:.3f} exceeds profile "
                    f"error threshold {corr_error:.3f}."
                ),
            })
        elif correlation_value <= corr_warn:
            issues.append({
                "severity": "warn",
                "code": "PROFILE.SCENE_CORRELATION_RISK",
                "message": (
                    f"Scene correlation {correlation_value:.3f} is below profile "
                    f"warn threshold {corr_warn:.3f}."
                ),
            })

    # Sort deterministically so review output and fixture expectations stay
    # comparable when more than one compatibility gate fires.
    # Stable sort: error before warn, then by code
    _severity_order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda iss: (_severity_order.get(iss.get("severity", "info"), 2), iss.get("code", "")))
    return issues
