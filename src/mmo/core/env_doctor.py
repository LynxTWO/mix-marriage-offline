from __future__ import annotations

import importlib.util
import os
import platform
import sys
from pathlib import Path
from typing import Any

from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd, resolve_ffprobe_cmd
from mmo.resources import (
    data_root,
    default_cache_dir,
    ontology_dir,
    presets_dir,
    schemas_dir,
    temp_dir_selection,
)

_ENV_OVERRIDE_KEYS: tuple[str, ...] = (
    "MMO_DATA_ROOT",
    "MMO_CACHE_DIR",
    "MMO_TEMP_DIR",
    "MMO_FFMPEG_PATH",
    "MMO_FFPROBE_PATH",
)


def _normalize_path(value: str | Path) -> str:
    raw = os.fspath(value)
    try:
        return Path(raw).expanduser().resolve().as_posix()
    except (OSError, RuntimeError, ValueError):
        return raw.replace("\\", "/")


def _is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False

    probe = path / f".mmo_env_doctor_probe_{os.getpid()}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False
    finally:
        if probe.exists():
            try:
                probe.unlink()
            except OSError:
                pass


def _is_readable_directory(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        with os.scandir(path) as entries:
            next(entries, None)
        return True
    except OSError:
        return False


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _env_override_entry(name: str) -> dict[str, Any]:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return {
            "present": False,
            "path": "",
        }
    return {
        "present": True,
        "path": _normalize_path(raw),
    }


def _temp_root_selection_text(*, source: str, root: Path, fallback: bool) -> str:
    fallback_text = "true" if fallback else "false"
    return f"source={source};root={_normalize_path(root)};fallback={fallback_text}"


def build_env_doctor_report() -> dict[str, Any]:
    resolved_data_root = data_root()
    resolved_schemas_dir = schemas_dir()
    resolved_ontology_dir = ontology_dir()
    resolved_presets_dir = presets_dir()
    resolved_cache_dir = default_cache_dir()
    resolved_temp_selection = temp_dir_selection()
    resolved_temp_dir = resolved_temp_selection.path
    temp_root_selection = _temp_root_selection_text(
        source=resolved_temp_selection.source,
        root=resolved_temp_selection.root,
        fallback=resolved_temp_selection.fallback,
    )

    env_overrides = {
        name: _env_override_entry(name)
        for name in _ENV_OVERRIDE_KEYS
    }

    return {
        "python": {
            "executable": _normalize_path(sys.executable),
            "platform": sys.platform,
            "version": platform.python_version(),
        },
        "paths": {
            "cache_dir": _normalize_path(resolved_cache_dir),
            "data_root": _normalize_path(resolved_data_root),
            "ontology_dir": _normalize_path(resolved_ontology_dir),
            "presets_dir": _normalize_path(resolved_presets_dir),
            "schemas_dir": _normalize_path(resolved_schemas_dir),
            "temp_dir": _normalize_path(resolved_temp_dir),
            "temp_root_selection": temp_root_selection,
        },
        "checks": {
            "cache_dir_writable": _is_writable_directory(resolved_cache_dir),
            "data_root_readable": _is_readable_directory(resolved_data_root),
            "temp_dir_writable": _is_writable_directory(resolved_temp_dir),
            "numpy_available": _module_available("numpy"),
            "ffmpeg_available": resolve_ffmpeg_cmd() is not None,
            "ffprobe_available": resolve_ffprobe_cmd() is not None,
            "reportlab_available": _module_available("reportlab"),
        },
        "env_overrides": env_overrides,
    }


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _as_bool_text(value: Any) -> str:
    return "true" if bool(value) else "false"


def render_env_doctor_text(report: dict[str, Any]) -> str:
    python_payload = report.get("python", {})
    paths_payload = report.get("paths", {})
    checks_payload = report.get("checks", {})
    overrides_payload = report.get("env_overrides", {})

    lines: list[str] = [
        f"python.version={_as_text(python_payload.get('version'))}",
        f"python.executable={_as_text(python_payload.get('executable'))}",
        f"python.platform={_as_text(python_payload.get('platform'))}",
        f"paths.data_root={_as_text(paths_payload.get('data_root'))}",
        f"paths.schemas_dir={_as_text(paths_payload.get('schemas_dir'))}",
        f"paths.ontology_dir={_as_text(paths_payload.get('ontology_dir'))}",
        f"paths.presets_dir={_as_text(paths_payload.get('presets_dir'))}",
        f"paths.cache_dir={_as_text(paths_payload.get('cache_dir'))}",
        f"paths.temp_dir={_as_text(paths_payload.get('temp_dir'))}",
        f"paths.temp_root_selection={_as_text(paths_payload.get('temp_root_selection'))}",
        f"checks.cache_dir_writable={_as_bool_text(checks_payload.get('cache_dir_writable'))}",
        f"checks.temp_dir_writable={_as_bool_text(checks_payload.get('temp_dir_writable'))}",
        f"checks.data_root_readable={_as_bool_text(checks_payload.get('data_root_readable'))}",
        f"checks.numpy_available={_as_bool_text(checks_payload.get('numpy_available'))}",
        f"checks.ffmpeg_available={_as_bool_text(checks_payload.get('ffmpeg_available'))}",
        f"checks.ffprobe_available={_as_bool_text(checks_payload.get('ffprobe_available'))}",
        f"checks.reportlab_available={_as_bool_text(checks_payload.get('reportlab_available'))}",
    ]

    for name in _ENV_OVERRIDE_KEYS:
        item = overrides_payload.get(name, {})
        lines.append(
            f"env_overrides.{name}.present={_as_bool_text(item.get('present'))}"
        )
        lines.append(f"env_overrides.{name}.path={_as_text(item.get('path'))}")

    return "\n".join(lines) + "\n"
