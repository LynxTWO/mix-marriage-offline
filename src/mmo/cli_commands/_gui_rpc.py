from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

from mmo.cli_commands._helpers import _load_json_object, _write_json_file
from mmo.cli_commands._project import (
    _run_project_build_gui,
    _run_project_load,
    _run_project_pack,
    _run_project_render_run,
    _run_project_save,
    _run_project_show,
    _run_project_validate,
    _run_project_write_render_request,
)
from mmo.core.env_doctor import build_env_doctor_report
from mmo.core.intent_params import load_intent_params, validate_scene_intent
from mmo.core.locks import (
    SCENE_BUILD_LOCKS_VERSION,
    apply_scene_build_locks,
    load_scene_build_locks,
)
from mmo.core.plugin_market import (
    build_plugin_market_list_payload,
    install_plugin_market_entry,
    update_plugin_market_snapshot,
)
from mmo.core.roles import load_roles
from mmo.core.scene_editor import set_intent as edit_scene_set_intent
from mmo.resources import ontology_dir

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency
    yaml = None

try:
    from mmo import __version__ as _MMO_VERSION
except Exception:  # pragma: no cover - import should succeed in normal installs
    _MMO_VERSION = "unknown"

__all__ = ["_run_gui_rpc"]


class _RpcRequestError(ValueError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _RpcMethodError(RuntimeError):
    def __init__(self, *, message: str) -> None:
        super().__init__(message)
        self.message = message


_RPC_VERSION = "1"
_PROJECT_WRITE_RENDER_REQUEST_ALLOWED_SET_KEYS: frozenset[str] = frozenset(
    {
        "dry_run",
        "lfe_derivation_profile_id",
        "lfe_mode",
        "max_theoretical_quality",
        "plugin_chain",
        "policies",
        "target_ids",
        "target_layout_ids",
    }
)
_SCENE_LOCKS_FILENAME = "scene_locks.yaml"
_SCENE_PERSPECTIVE_VALUES: tuple[str, ...] = (
    "audience",
    "on_stage",
    "in_band",
    "in_orchestra",
)

_RPC_DISCOVER_METHOD_DETAILS: dict[str, dict[str, Any]] = {
    "env.doctor": {
        "params_schema": {
            "required": {},
            "optional": {},
            "examples": [
                {},
            ],
        },
        "result_shape": {
            "keys": [
                "checks",
                "env_overrides",
                "paths",
                "python",
            ],
        },
    },
    "project.build_gui": {
        "params_schema": {
            "required": {
                "pack_out": "string",
                "project_dir": "string",
            },
            "optional": {
                "event_log": "boolean",
                "event_log_force": "boolean",
                "force": "boolean",
                "include_plugins": "boolean",
                "include_plugin_layouts": "boolean",
                "include_plugin_layout_snapshots": "boolean",
                "include_plugin_ui_hints": "boolean",
                "plugins": "string",
                "scan": "boolean",
                "scan_out": "string",
                "scan_stems": "string",
            },
            "examples": [
                {
                    "pack_out": "C:/mmo/project/project_gui.zip",
                    "project_dir": "C:/mmo/project",
                },
                {
                    "event_log": True,
                    "event_log_force": True,
                    "force": True,
                    "pack_out": "C:/mmo/project/project_gui.zip",
                    "project_dir": "C:/mmo/project",
                    "include_plugins": True,
                    "include_plugin_layouts": True,
                    "include_plugin_layout_snapshots": False,
                    "include_plugin_ui_hints": True,
                    "plugins": "C:/mmo/plugins",
                    "scan": True,
                    "scan_out": "C:/mmo/project/report.json",
                    "scan_stems": "C:/mmo/stems",
                },
            ],
        },
        "result_shape": {
            "keys": [
                "ok",
                "pack_out",
                "paths_written",
                "project_dir",
                "steps",
            ],
        },
    },
    "project.render_run": {
        "params_schema": {
            "required": {
                "project_dir": "string",
            },
            "optional": {
                "event_log": "boolean",
                "event_log_force": "boolean",
                "execute": "boolean",
                "execute_force": "boolean",
                "execute_out": "string",
                "force": "boolean",
                "preflight": "boolean",
                "preflight_force": "boolean",
                "qa_out": "boolean",
            },
            "examples": [
                {
                    "force": True,
                    "project_dir": "C:/mmo/project",
                },
                {
                    "event_log": True,
                    "event_log_force": True,
                    "execute": True,
                    "execute_force": True,
                    "force": True,
                    "project_dir": "C:/mmo/project",
                    "preflight": True,
                    "preflight_force": True,
                    "qa_out": True,
                },
                {
                    "execute_out": "C:/mmo/project/renders/render_execute.json",
                    "force": True,
                    "project_dir": "C:/mmo/project",
                },
            ],
        },
        "result_shape": {
            "keys": [
                "job_count",
                "paths_written",
                "plan_id",
                "targets",
            ],
            "optional_keys": [
                "run_id",
            ],
        },
    },
    "project.pack": {
        "params_schema": {
            "required": {
                "out": "string",
                "project_dir": "string",
            },
            "optional": {
                "force": "boolean",
                "include_wavs": "boolean",
            },
            "examples": [
                {
                    "out": "C:/mmo/project/project_pack.zip",
                    "project_dir": "C:/mmo/project",
                },
            ],
        },
        "result_shape": {
            "keys": [
                "file_count",
                "ok",
                "out",
            ],
        },
    },
    "project.show": {
        "params_schema": {
            "required": {
                "project_dir": "string",
            },
            "optional": {},
            "examples": [
                {
                    "project_dir": "C:/mmo/project",
                },
            ],
        },
        "result_shape": {
            "keys": [
                "artifacts",
                "last_built_markers",
                "project_dir",
                "schema_versions",
            ],
        },
    },
    "project.save": {
        "params_schema": {
            "required": {
                "project_dir": "string",
            },
            "optional": {
                "force": "boolean",
                "session": "string",
            },
            "examples": [
                {
                    "project_dir": "C:/mmo/project",
                },
                {
                    "force": True,
                    "project_dir": "C:/mmo/project",
                    "session": "C:/mmo/project/project_session.json",
                },
            ],
        },
        "result_shape": {
            "keys": [
                "history_count",
                "ok",
                "project_dir",
                "receipt_count",
                "scene_path",
                "session_path",
                "written",
            ],
        },
    },
    "project.load": {
        "params_schema": {
            "required": {
                "project_dir": "string",
            },
            "optional": {
                "force": "boolean",
                "session": "string",
            },
            "examples": [
                {
                    "project_dir": "C:/mmo/project",
                },
                {
                    "force": True,
                    "project_dir": "C:/mmo/project",
                    "session": "C:/mmo/project/project_session.json",
                },
            ],
        },
        "result_shape": {
            "keys": [
                "history_count",
                "ok",
                "project_dir",
                "receipt_count",
                "session_path",
                "written",
            ],
        },
    },
    "project.validate": {
        "params_schema": {
            "required": {
                "project_dir": "string",
            },
            "optional": {
                "out": "string",
                "render_compat": "boolean",
            },
            "examples": [
                {
                    "project_dir": "C:/mmo/project",
                },
                {
                    "project_dir": "C:/mmo/project",
                    "render_compat": True,
                },
            ],
        },
        "result_shape": {
            "keys": [
                "checks",
                "ok",
                "project_dir",
                "summary",
            ],
            "optional_keys": [
                "render_compat",
            ],
        },
    },
    "project.write_render_request": {
        "params_schema": {
            "required": {
                "project_dir": "string",
                "set": "object",
            },
            "optional": {},
            "examples": [
                {
                    "project_dir": "C:/mmo/project",
                    "set": {
                        "dry_run": False,
                        "lfe_derivation_profile_id": "LFE_DERIVE.DOLBY_120_LR24_TRIM_10",
                        "lfe_mode": "mono",
                        "max_theoretical_quality": True,
                        "target_ids": [
                            "TARGET.STEREO.2_0",
                            "TARGET.SURROUND.5_1",
                        ],
                        "target_layout_ids": [
                            "LAYOUT.2_0",
                            "LAYOUT.5_1",
                        ],
                        "policies": {
                            "downmix_policy_id": "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
                            "gates_policy_id": "POLICY.GATES.CORE_V0",
                        },
                        "plugin_chain": [
                            {
                                "plugin_id": "gain_v0",
                                "params": {"gain_db": -3.0},
                            }
                        ],
                    },
                },
            ],
        },
        "result_shape": {
            "keys": [
                "ok",
                "project_dir",
                "updated_fields",
                "written",
            ],
            "optional_keys": [
                "dry_run",
                "lfe_derivation_profile_id",
                "lfe_mode",
                "max_theoretical_quality",
                "plugin_chain",
                "policies",
                "target_ids",
                "target_layout_ids",
            ],
        },
    },
    "plugin.market.list": {
        "params_schema": {
            "required": {},
            "optional": {
                "index": "string",
                "plugin_dir": "string",
                "plugins": "string",
            },
            "examples": [
                {},
                {
                    "plugins": "C:/mmo/plugins",
                },
                {
                    "index": "C:/mmo/ontology/plugin_index.yaml",
                    "plugins": "C:/mmo/plugins",
                },
            ],
        },
        "result_shape": {
            "keys": [
                "entries",
                "entry_count",
                "index_path",
                "installed_count",
                "market_id",
                "schema_version",
            ],
            "optional_keys": [
                "installed_scan_error",
                "plugin_dir",
                "plugins_dir",
            ],
        },
    },
    "plugin.market.update": {
        "params_schema": {
            "required": {},
            "optional": {
                "index": "string",
                "out": "string",
            },
            "examples": [
                {},
                {
                    "out": "C:/mmo/cache/plugin_index.snapshot.json",
                },
            ],
        },
        "result_shape": {
            "keys": [
                "entry_count",
                "market_id",
                "out_path",
                "schema_version",
                "sha256",
            ],
            "optional_keys": [
                "index_path",
            ],
        },
    },
    "plugin.market.install": {
        "params_schema": {
            "required": {
                "plugin_id": "string",
            },
            "optional": {
                "index": "string",
                "plugins": "string",
            },
            "examples": [
                {
                    "plugin_id": "PLUGIN.RENDERER.GAIN_TRIM",
                },
                {
                    "plugin_id": "PLUGIN.RENDERER.GAIN_TRIM",
                    "plugins": "C:/mmo/plugins",
                },
            ],
        },
        "result_shape": {
            "keys": [
                "changed",
                "manifest_path",
                "module_path",
                "plugin_id",
                "plugins_dir",
                "schema_version",
            ],
            "optional_keys": [
                "copied_files",
                "index_path",
                "market_id",
            ],
        },
    },
    "scene.locks.inspect": {
        "params_schema": {
            "required": {
                "project_dir": "string",
            },
            "optional": {},
            "examples": [
                {
                    "project_dir": "C:/mmo/project",
                },
            ],
        },
        "result_shape": {
            "keys": [
                "objects",
                "perspective",
                "perspective_values",
                "project_dir",
                "role_options",
                "scene_locks_path",
                "scene_path",
            ],
            "optional_keys": [
                "scene_preview",
            ],
        },
    },
    "scene.locks.save": {
        "params_schema": {
            "required": {
                "project_dir": "string",
                "rows": "array",
            },
            "optional": {
                "perspective": "string",
            },
            "examples": [
                {
                    "project_dir": "C:/mmo/project",
                    "perspective": "in_band",
                    "rows": [
                        {
                            "front_only": True,
                            "height_cap": 0.0,
                            "role_id": "ROLE.DRUM.KICK",
                            "stem_id": "STEM.KICK",
                            "surround_cap": 0.0,
                        }
                    ],
                },
            ],
        },
        "result_shape": {
            "keys": [
                "overrides_count",
                "perspective",
                "project_dir",
                "scene_locks_path",
                "scene_path",
                "written",
            ],
            "optional_keys": [
                "scene_preview",
            ],
        },
    },
    "rpc.discover": {
        "params_schema": {
            "required": {},
            "optional": {},
            "examples": [
                {},
            ],
        },
        "result_shape": {
            "keys": [
                "method_details",
                "methods",
                "rpc_version",
                "server_build",
            ],
        },
    },
}


def _server_build() -> str:
    if isinstance(_MMO_VERSION, str) and _MMO_VERSION.strip():
        return _MMO_VERSION.strip()
    return "unknown"


def _build_rpc_discover_payload() -> dict[str, Any]:
    methods = sorted(_RPC_METHOD_HANDLERS.keys())
    return {
        "rpc_version": _RPC_VERSION,
        "server_build": _server_build(),
        "methods": methods,
        "method_details": {
            method: _RPC_DISCOVER_METHOD_DETAILS[method]
            for method in methods
        },
    }


def _error_response(
    request_id: Any,
    *,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
        },
        "id": request_id,
        "ok": False,
    }


