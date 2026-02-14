"""Analysis-related CLI helpers: scan, analyze, export, and cache utilities."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from mmo.core.cache_keys import cache_key, hash_lockfile, hash_run_config
from mmo.core.cache_store import report_has_time_cap_stop_condition
from mmo.core.run_config import RUN_CONFIG_SCHEMA_VERSION, normalize_run_config

__all__ = [
    "_run_command",
    "_run_scan",
    "_run_analyze",
    "_run_export",
    "_analyze_run_config",
    "_analysis_cache_key",
    "_analysis_run_config_for_variant_cache",
    "_should_skip_analysis_cache_save",
]


def _run_command(command: list[str]) -> int:
    completed = subprocess.run(command, check=False)
    return completed.returncode


def _run_scan(
    tools_dir: Path,
    stems_dir: Path,
    out_path: Path,
    meters: str | None,
    include_peak: bool,
) -> int:
    command = [
        sys.executable,
        str(tools_dir / "scan_session.py"),
        str(stems_dir),
        "--out",
        str(out_path),
    ]
    if meters:
        command.extend(["--meters", meters])
    if include_peak:
        command.append("--peak")
    return _run_command(command)


def _run_analyze(
    tools_dir: Path,
    stems_dir: Path,
    out_report: Path,
    meters: str | None,
    include_peak: bool,
    plugins_dir: str,
    keep_scan: bool,
    profile_id: str,
) -> int:
    command = [
        sys.executable,
        str(tools_dir / "analyze_stems.py"),
        str(stems_dir),
        "--out-report",
        str(out_report),
        "--plugins",
        plugins_dir,
    ]
    if meters:
        command.extend(["--meters", meters])
    if include_peak:
        command.append("--peak")
    if keep_scan:
        command.append("--keep-scan")
    if profile_id:
        command.extend(["--profile", profile_id])
    return _run_command(command)


def _run_export(
    tools_dir: Path,
    report_path: Path,
    csv_path: str | None,
    pdf_path: str | None,
    *,
    no_measurements: bool,
    no_gates: bool,
    truncate_values: int,
) -> int:
    command = [
        sys.executable,
        str(tools_dir / "export_report.py"),
        "--report",
        str(report_path),
    ]
    if csv_path:
        command.extend(["--csv", csv_path])
    if pdf_path:
        command.extend(["--pdf", pdf_path])
    if no_measurements:
        command.append("--no-measurements")
    if no_gates:
        command.append("--no-gates")
    if truncate_values != 200:
        command.extend(["--truncate-values", str(truncate_values)])
    if len(command) == 4:
        return 0
    return _run_command(command)


def _analyze_run_config(
    *,
    profile_id: str,
    meters: str | None,
    preset_id: str | None = None,
    base_run_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = dict(base_run_config or {})
    payload["schema_version"] = RUN_CONFIG_SCHEMA_VERSION
    payload["profile_id"] = profile_id
    if meters is not None:
        payload["meters"] = meters
    if preset_id is not None:
        payload["preset_id"] = preset_id
    return normalize_run_config(payload)


def _analysis_cache_key(lock: dict[str, Any], cfg: dict[str, Any]) -> str:
    lock_hash = hash_lockfile(lock)
    cfg_hash = hash_run_config(cfg)
    return cache_key(lock_hash, cfg_hash)


def _analysis_run_config_for_variant_cache(run_config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_run_config(run_config)
    analysis_cfg = json.loads(json.dumps(normalized))

    render_cfg = analysis_cfg.get("render")
    if isinstance(render_cfg, dict):
        render_cfg = dict(render_cfg)
        render_cfg.pop("out_dir", None)
        render_cfg.pop("output_formats", None)
        if render_cfg:
            analysis_cfg["render"] = render_cfg
        else:
            analysis_cfg.pop("render", None)
    else:
        analysis_cfg.pop("render", None)

    apply_cfg = analysis_cfg.get("apply")
    if isinstance(apply_cfg, dict):
        apply_cfg = dict(apply_cfg)
        apply_cfg.pop("output_formats", None)
        if apply_cfg:
            analysis_cfg["apply"] = apply_cfg
        else:
            analysis_cfg.pop("apply", None)
    else:
        analysis_cfg.pop("apply", None)

    downmix_cfg = analysis_cfg.get("downmix")
    if isinstance(downmix_cfg, dict):
        downmix_cfg = dict(downmix_cfg)
        downmix_cfg.pop("source_layout_id", None)
        downmix_cfg.pop("target_layout_id", None)
        if downmix_cfg:
            analysis_cfg["downmix"] = downmix_cfg
        else:
            analysis_cfg.pop("downmix", None)
    else:
        analysis_cfg.pop("downmix", None)

    return normalize_run_config(analysis_cfg)


def _should_skip_analysis_cache_save(report: dict[str, Any], run_config: dict[str, Any]) -> bool:
    meters = run_config.get("meters")
    if meters != "truth":
        return False
    return report_has_time_cap_stop_condition(report)
