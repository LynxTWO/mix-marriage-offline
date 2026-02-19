from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

from mmo.cli_commands._project import (
    _run_project_build_gui,
    _run_project_pack,
    _run_project_render_run,
    _run_project_show,
    _run_project_validate,
    _run_project_write_render_request,
)
from mmo.core.env_doctor import build_env_doctor_report

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
        "plugin_chain",
        "policies",
        "target_ids",
        "target_layout_ids",
    }
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
                "plugin_chain",
                "policies",
                "target_ids",
                "target_layout_ids",
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
    "project.build_gui": _handle_project_build_gui,
    "project.render_run": _handle_project_render_run,
    "project.validate": _handle_project_validate,
    "project.pack": _handle_project_pack,
    "project.write_render_request": _handle_project_write_render_request,
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