def _validate_allowed_params(
    *,
    method: str,
    params: dict[str, Any],
    allowed: set[str],
) -> None:
    unknown = sorted(
        key
        for key in params
        if key not in allowed
    )
    if unknown:
        joined = ", ".join(unknown)
        raise _RpcRequestError(
            code="RPC.INVALID_PARAMS",
            message=f"{method} received unknown params: {joined}",
        )


def _require_str_param(*, method: str, params: dict[str, Any], name: str) -> str:
    raw_value = params.get(name)
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise _RpcRequestError(
            code="RPC.INVALID_PARAMS",
            message=f"{method} param '{name}' must be a non-empty string.",
        )
    return raw_value.strip()


def _require_object_param(
    *,
    method: str,
    params: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    raw_value = params.get(name)
    if not isinstance(raw_value, dict):
        raise _RpcRequestError(
            code="RPC.INVALID_PARAMS",
            message=f"{method} param '{name}' must be a JSON object.",
        )
    return dict(raw_value)


def _optional_str_param(
    *,
    method: str,
    params: dict[str, Any],
    name: str,
    default: str | None = None,
) -> str | None:
    if name not in params:
        return default
    raw_value = params.get(name)
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise _RpcRequestError(
            code="RPC.INVALID_PARAMS",
            message=f"{method} param '{name}' must be a non-empty string when provided.",
        )
    return raw_value.strip()


def _optional_bool_param(
    *,
    method: str,
    params: dict[str, Any],
    name: str,
    default: bool,
) -> bool:
    if name not in params:
        return default
    raw_value = params.get(name)
    if not isinstance(raw_value, bool):
        raise _RpcRequestError(
            code="RPC.INVALID_PARAMS",
            message=f"{method} param '{name}' must be a boolean.",
        )
    return raw_value


def _call_json_command(
    *,
    method: str,
    invoke: Callable[[], int],
    accepted_exit_codes: tuple[int, ...] = (0,),
) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = invoke()

    if exit_code not in accepted_exit_codes:
        err_text = stderr.getvalue().strip()
        if err_text:
            raise _RpcMethodError(message=err_text)
        raise _RpcMethodError(
            message=f"{method} failed with exit code {exit_code}.",
        )

    payload_text = stdout.getvalue().strip()
    if not payload_text:
        return {}

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise _RpcMethodError(
            message=f"{method} returned invalid JSON output.",
        ) from exc

    if not isinstance(payload, dict):
        raise _RpcMethodError(
            message=f"{method} returned non-object JSON output.",
        )
    return payload


def _coerce_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_unit_float(value: Any, *, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return default


def _coerce_confidence(value: Any) -> float:
    normalized = _coerce_unit_float(value, default=0.0)
    return round(float(normalized if normalized is not None else 0.0), 3)


def _scene_project_paths(project_dir: Path) -> tuple[Path, Path]:
    return (
        project_dir / "drafts" / "scene.draft.json",
        project_dir / _SCENE_LOCKS_FILENAME,
    )


def _load_scene_from_project(project_dir: Path) -> tuple[Path, dict[str, Any]]:
    scene_path, _ = _scene_project_paths(project_dir)
    if not scene_path.is_file():
        raise _RpcMethodError(
            message=(
                "Scene draft file is missing: "
                f"{scene_path.resolve().as_posix()} (run project init/refresh first)."
            ),
        )
    return scene_path, _load_json_object(scene_path, label="Scene")


def _load_scene_locks_overrides(scene_locks_path: Path) -> dict[str, dict[str, Any]]:
    if not scene_locks_path.is_file():
        return {}
    payload = load_scene_build_locks(scene_locks_path)
    overrides = payload.get("overrides")
    if not isinstance(overrides, dict):
        return {}
    return {
        stem_id: dict(override)
        for stem_id, override in overrides.items()
        if isinstance(stem_id, str) and stem_id and isinstance(override, dict)
    }


def _scene_perspective(scene_payload: dict[str, Any]) -> str:
    intent = scene_payload.get("intent")
    perspective = _coerce_string(
        intent.get("perspective") if isinstance(intent, dict) else None,
    ).strip().lower()
    if perspective in _SCENE_PERSPECTIVE_VALUES:
        return perspective
    return "audience"


def _scene_role_options() -> list[dict[str, str]]:
    payload = load_roles(ontology_dir() / "roles.yaml")
    roles = payload.get("roles")
    if not isinstance(roles, dict):
        return []
    rows: list[dict[str, str]] = []
    for role_id in sorted(roles.keys()):
        if role_id == "_meta":
            continue
        role_entry = roles.get(role_id)
        if not isinstance(role_id, str) or not role_id.strip() or not isinstance(role_entry, dict):
            continue
        label = _coerce_string(role_entry.get("label")).strip() or role_id
        rows.append({"role_id": role_id, "label": label})
    return rows


def _override_surround_cap(override: dict[str, Any]) -> float | None:
    caps = override.get("surround_send_caps")
    if not isinstance(caps, dict):
        return None
    side = _coerce_unit_float(caps.get("side_max_gain"))
    rear = _coerce_unit_float(caps.get("rear_max_gain"))
    if side is None and rear is None:
        return None
    return round(
        max(
            float(side if side is not None else 0.0),
            float(rear if rear is not None else 0.0),
        ),
        3,
    )


def _override_height_cap(override: dict[str, Any]) -> float | None:
    caps = override.get("height_send_caps")
    if not isinstance(caps, dict):
        return None
    values = [
        _coerce_unit_float(caps.get("top_max_gain")),
        _coerce_unit_float(caps.get("top_front_max_gain")),
        _coerce_unit_float(caps.get("top_rear_max_gain")),
    ]
    normalized = [float(value) for value in values if value is not None]
    if not normalized:
        return None
    return round(max(normalized), 3)


def _scene_lock_rows(
    scene_payload: dict[str, Any],
    overrides: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    objects = scene_payload.get("objects")
    if not isinstance(objects, list):
        return []

    rows: list[dict[str, Any]] = []
    for row in objects:
        if not isinstance(row, dict):
            continue
        stem_id = _coerce_string(row.get("stem_id")).strip()
        if not stem_id:
            continue
        object_id = _coerce_string(row.get("object_id")).strip() or f"OBJ.{stem_id}"
        label = _coerce_string(row.get("label")).strip() or object_id
        intent = row.get("intent")
        confidence_raw = (
            intent.get("confidence")
            if isinstance(intent, dict)
            else row.get("confidence")
        )
        inferred_role_id = _coerce_string(row.get("role_id")).strip()
        override = overrides.get(stem_id)
        override_payload = override if isinstance(override, dict) else {}
        role_override_id = _coerce_string(override_payload.get("role_id")).strip() or None
        surround_cap_override = _override_surround_cap(override_payload)
        height_cap_override = _override_height_cap(override_payload)
        rows.append(
            {
                "confidence": _coerce_confidence(confidence_raw),
                "height_cap_override": height_cap_override,
                "inferred_role_id": inferred_role_id or None,
                "label": label,
                "object_id": object_id,
                "role_effective_id": role_override_id or (inferred_role_id or None),
                "role_override_id": role_override_id,
                "stem_id": stem_id,
                "surround_cap_override": surround_cap_override,
                "front_only_override": bool(
                    surround_cap_override is not None and surround_cap_override <= 0.0
                ),
            }
        )
    rows.sort(key=lambda item: (item["object_id"], item["stem_id"]))
    return rows


def _scene_preview_payload(scene_payload: dict[str, Any]) -> dict[str, Any] | None:
    from mmo.core.ui_bundle import _scene_preview_payload as _build_scene_preview_payload  # noqa: WPS433

    try:
        preview = _build_scene_preview_payload(scene_payload)
    except (RuntimeError, ValueError):
        return None
    return preview if isinstance(preview, dict) else None


def _build_scene_locks_inspect_payload(project_dir: Path) -> dict[str, Any]:
    resolved_project_dir = project_dir.resolve()
    if not resolved_project_dir.exists() or not resolved_project_dir.is_dir():
        raise _RpcMethodError(
            message=(
                "MMO could not find that project folder. "
                f"Expected a real workspace project at {resolved_project_dir.as_posix()}. "
                "Run Validate and Scene first, then try Inspect Scene Locks again."
            ),
        )

    scene_path, scene_payload = _load_scene_from_project(resolved_project_dir)
    _, scene_locks_path = _scene_project_paths(resolved_project_dir)
    overrides = _load_scene_locks_overrides(scene_locks_path)
    rows = _scene_lock_rows(scene_payload, overrides)
    payload: dict[str, Any] = {
        "project_dir": resolved_project_dir.as_posix(),
        "scene_path": scene_path.resolve().as_posix(),
        "scene_locks_path": scene_locks_path.resolve().as_posix(),
        "perspective": _scene_perspective(scene_payload),
        "perspective_values": list(_SCENE_PERSPECTIVE_VALUES),
        "role_options": _scene_role_options(),
        "objects": rows,
        "overrides_count": len(overrides),
    }
    preview = _scene_preview_payload(scene_payload)
    if isinstance(preview, dict):
        payload["scene_preview"] = preview
    return payload


def _normalize_role_override(value: Any) -> str | None:
    role_id = _coerce_string(value).strip()
    if not role_id:
        return None
    if not role_id.startswith("ROLE."):
        raise _RpcRequestError(
            code="RPC.INVALID_PARAMS",
            message=(
                "Scene lock role overrides must start with ROLE. "
                "Leave the field blank if you want MMO to keep its current guess."
            ),
        )
    return role_id


def _merge_scene_lock_rows(
    *,
    rows: list[dict[str, Any]],
    existing_overrides: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {
        stem_id: dict(payload)
        for stem_id, payload in existing_overrides.items()
        if isinstance(stem_id, str) and stem_id and isinstance(payload, dict)
    }
    seen_stem_ids: set[str] = set()
    for raw_row in rows:
        if not isinstance(raw_row, dict):
            raise _RpcRequestError(
                code="RPC.INVALID_PARAMS",
                message="Scene lock rows must be objects.",
            )
        stem_id = _coerce_string(raw_row.get("stem_id")).strip()
        if not stem_id:
            raise _RpcRequestError(
                code="RPC.INVALID_PARAMS",
                message="Each scene lock row needs a stem_id so MMO knows which part you are editing.",
            )
        if stem_id in seen_stem_ids:
            raise _RpcRequestError(
                code="RPC.INVALID_PARAMS",
                message=(
                    "Scene lock rows include the same stem twice: "
                    f"{stem_id}. Remove the duplicate row and save again."
                ),
            )
        seen_stem_ids.add(stem_id)

        row_payload = dict(merged.get(stem_id, {}))
        role_id = _normalize_role_override(raw_row.get("role_id"))
        if role_id is None:
            row_payload.pop("role_id", None)
        else:
            row_payload["role_id"] = role_id

        raw_front_only = raw_row.get("front_only")
        front_only = bool(raw_front_only) if isinstance(raw_front_only, bool) else False
        surround_cap = _coerce_unit_float(raw_row.get("surround_cap"), default=1.0)
        if surround_cap is None:
            surround_cap = 1.0
        if front_only:
            surround_cap = 0.0
        if surround_cap >= 0.999:
            row_payload.pop("surround_send_caps", None)
        else:
            row_payload["surround_send_caps"] = {
                "side_max_gain": round(surround_cap, 3),
                "rear_max_gain": round(surround_cap, 3),
            }

        height_cap = _coerce_unit_float(raw_row.get("height_cap"), default=1.0)
        if height_cap is None:
            height_cap = 1.0
        if height_cap >= 0.999:
            row_payload.pop("height_send_caps", None)
        else:
            row_payload["height_send_caps"] = {
                "top_max_gain": round(height_cap, 3),
            }

        if row_payload:
            merged[stem_id] = row_payload
        else:
            merged.pop(stem_id, None)

    return {
        stem_id: merged[stem_id]
        for stem_id in sorted(merged.keys())
    }


def _write_scene_locks_yaml(path: Path, payload: dict[str, Any]) -> None:
    if yaml is None:
        raise _RpcMethodError(
            message=(
                "MMO cannot save scene_locks.yaml because the YAML writer is missing "
                "from this install."
            ),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(payload, sort_keys=False)
    if not rendered.endswith("\n"):
        rendered += "\n"
    path.write_text(rendered, encoding="utf-8")


def _validated_scene_with_updates(
    *,
    scene_payload: dict[str, Any],
    scene_locks_path: Path,
    overrides: dict[str, dict[str, Any]],
    perspective: str | None,
) -> dict[str, Any]:
    updated_scene = apply_scene_build_locks(
        scene_payload,
        {"version": SCENE_BUILD_LOCKS_VERSION, "overrides": overrides},
        locks_path=scene_locks_path,
    )
    if isinstance(perspective, str):
        updated_scene = edit_scene_set_intent(
            updated_scene,
            "scene",
            None,
            "perspective",
            perspective,
        )

    scene_issues = validate_scene_intent(
        updated_scene,
        load_intent_params(ontology_dir() / "intent_params.yaml"),
    )
    if scene_issues:
        issue = scene_issues[0] if isinstance(scene_issues[0], dict) else {}
        issue_id = _coerce_string(issue.get("issue_id")).strip() or "ISSUE.SCENE.INTENT.INVALID"
        message = _coerce_string(issue.get("message")).strip() or "Scene intent validation failed."
        raise _RpcMethodError(
            message=(
                "Scene Lock save stopped because one override would create an invalid scene. "
                f"Why: {issue_id}: {message}. "
                "Next: undo the last lock change or relax that override, then save again."
            ),
        )
    return updated_scene


def _handle_scene_locks_inspect(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="scene.locks.inspect",
        params=params,
        allowed={"project_dir"},
    )
    project_dir = _require_str_param(
        method="scene.locks.inspect",
        params=params,
        name="project_dir",
    )
    try:
        return _build_scene_locks_inspect_payload(Path(project_dir))
    except (RuntimeError, ValueError, OSError) as exc:
        raise _RpcMethodError(message=str(exc)) from exc


def _handle_scene_locks_save(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="scene.locks.save",
        params=params,
        allowed={"project_dir", "perspective", "rows"},
    )
    project_dir = _require_str_param(
        method="scene.locks.save",
        params=params,
        name="project_dir",
    )
    perspective = _optional_str_param(
        method="scene.locks.save",
        params=params,
        name="perspective",
        default=None,
    )
    if isinstance(perspective, str):
        normalized_perspective = perspective.strip().lower()
        if normalized_perspective not in _SCENE_PERSPECTIVE_VALUES:
            expected = ", ".join(_SCENE_PERSPECTIVE_VALUES)
            raise _RpcRequestError(
                code="RPC.INVALID_PARAMS",
                message=(
                    "Scene perspective must be one of: "
                    f"{expected}."
                ),
            )
        perspective = normalized_perspective

    raw_rows = params.get("rows")
    if not isinstance(raw_rows, list):
        raise _RpcRequestError(
            code="RPC.INVALID_PARAMS",
            message="Scene lock save expects 'rows' to be a list.",
        )
    rows = [row for row in raw_rows if isinstance(row, dict)]
    if len(rows) != len(raw_rows):
        raise _RpcRequestError(
            code="RPC.INVALID_PARAMS",
            message="Scene lock rows must be objects.",
        )

    try:
        resolved_project_dir = Path(project_dir).resolve()
        scene_path, scene_payload = _load_scene_from_project(resolved_project_dir)
        _, scene_locks_path = _scene_project_paths(resolved_project_dir)
        existing_overrides = _load_scene_locks_overrides(scene_locks_path)
        merged_overrides = _merge_scene_lock_rows(
            rows=rows,
            existing_overrides=existing_overrides,
        )
        locks_payload = {
            "version": SCENE_BUILD_LOCKS_VERSION,
            "overrides": merged_overrides,
        }
        _write_scene_locks_yaml(scene_locks_path, locks_payload)

        updated_scene = _validated_scene_with_updates(
            scene_payload=scene_payload,
            scene_locks_path=scene_locks_path,
            overrides=merged_overrides,
            perspective=perspective,
        )
        _write_json_file(scene_path, updated_scene)

        preview_payload = _scene_preview_payload(updated_scene)
        return {
            "project_dir": resolved_project_dir.as_posix(),
            "scene_path": scene_path.resolve().as_posix(),
            "scene_locks_path": scene_locks_path.resolve().as_posix(),
            "overrides_count": len(merged_overrides),
            "perspective": _scene_perspective(updated_scene),
            "written": [
                scene_locks_path.resolve().as_posix(),
                scene_path.resolve().as_posix(),
            ],
            "scene_preview": preview_payload if isinstance(preview_payload, dict) else None,
        }
    except _RpcRequestError:
        raise
    except (RuntimeError, ValueError, OSError) as exc:
        raise _RpcMethodError(message=str(exc)) from exc


def _handle_env_doctor(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="env.doctor",
        params=params,
        allowed=set(),
    )
    try:
        return build_env_doctor_report()
    except (RuntimeError, ValueError, OSError) as exc:
        raise _RpcMethodError(message=str(exc)) from exc


def _handle_project_show(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="project.show",
        params=params,
        allowed={"project_dir"},
    )
    project_dir = _require_str_param(method="project.show", params=params, name="project_dir")
    return _call_json_command(
        method="project.show",
        invoke=lambda: _run_project_show(
            project_dir=Path(project_dir),
            output_format="json",
        ),
    )


def _handle_project_save(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="project.save",
        params=params,
        allowed={"project_dir", "session", "force"},
    )
    project_dir = _require_str_param(method="project.save", params=params, name="project_dir")
    session = _optional_str_param(
        method="project.save",
        params=params,
        name="session",
        default=None,
    )
    force = _optional_bool_param(
        method="project.save",
        params=params,
        name="force",
        default=False,
    )
    return _call_json_command(
        method="project.save",
        invoke=lambda: _run_project_save(
            project_dir=Path(project_dir),
            session_path=Path(session) if isinstance(session, str) else None,
            force=force,
        ),
    )


def _handle_project_load(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="project.load",
        params=params,
        allowed={"project_dir", "session", "force"},
    )
    project_dir = _require_str_param(method="project.load", params=params, name="project_dir")
    session = _optional_str_param(
        method="project.load",
        params=params,
        name="session",
        default=None,
    )
    force = _optional_bool_param(
        method="project.load",
        params=params,
        name="force",
        default=False,
    )
    return _call_json_command(
        method="project.load",
        invoke=lambda: _run_project_load(
            project_dir=Path(project_dir),
            session_path=Path(session) if isinstance(session, str) else None,
            force=force,
        ),
    )


def _handle_project_build_gui(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="project.build_gui",
        params=params,
        allowed={
            "project_dir",
            "pack_out",
            "force",
            "scan",
            "scan_stems",
            "scan_out",
            "event_log",
            "event_log_force",
            "include_plugins",
            "include_plugin_layouts",
            "include_plugin_layout_snapshots",
            "include_plugin_ui_hints",
            "plugins",
        },
    )
    project_dir = _require_str_param(
        method="project.build_gui",
        params=params,
        name="project_dir",
    )
    pack_out = _require_str_param(
        method="project.build_gui",
        params=params,
        name="pack_out",
    )
    force = _optional_bool_param(
        method="project.build_gui",
        params=params,
        name="force",
        default=False,
    )
    scan = _optional_bool_param(
        method="project.build_gui",
        params=params,
        name="scan",
        default=False,
    )
    scan_stems = _optional_str_param(
        method="project.build_gui",
        params=params,
        name="scan_stems",
        default=None,
    )
    scan_out = _optional_str_param(
        method="project.build_gui",
        params=params,
        name="scan_out",
        default=None,
    )
    event_log = _optional_bool_param(
        method="project.build_gui",
        params=params,
        name="event_log",
        default=False,
    )
    event_log_force = _optional_bool_param(
        method="project.build_gui",
        params=params,
        name="event_log_force",
        default=False,
    )
    include_plugins = _optional_bool_param(
        method="project.build_gui",
        params=params,
        name="include_plugins",
        default=False,
    )
    include_plugin_layouts = _optional_bool_param(
        method="project.build_gui",
        params=params,
        name="include_plugin_layouts",
        default=False,
    )
    include_plugin_layout_snapshots = _optional_bool_param(
        method="project.build_gui",
        params=params,
        name="include_plugin_layout_snapshots",
        default=False,
    )
    include_plugin_ui_hints = _optional_bool_param(
        method="project.build_gui",
        params=params,
        name="include_plugin_ui_hints",
        default=False,
    )
    plugins = _optional_str_param(
        method="project.build_gui",
        params=params,
        name="plugins",
        default="plugins",
    )

    plugins_dir = Path(plugins) if include_plugins and isinstance(plugins, str) else None
    scan_stems_dir = Path(scan_stems) if isinstance(scan_stems, str) else None
    scan_out_path = Path(scan_out) if isinstance(scan_out, str) else None
    return _call_json_command(
        method="project.build_gui",
        invoke=lambda: _run_project_build_gui(
            project_dir=Path(project_dir),
            pack_out_path=Path(pack_out),
            force=force,
            scan=scan,
            scan_stems_dir=scan_stems_dir,
            scan_out_path=scan_out_path,
            event_log=event_log,
            event_log_force=event_log_force,
            include_plugins=include_plugins,
            include_plugin_layouts=include_plugin_layouts,
            include_plugin_layout_snapshots=include_plugin_layout_snapshots,
            include_plugin_ui_hints=include_plugin_ui_hints,
            plugins_dir=plugins_dir,
        ),
    )


def _handle_project_render_run(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="project.render_run",
        params=params,
        allowed={
            "project_dir",
            "force",
            "event_log",
            "event_log_force",
            "preflight",
            "preflight_force",
            "execute",
            "execute_out",
            "execute_force",
            "qa_out",
        },
    )
    project_dir = _require_str_param(
        method="project.render_run",
        params=params,
        name="project_dir",
    )
    force = _optional_bool_param(
        method="project.render_run",
        params=params,
        name="force",
        default=False,
    )
    event_log = _optional_bool_param(
        method="project.render_run",
        params=params,
        name="event_log",
        default=False,
    )
    event_log_force = _optional_bool_param(
        method="project.render_run",
        params=params,
        name="event_log_force",
        default=False,
    )
    preflight = _optional_bool_param(
        method="project.render_run",
        params=params,
        name="preflight",
        default=False,
    )
    preflight_force = _optional_bool_param(
        method="project.render_run",
        params=params,
        name="preflight_force",
        default=False,
    )
    execute = _optional_bool_param(
        method="project.render_run",
        params=params,
        name="execute",
        default=False,
    )
    execute_out = _optional_str_param(
        method="project.render_run",
        params=params,
        name="execute_out",
        default=None,
    )
    execute_force = _optional_bool_param(
        method="project.render_run",
        params=params,
        name="execute_force",
        default=False,
    )
    qa_out = _optional_bool_param(
        method="project.render_run",
        params=params,
        name="qa_out",
        default=False,
    )
    execute_out_path = Path(execute_out) if isinstance(execute_out, str) else None
    return _call_json_command(
        method="project.render_run",
        invoke=lambda: _run_project_render_run(
            project_dir=Path(project_dir),
            force=force,
            event_log=event_log,
            event_log_force=event_log_force,
            preflight=preflight,
            preflight_force=preflight_force,
            execute=execute,
            execute_out_path=execute_out_path,
            execute_force=execute_force,
            qa=qa_out,
            qa_force=qa_out,
        ),
    )


def _handle_project_validate(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="project.validate",
        params=params,
        allowed={"project_dir", "out", "render_compat"},
    )
    project_dir = _require_str_param(
        method="project.validate",
        params=params,
        name="project_dir",
    )
    out = _optional_str_param(
        method="project.validate",
        params=params,
        name="out",
        default=None,
    )
    render_compat = _optional_bool_param(
        method="project.validate",
        params=params,
        name="render_compat",
        default=False,
    )
    out_path = Path(out) if isinstance(out, str) else None
    return _call_json_command(
        method="project.validate",
        invoke=lambda: _run_project_validate(
            project_dir=Path(project_dir),
            out_path=out_path,
            repo_root=None,
            render_compat=render_compat,
        ),
        accepted_exit_codes=(0, 2),
    )


def _handle_project_pack(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="project.pack",
        params=params,
        allowed={"project_dir", "out", "include_wavs", "force"},
    )
    project_dir = _require_str_param(
        method="project.pack",
        params=params,
        name="project_dir",
    )
    out = _require_str_param(
        method="project.pack",
        params=params,
        name="out",
    )
    include_wavs = _optional_bool_param(
        method="project.pack",
        params=params,
        name="include_wavs",
        default=False,
    )
    force = _optional_bool_param(
        method="project.pack",
        params=params,
        name="force",
        default=False,
    )
    return _call_json_command(
        method="project.pack",
        invoke=lambda: _run_project_pack(
            project_dir=Path(project_dir),
            out_path=Path(out),
            include_wavs=include_wavs,
            force=force,
        ),
    )


def _handle_project_write_render_request(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="project.write_render_request",
        params=params,
        allowed={"project_dir", "set"},
    )
    project_dir = _require_str_param(
        method="project.write_render_request",
        params=params,
        name="project_dir",
    )
    updates = _require_object_param(
        method="project.write_render_request",
        params=params,
        name="set",
    )
    if not updates:
        raise _RpcRequestError(
            code="RPC.INVALID_PARAMS",
            message=(
                "project.write_render_request param 'set' must include at least "
                "one editable field."
            ),
        )
    unknown_keys = sorted(
        key
        for key in updates
        if key not in _PROJECT_WRITE_RENDER_REQUEST_ALLOWED_SET_KEYS
    )
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        allowed = ", ".join(sorted(_PROJECT_WRITE_RENDER_REQUEST_ALLOWED_SET_KEYS))
        raise _RpcRequestError(
            code="RPC.INVALID_PARAMS",
            message=(
                "project.write_render_request param 'set' received unknown keys: "
                f"{joined}. Allowed keys: {allowed}"
            ),
        )
    return _call_json_command(
        method="project.write_render_request",
        invoke=lambda: _run_project_write_render_request(
            project_dir=Path(project_dir),
            updates=updates,
        ),
    )


def _handle_plugin_market_list(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="plugin.market.list",
        params=params,
        allowed={"plugins", "plugin_dir", "index"},
    )
    plugins = _optional_str_param(
        method="plugin.market.list",
        params=params,
        name="plugins",
        default="plugins",
    )
    plugin_dir = _optional_str_param(
        method="plugin.market.list",
        params=params,
        name="plugin_dir",
        default=None,
    )
    index = _optional_str_param(
        method="plugin.market.list",
        params=params,
        name="index",
        default=None,
    )

    try:
        return build_plugin_market_list_payload(
            plugins_dir=Path(plugins) if isinstance(plugins, str) else Path("plugins"),
            plugin_dir=Path(plugin_dir) if isinstance(plugin_dir, str) else None,
            index_path=Path(index) if isinstance(index, str) else None,
        )
    except (RuntimeError, ValueError, AttributeError, OSError) as exc:
        raise _RpcMethodError(message=str(exc)) from exc


def _handle_plugin_market_update(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="plugin.market.update",
        params=params,
        allowed={"out", "index"},
    )
    out = _optional_str_param(
        method="plugin.market.update",
        params=params,
        name="out",
        default=None,
    )
    index = _optional_str_param(
        method="plugin.market.update",
        params=params,
        name="index",
        default=None,
    )

    try:
        return update_plugin_market_snapshot(
            out_path=Path(out) if isinstance(out, str) else None,
            index_path=Path(index) if isinstance(index, str) else None,
        )
    except (RuntimeError, ValueError, AttributeError, OSError) as exc:
        raise _RpcMethodError(message=str(exc)) from exc


def _handle_plugin_market_install(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="plugin.market.install",
        params=params,
        allowed={"plugin_id", "plugins", "index"},
    )
    plugin_id = _require_str_param(
        method="plugin.market.install",
        params=params,
        name="plugin_id",
    )
    plugins = _optional_str_param(
        method="plugin.market.install",
        params=params,
        name="plugins",
        default=None,
    )
    index = _optional_str_param(
        method="plugin.market.install",
        params=params,
        name="index",
        default=None,
    )

    try:
        return install_plugin_market_entry(
            plugin_id=plugin_id,
            plugins_dir=Path(plugins) if isinstance(plugins, str) else None,
            index_path=Path(index) if isinstance(index, str) else None,
        )
    except (RuntimeError, ValueError, AttributeError, OSError) as exc:
        raise _RpcMethodError(message=str(exc)) from exc


def _handle_rpc_discover(params: dict[str, Any]) -> dict[str, Any]:
    _validate_allowed_params(
        method="rpc.discover",
        params=params,
        allowed=set(),
    )
    return _build_rpc_discover_payload()


_RPC_METHOD_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "env.doctor": _handle_env_doctor,
    "project.show": _handle_project_show,
    "project.save": _handle_project_save,
    "project.load": _handle_project_load,
    "project.build_gui": _handle_project_build_gui,
    "project.render_run": _handle_project_render_run,
    "project.validate": _handle_project_validate,
    "project.pack": _handle_project_pack,
    "project.write_render_request": _handle_project_write_render_request,
    "plugin.market.list": _handle_plugin_market_list,
    "plugin.market.update": _handle_plugin_market_update,
    "plugin.market.install": _handle_plugin_market_install,
    "scene.locks.inspect": _handle_scene_locks_inspect,
    "scene.locks.save": _handle_scene_locks_save,
    "rpc.discover": _handle_rpc_discover,
}


def _run_gui_rpc(
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    input_stream = stdin if stdin is not None else sys.stdin
    output_stream = stdout if stdout is not None else sys.stdout

    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue

        request_id: Any = None
        try:
            raw_request = json.loads(line)
        except json.JSONDecodeError:
            response = _error_response(
                None,
                code="RPC.INVALID_JSON",
                message="Invalid JSON request.",
            )
        else:
            if not isinstance(raw_request, dict):
                response = _error_response(
                    None,
                    code="RPC.INVALID_REQUEST",
                    message="Request must be a JSON object.",
                )
            else:
                request_id = raw_request.get("id")
                method = raw_request.get("method")
                params = raw_request.get("params", {})

                try:
                    if not isinstance(method, str) or not method.strip():
                        raise _RpcRequestError(
                            code="RPC.INVALID_REQUEST",
                            message="Request field 'method' must be a non-empty string.",
                        )
                    if not isinstance(params, dict):
                        raise _RpcRequestError(
                            code="RPC.INVALID_PARAMS",
                            message=f"{method} params must be a JSON object.",
                        )

                    handler = _RPC_METHOD_HANDLERS.get(method)
                    if handler is None:
                        raise _RpcRequestError(
                            code="RPC.UNKNOWN_METHOD",
                            message=f"Unknown method: {method}",
                        )

                    result = handler(params)
                except _RpcRequestError as exc:
                    response = _error_response(
                        request_id,
                        code=exc.code,
                        message=exc.message,
                    )
                except _RpcMethodError as exc:
                    response = _error_response(
                        request_id,
                        code="RPC.METHOD_FAILED",
                        message=exc.message,
                    )
                except Exception:
                    response = _error_response(
                        request_id,
                        code="RPC.INTERNAL_ERROR",
                        message="Internal RPC error.",
                    )
                else:
                    response = {
                        "id": request_id,
                        "ok": True,
                        "result": result,
                    }

        output_stream.write(json.dumps(response, sort_keys=True))
        output_stream.write("\n")
        output_stream.flush()

    return 0
