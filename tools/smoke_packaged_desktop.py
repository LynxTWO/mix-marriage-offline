"""Run packaged MMO Desktop smoke checks against built Tauri bundles."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_ROOT = REPO_ROOT / "gui" / "desktop-tauri" / "src-tauri" / "target" / "release" / "bundle"
DEFAULT_TARGET = "TARGET.STEREO.2_0"
DEFAULT_LAYOUT_STANDARD = "SMPTE"
MIN_MEANINGFUL_DURATION_SECONDS = 0.11
SILENT_OUTPUT_LINEAR_TOLERANCE = 10.0 ** (-120.0 / 20.0)
_EXPECTED_SMOKE_WORKFLOW_STAGES = ("doctor", "validate", "analyze", "scene", "render")
_VALID_MASTER_RESULT_BUCKETS = frozenset({"partial_success", "valid_master"})


class SmokeError(RuntimeError):
    """Raised when the packaged desktop smoke flow fails."""


class WindowsInstallResult(NamedTuple):
    """Resolved details from a real Windows installer run."""

    app_executable: Path
    install_log_path: Path
    install_root: Path
    installer_kind: str
    installer_path: Path


class WindowsInstallEntry(NamedTuple):
    """Windows uninstall metadata discovered from the registry."""

    display_name: str
    install_location: Path | None
    display_icon: Path | None
    uninstall_command: str | None
    quiet_uninstall_command: str | None


class WindowsCleanupResult(NamedTuple):
    """Best-effort cleanup result for a Windows real-install smoke run."""

    attempted: bool
    ok: bool
    strategy: str | None
    install_root: Path | None
    uninstall_log_path: Path | None
    removed_install_root: bool
    command: tuple[str, ...]
    notes: tuple[str, ...]


def _platform_tag() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise SmokeError(f"Unsupported platform for packaged desktop smoke: {sys.platform}")


def _normalize_path_text(value: str | Path) -> str:
    return os.fspath(value).replace("\\", "/").rstrip("/").casefold()


def _path_is_under(candidate: str, root: Path) -> bool:
    root_text = _normalize_path_text(root)
    candidate_text = _normalize_path_text(candidate)
    return candidate_text == root_text or candidate_text.startswith(f"{root_text}/")


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_int(value: Any) -> int | None:
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


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        candidate = float(value)
        if math.isfinite(candidate):
            return candidate
        return None
    if isinstance(value, str) and value.strip():
        try:
            candidate = float(value)
        except ValueError:
            return None
        if math.isfinite(candidate):
            return candidate
    return None


def _canonical_payload(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _read_product_name(repo_root: Path) -> str:
    config_path = repo_root / "gui" / "desktop-tauri" / "src-tauri" / "tauri.conf.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    product_name = payload.get("productName")
    if not isinstance(product_name, str) or not product_name.strip():
        raise SmokeError(f"Missing productName in {config_path}")
    return product_name.strip()


def _artifact_suffixes_for_platform(platform_tag: str) -> tuple[str, ...]:
    if platform_tag == "windows":
        return (".msi", "-setup.exe")
    if platform_tag == "macos":
        return (".app",)
    if platform_tag == "linux":
        return (".AppImage",)
    raise SmokeError(f"Unsupported platform tag: {platform_tag}")


def _find_artifact(*, bundle_root: Path, platform_tag: str) -> Path:
    suffixes = _artifact_suffixes_for_platform(platform_tag)
    candidates = sorted(
        path
        for path in bundle_root.rglob("*")
        if path.name.endswith(suffixes)
    )
    if not candidates:
        suffix_text = ", ".join(suffixes)
        raise SmokeError(f"No {suffix_text} artifact found under {bundle_root}")
    if platform_tag == "windows":
        # Prefer the NSIS setup executable when present because it most closely
        # matches the end-user setup flow. Fall back to MSI if it is the only
        # Windows installer artifact available.
        candidates.sort(
            key=lambda path: (
                0 if path.name.casefold().endswith("-setup.exe") else 1,
                path.name.casefold(),
                path.as_posix().casefold(),
            )
        )
    return candidates[0]


def _looks_like_sidecar_name(name: str, platform_tag: str) -> bool:
    path = Path(name)
    normalized = name.casefold()
    stem = path.stem.casefold()

    if stem == "mmo":
        return True

    if not normalized.startswith("mmo-"):
        return False
    if platform_tag == "windows":
        return "windows" in normalized or "msvc" in normalized
    if platform_tag == "macos":
        return "darwin" in normalized or "apple" in normalized
    if platform_tag == "linux":
        return "linux" in normalized or "gnu" in normalized
    return False


def _sidecar_search_directories(root: Path, *, platform_tag: str) -> tuple[Path, ...]:
    if platform_tag == "macos":
        return (
            root / "Contents" / "MacOS",
            root / "Contents" / "Frameworks",
            root / "Contents" / "Resources",
        )
    if platform_tag == "windows":
        return (
            root,
            root / "bin",
        )
    if platform_tag == "linux":
        return (
            root,
            root / "bin",
            root / "usr" / "bin",
        )
    return (root,)


def _describe_directory_entries(path: Path, *, max_entries: int = 8) -> str:
    if not path.exists():
        return "(missing)"
    if not path.is_dir():
        return "(not a directory)"
    entries = sorted(child.name for child in path.iterdir())
    if not entries:
        return "(empty)"
    visible = entries[:max_entries]
    if len(entries) > max_entries:
        visible.append(f"... (+{len(entries) - max_entries} more)")
    return ", ".join(visible)


def _sidecar_search_receipt(root: Path, *, platform_tag: str) -> str:
    lines = ["Likely bundle directories:"]
    for directory in _sidecar_search_directories(root, platform_tag=platform_tag):
        try:
            label = directory.relative_to(root).as_posix()
        except ValueError:
            label = directory.as_posix()
        lines.append(f"- {label}: {_describe_directory_entries(directory)}")
    return "\n".join(lines)


def _main_app_score(path: Path, *, platform_tag: str, product_name: str) -> int:
    normalized_name = path.name.casefold()
    normalized_stem = path.stem.casefold()
    normalized_product = product_name.casefold()
    compact_product = normalized_product.replace(" ", "")
    compact_name = normalized_name.replace("-", "").replace("_", "").replace(" ", "")

    score = 0
    if compact_product and compact_product in compact_name:
        score += 200
    if "desktop" in normalized_name:
        score += 50
    if "mmo" in normalized_name:
        score += 25
    if platform_tag == "macos" and "contents" in {part.casefold() for part in path.parts}:
        score += 20
    if platform_tag == "windows" and len(path.parts) <= 6:
        score += 15
    if normalized_stem in {"apprun", product_name.casefold()}:
        score += 30
    if _looks_like_sidecar_name(path.name, platform_tag):
        score -= 500
    for helper_token in ("crashpad", "uninstall", "setup", "updater", "squirrel", "helper"):
        if helper_token in normalized_name:
            score -= 200
    return score


def _find_main_app_executable(
    root: Path,
    *,
    platform_tag: str,
    product_name: str,
) -> Path:
    if platform_tag == "macos":
        macos_dir = root / "Contents" / "MacOS"
        if not macos_dir.is_dir():
            raise SmokeError(f"Expected macOS app executable directory is missing: {macos_dir}")
        candidates = [
            path
            for path in macos_dir.iterdir()
            if path.is_file()
        ]
    else:
        suffix = ".exe" if platform_tag == "windows" else ""
        candidates = [
            path
            for path in root.rglob("*")
            if path.is_file() and (suffix == "" or path.suffix.lower() == suffix)
        ]

    if not candidates:
        raise SmokeError(f"Could not find a packaged app executable under {root}")

    return max(
        candidates,
        key=lambda path: _main_app_score(path, platform_tag=platform_tag, product_name=product_name),
    )


def _find_sidecar_binaries(root: Path, *, platform_tag: str) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and _looks_like_sidecar_name(path.name, platform_tag)
    )


def _find_sidecar_binary(root: Path, *, platform_tag: str) -> Path:
    candidates = _find_sidecar_binaries(root, platform_tag=platform_tag)
    if not candidates:
        raise SmokeError(
            f"Could not find a packaged sidecar under {root}\n"
            f"{_sidecar_search_receipt(root, platform_tag=platform_tag)}"
        )
    return min(
        candidates,
        key=lambda path: (
            0 if path.stem.casefold() == "mmo" else 1,
            len(path.name),
            path.name.casefold(),
            path.as_posix().casefold(),
        ),
    )


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    label: str,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode == 0:
        return completed
    raise SmokeError(
        f"{label} failed with exit code {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def _artifact_kind(path: Path, *, platform_tag: str) -> str:
    name = path.name.casefold()
    if platform_tag == "windows":
        if name.endswith("-setup.exe"):
            return "nsis"
        if path.suffix.lower() == ".msi":
            return "msi"
    if platform_tag == "macos" and path.suffix.lower() == ".app":
        return "app"
    if platform_tag == "linux" and path.suffix == ".AppImage":
        return "appimage"
    raise SmokeError(f"Unsupported {platform_tag} artifact path: {path}")


def _probe_packaged_sidecar(
    *,
    bundle_root: Path,
    platform_tag: str,
    env: dict[str, str],
) -> Path:
    sidecar_path = _find_sidecar_binary(bundle_root, platform_tag=platform_tag)
    sidecar_cwd = sidecar_path.parent

    version_result = _run_command(
        [str(sidecar_path), "--version"],
        cwd=sidecar_cwd,
        env=env,
        label="sidecar-version",
    )
    version_text = version_result.stdout.strip() or version_result.stderr.strip()
    if not version_text:
        raise SmokeError("Packaged sidecar returned no version output.")

    plugins_result = _run_command(
        [
            str(sidecar_path),
            "plugins",
            "validate",
            "--bundled-only",
            "--format",
            "json",
        ],
        cwd=sidecar_cwd,
        env=env,
        label="sidecar-plugins-validate",
    )
    try:
        plugins_payload = json.loads(plugins_result.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError(
            "Packaged sidecar plugins validate output was not valid JSON.\n"
            f"stdout:\n{plugins_result.stdout}\n"
            f"stderr:\n{plugins_result.stderr}"
        ) from exc
    if not isinstance(plugins_payload, dict) or not bool(plugins_payload.get("ok")):
        raise SmokeError(
            "Packaged sidecar plugins validate probe did not report success.\n"
            f"{json.dumps(plugins_payload, indent=2, sort_keys=True)}"
        )
    if plugins_payload.get("bundled_only") is not True:
        raise SmokeError("Packaged sidecar plugins validate probe was not restricted to bundled plugins.")

    env_doctor_result = _run_command(
        [str(sidecar_path), "env", "doctor", "--format", "json"],
        cwd=sidecar_cwd,
        env=env,
        label="sidecar-env-doctor",
    )
    try:
        env_doctor_payload = json.loads(env_doctor_result.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeError(
            "Packaged sidecar env doctor output was not valid JSON.\n"
            f"stdout:\n{env_doctor_result.stdout}\n"
            f"stderr:\n{env_doctor_result.stderr}"
        ) from exc
    if not isinstance(env_doctor_payload, dict):
        raise SmokeError("Packaged sidecar env doctor probe did not return a JSON object.")
    if not isinstance(env_doctor_payload.get("checks"), dict):
        raise SmokeError("Packaged sidecar env doctor probe did not include checks.")

    return sidecar_path


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        normalized = _normalize_path_text(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(path)
    return deduped


def _coerce_windows_executable_path(value: str) -> Path | None:
    text = value.strip().strip('"')
    if not text:
        return None
    lowered = text.casefold()
    marker = ".exe"
    if marker in lowered:
        text = text[: lowered.index(marker) + len(marker)]
    candidate = Path(text)
    if candidate.suffix.lower() != ".exe":
        return None
    return candidate


def _read_windows_install_entries(product_name: str) -> list[WindowsInstallEntry]:
    if not sys.platform.startswith("win"):
        return []
    try:
        import winreg
    except ImportError:
        return []

    uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    display_name_needles = {
        product_name.casefold(),
        product_name.casefold().replace(" ", ""),
    }

    def _matches_display_name(value: str) -> bool:
        normalized = value.casefold()
        compact = normalized.replace(" ", "")
        return any(needle in {normalized, compact} or needle in normalized or needle in compact for needle in display_name_needles)

    entries: list[WindowsInstallEntry] = []
    hive_specs = [
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ, "HKCU"),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0), "HKLM64"),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0), "HKLM32"),
    ]
    for hive, access, _label in hive_specs:
        try:
            with winreg.OpenKey(hive, uninstall_key, 0, access) as root_key:
                index = 0
                while True:
                    try:
                        child_name = winreg.EnumKey(root_key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(root_key, child_name, 0, access) as child_key:
                            display_name, _ = winreg.QueryValueEx(child_key, "DisplayName")
                            if not isinstance(display_name, str) or not _matches_display_name(display_name):
                                continue

                            install_location: str | None = None
                            display_icon: str | None = None
                            uninstall_command: str | None = None
                            quiet_uninstall_command: str | None = None
                            try:
                                install_location_value, _ = winreg.QueryValueEx(child_key, "InstallLocation")
                                if isinstance(install_location_value, str) and install_location_value.strip():
                                    install_location = install_location_value.strip()
                            except OSError:
                                pass
                            try:
                                display_icon_value, _ = winreg.QueryValueEx(child_key, "DisplayIcon")
                                if isinstance(display_icon_value, str) and display_icon_value.strip():
                                    display_icon = display_icon_value.strip()
                            except OSError:
                                pass
                            try:
                                uninstall_value, _ = winreg.QueryValueEx(child_key, "UninstallString")
                                if isinstance(uninstall_value, str) and uninstall_value.strip():
                                    uninstall_command = uninstall_value.strip()
                            except OSError:
                                pass
                            try:
                                quiet_uninstall_value, _ = winreg.QueryValueEx(child_key, "QuietUninstallString")
                                if isinstance(quiet_uninstall_value, str) and quiet_uninstall_value.strip():
                                    quiet_uninstall_command = quiet_uninstall_value.strip()
                            except OSError:
                                pass

                            entries.append(
                                WindowsInstallEntry(
                                    display_name=display_name.strip(),
                                    install_location=Path(install_location) if install_location else None,
                                    display_icon=_coerce_windows_executable_path(display_icon) if display_icon else None,
                                    uninstall_command=uninstall_command,
                                    quiet_uninstall_command=quiet_uninstall_command,
                                )
                            )
                    except OSError:
                        continue
        except OSError:
            continue

    deduped_entries: list[WindowsInstallEntry] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for entry in entries:
        key = (
            entry.display_name.casefold(),
            _normalize_path_text(entry.install_location) if entry.install_location is not None else None,
            _normalize_path_text(entry.display_icon) if entry.display_icon is not None else None,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped_entries.append(entry)
    return deduped_entries


def _read_windows_install_roots_from_registry(product_name: str) -> list[Path]:
    candidates: list[Path] = []
    for entry in _read_windows_install_entries(product_name):
        if entry.install_location is not None:
            candidates.append(entry.install_location)
        if entry.display_icon is not None:
            candidates.append(entry.display_icon.parent)
    return _dedupe_paths(candidates)


def _product_name_tokens(product_name: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[\s._-]+", product_name.casefold()) if token)


def _windows_dir_name_matches_product(name: str, *, product_name: str) -> bool:
    normalized = name.casefold()
    compact = normalized.replace(" ", "").replace("-", "").replace("_", "")
    compact_product = product_name.casefold().replace(" ", "").replace("-", "").replace("_", "")
    if compact_product and compact_product in compact:
        return True
    return any(token in normalized for token in _product_name_tokens(product_name))


def _windows_candidate_install_dirs(*, product_name: str, env: dict[str, str]) -> list[Path]:
    roots: list[Path] = []
    local_app_data = env.get("LOCALAPPDATA")
    if local_app_data:
        local_root = Path(local_app_data)
        roots.append(local_root / "Programs" / product_name)
        roots.append(local_root / product_name)
        programs_dir = local_root / "Programs"
        if programs_dir.is_dir():
            for child in sorted(programs_dir.iterdir(), key=lambda path: path.name.casefold()):
                if child.is_dir() and _windows_dir_name_matches_product(child.name, product_name=product_name):
                    roots.append(child)

    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = env.get(env_name)
        if not base:
            continue
        base_path = Path(base)
        roots.append(base_path / product_name)
        if base_path.is_dir():
            for child in sorted(base_path.iterdir(), key=lambda path: path.name.casefold()):
                if child.is_dir() and _windows_dir_name_matches_product(child.name, product_name=product_name):
                    roots.append(child)

    roots.extend(_read_windows_install_roots_from_registry(product_name))
    return _dedupe_paths(roots)


def _find_windows_installed_app_candidates(*, product_name: str, env: dict[str, str]) -> list[Path]:
    candidates: list[Path] = []
    for install_dir in _windows_candidate_install_dirs(product_name=product_name, env=env):
        if install_dir.is_file() and install_dir.suffix.lower() == ".exe":
            candidates.append(install_dir)
            continue
        if not install_dir.is_dir():
            continue
        try:
            candidates.append(
                _find_main_app_executable(
                    install_dir,
                    platform_tag="windows",
                    product_name=product_name,
                )
            )
        except SmokeError:
            continue
    return _dedupe_paths(candidates)


def _choose_windows_installed_app(
    candidates: list[Path],
    *,
    preexisting_candidates: set[str],
    product_name: str,
) -> Path:
    if not candidates:
        raise SmokeError("Could not locate the installed Windows app executable after installer run.")
    return max(
        candidates,
        key=lambda path: (
            1 if _normalize_path_text(path) not in preexisting_candidates else 0,
            _main_app_score(path, platform_tag="windows", product_name=product_name),
            -len(path.parts),
            path.as_posix().casefold(),
        ),
    )


def _read_log_tail(path: Path, *, max_lines: int = 40) -> str:
    if not path.exists():
        return "(missing)"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"(unreadable: {exc})"
    if not lines:
        return "(empty)"
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def _windows_install_receipt(
    *,
    product_name: str,
    env: dict[str, str],
    installer_path: Path | None,
    install_log_path: Path | None,
    install_root: Path | None,
    launch_stdout: str,
    launch_stderr: str,
) -> str:
    lines: list[str] = ["Windows installer receipt:"]
    lines.append(f"- installer path: {installer_path if installer_path is not None else '(unknown)'}")
    lines.append(f"- install log path: {install_log_path if install_log_path is not None else '(unknown)'}")
    if install_root is not None:
        lines.append(f"- install root: {install_root}")

    lines.append("- likely install directory contents:")
    search_dirs = _windows_candidate_install_dirs(product_name=product_name, env=env)
    if install_root is not None:
        search_dirs = _dedupe_paths([install_root, *search_dirs])
    for directory in search_dirs[:8]:
        lines.append(f"  {directory}: {_describe_directory_entries(directory)}")

    if install_log_path is not None:
        lines.append("- install log tail:")
        lines.append(_read_log_tail(install_log_path))

    lines.append("- launched app stdout:")
    lines.append(launch_stdout.strip() or "(empty)")
    lines.append("- launched app stderr:")
    lines.append(launch_stderr.strip() or "(empty)")
    return "\n".join(lines)


def _windows_cleanup_payload(result: WindowsCleanupResult) -> dict[str, Any]:
    return {
        "attempted": result.attempted,
        "command": list(result.command),
        "install_root": result.install_root.as_posix() if result.install_root is not None else "",
        "notes": list(result.notes),
        "ok": result.ok,
        "removed_install_root": result.removed_install_root,
        "strategy": result.strategy or "",
        "uninstall_log_path": result.uninstall_log_path.as_posix() if result.uninstall_log_path is not None else "",
    }


def _windows_cleanup_receipt(result: WindowsCleanupResult) -> str:
    lines = ["Windows cleanup receipt:"]
    lines.append(f"- attempted: {result.attempted}")
    lines.append(f"- ok: {result.ok}")
    lines.append(f"- strategy: {result.strategy or '(none)'}")
    lines.append(f"- command: {' '.join(result.command) if result.command else '(none)'}")
    lines.append(f"- install root: {result.install_root if result.install_root is not None else '(unknown)'}")
    lines.append(f"- removed install root: {result.removed_install_root}")
    if result.uninstall_log_path is not None:
        lines.append(f"- uninstall log path: {result.uninstall_log_path}")
        lines.append("- uninstall log tail:")
        lines.append(_read_log_tail(result.uninstall_log_path))
    if result.notes:
        lines.extend(f"- note: {note}" for note in result.notes)
    return "\n".join(lines)


def _windows_install_state_payload(
    *,
    artifact_path: Path,
    product_name: str,
    temp_root: Path,
    install_result: WindowsInstallResult,
    installed_sidecar_paths: list[Path],
) -> dict[str, Any]:
    return {
        "artifact_path": artifact_path.as_posix(),
        "install_log_path": install_result.install_log_path.as_posix(),
        "install_root": install_result.install_root.as_posix(),
        "installed_app_path": install_result.app_executable.as_posix(),
        "installed_sidecar_paths": [path.as_posix() for path in installed_sidecar_paths],
        "installer_kind": install_result.installer_kind,
        "installer_path": install_result.installer_path.as_posix(),
        "product_name": product_name,
        "temp_root": temp_root.as_posix(),
    }


def _write_windows_install_state(state_path: Path, payload: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_windows_install_state(state_path: Path) -> dict[str, Any] | None:
    if not state_path.exists():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _parse_windows_command(command_text: str) -> list[str]:
    try:
        parts = shlex.split(command_text, posix=False)
    except ValueError:
        parts = [command_text]
    return [part.strip() for part in parts if isinstance(part, str) and part.strip()]


def _is_msiexec_command(command: list[str]) -> bool:
    if not command:
        return False
    executable = Path(command[0].strip('"')).name.casefold()
    return executable in {"msiexec", "msiexec.exe"}


def _normalize_msiexec_uninstall_command(
    command: list[str],
    *,
    uninstall_log_path: Path,
) -> list[str]:
    normalized = ["msiexec"]
    extras: list[str] = []
    target_parts: list[str] = []
    index = 1
    while index < len(command):
        part = command[index]
        lowered = part.casefold()
        if lowered in {"/i", "-i", "/x", "-x"}:
            if index + 1 < len(command):
                target_parts.append(command[index + 1])
                index += 2
                continue
            index += 1
            continue
        if re.match(r"^[/-][ix].+", lowered):
            target_parts.append(part[2:])
            index += 1
            continue
        if lowered in {"/qn", "/quiet", "/passive", "/promptrestart", "/forcerestart", "/norestart"}:
            index += 1
            continue
        if lowered in {"/l*v", "/lv", "/l*vx", "/log"}:
            index += 2 if index + 1 < len(command) else 1
            continue
        extras.append(part)
        index += 1

    normalized.append("/x")
    normalized.extend(target_parts)
    normalized.extend(extras)
    if not any(part.casefold() in {"/qn", "/quiet"} for part in normalized):
        normalized.append("/qn")
    if not any(part.casefold() == "/norestart" for part in normalized):
        normalized.append("/norestart")
    normalized.extend(["/l*v", str(uninstall_log_path)])
    return normalized


def _windows_entry_matches_install_root(entry: WindowsInstallEntry, install_root: Path) -> bool:
    candidate_paths = [
        entry.install_location,
        entry.display_icon.parent if entry.display_icon is not None else None,
    ]
    install_root_text = _normalize_path_text(install_root)
    for candidate in candidate_paths:
        if candidate is None:
            continue
        candidate_text = _normalize_path_text(candidate)
        if candidate_text == install_root_text:
            return True
        if candidate_text.startswith(f"{install_root_text}/"):
            return True
        if install_root_text.startswith(f"{candidate_text}/"):
            return True
    return False


def _matching_windows_install_entries(*, install_root: Path, product_name: str) -> list[WindowsInstallEntry]:
    return [
        entry
        for entry in _read_windows_install_entries(product_name)
        if _windows_entry_matches_install_root(entry, install_root)
    ]


def _expected_windows_install_parent_roots(env: dict[str, str]) -> list[Path]:
    roots: list[Path] = []
    local_app_data = env.get("LOCALAPPDATA")
    if local_app_data:
        local_root = Path(local_app_data)
        roots.extend([local_root / "Programs", local_root])
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = env.get(env_name)
        if base:
            roots.append(Path(base))
    return _dedupe_paths(roots)


def _is_safe_windows_install_root(*, install_root: Path, product_name: str, env: dict[str, str]) -> bool:
    if not _windows_dir_name_matches_product(install_root.name, product_name=product_name):
        return False
    return any(_path_is_under(install_root, root) for root in _expected_windows_install_parent_roots(env))


def _choose_windows_uninstall_command(
    *,
    install_root: Path,
    installer_kind: str,
    artifact_path: Path,
    product_name: str,
    uninstall_log_path: Path,
) -> tuple[str | None, list[str] | None, tuple[str, ...]]:
    notes: list[str] = []
    uninstall_exe = install_root / "uninstall.exe"
    if uninstall_exe.is_file():
        return ("uninstall-exe", [str(uninstall_exe), "/S"], tuple(notes))

    for entry in _matching_windows_install_entries(install_root=install_root, product_name=product_name):
        for label, command_text in (
            ("registry-quiet-uninstall", entry.quiet_uninstall_command),
            ("registry-uninstall", entry.uninstall_command),
        ):
            if not command_text:
                continue
            parsed = _parse_windows_command(command_text)
            if not parsed:
                continue
            if _is_msiexec_command(parsed):
                return (
                    "registry-msiexec",
                    _normalize_msiexec_uninstall_command(parsed, uninstall_log_path=uninstall_log_path),
                    tuple(notes),
                )
            executable = _coerce_windows_executable_path(parsed[0])
            if executable is not None and executable.name.casefold() == "uninstall.exe":
                remainder = list(parsed[1:])
                if not any(arg.casefold() == "/s" for arg in remainder):
                    remainder.append("/S")
                return (label, [str(executable), *remainder], tuple(notes))
            notes.append(
                f"Skipped registry uninstall command for '{entry.display_name}' because it may require interaction."
            )

    if installer_kind == "msi":
        return (
            "artifact-msiexec",
            [
                "msiexec",
                "/x",
                str(artifact_path),
                "/qn",
                "/norestart",
                "/l*v",
                str(uninstall_log_path),
            ],
            tuple(notes),
        )

    return (None, None, tuple(notes))


def _run_windows_cleanup_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    uninstall_log_path: Path | None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if uninstall_log_path is not None and not uninstall_log_path.exists():
        uninstall_log_path.write_text(
            "\n".join(
                [
                    f"command={json.dumps(command)}",
                    f"exit_code={completed.returncode}",
                    "stdout:",
                    completed.stdout,
                    "stderr:",
                    completed.stderr,
                ]
            ),
            encoding="utf-8",
        )
    return completed


def _cleanup_windows_install(
    *,
    state: dict[str, Any],
    env: dict[str, str],
) -> WindowsCleanupResult:
    product_name = str(state.get("product_name", "")).strip()
    install_root_raw = state.get("install_root")
    artifact_path_raw = state.get("artifact_path")
    installer_kind = str(state.get("installer_kind", "")).strip().casefold()
    install_root = Path(install_root_raw).resolve() if isinstance(install_root_raw, str) and install_root_raw else None
    artifact_path = Path(artifact_path_raw).resolve() if isinstance(artifact_path_raw, str) and artifact_path_raw else None
    uninstall_log_path = None
    if isinstance(state.get("install_log_path"), str) and state["install_log_path"]:
        uninstall_log_path = Path(str(state["install_log_path"])).with_name("windows-uninstall.log")

    notes: list[str] = []
    if install_root is None or artifact_path is None or not product_name:
        notes.append("Windows install state did not include enough information for cleanup.")
        return WindowsCleanupResult(
            attempted=False,
            ok=False,
            strategy=None,
            install_root=install_root,
            uninstall_log_path=uninstall_log_path,
            removed_install_root=False,
            command=(),
            notes=tuple(notes),
        )

    strategy, command, selection_notes = _choose_windows_uninstall_command(
        install_root=install_root,
        installer_kind=installer_kind,
        artifact_path=artifact_path,
        product_name=product_name,
        uninstall_log_path=uninstall_log_path or (install_root / "windows-uninstall.log"),
    )
    notes.extend(selection_notes)

    attempted = False
    removed_install_root = False
    command_tuple: tuple[str, ...] = ()
    command_ok = False
    if command:
        attempted = True
        command_tuple = tuple(command)
        completed = _run_windows_cleanup_command(
            command,
            cwd=install_root.parent if install_root.parent.exists() else Path.cwd(),
            env=env,
            uninstall_log_path=uninstall_log_path,
        )
        command_ok = completed.returncode == 0
        if not command_ok:
            notes.append(f"Uninstall command exited {completed.returncode}.")
    else:
        notes.append("No safe uninstall command was available.")

    if install_root.exists():
        if _is_safe_windows_install_root(install_root=install_root, product_name=product_name, env=env):
            try:
                shutil.rmtree(install_root)
                removed_install_root = not install_root.exists()
                if removed_install_root:
                    strategy = f"{strategy} + residual-rmtree" if strategy else "residual-rmtree"
            except OSError as exc:
                notes.append(f"Residual install-root cleanup failed: {exc}")
        else:
            notes.append("Skipped residual install-root cleanup because the path was not an expected MMO install directory.")

    ok = (command_ok and not install_root.exists()) or removed_install_root or not install_root.exists()
    return WindowsCleanupResult(
        attempted=attempted,
        ok=ok,
        strategy=strategy,
        install_root=install_root,
        uninstall_log_path=uninstall_log_path,
        removed_install_root=removed_install_root,
        command=command_tuple,
        notes=tuple(notes),
    )

def _run_windows_installer(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    install_log_path: Path,
    label: str,
) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if label == "nsis-install":
        install_log_path.write_text(
            "\n".join(
                [
                    f"label={label}",
                    f"command={json.dumps(command)}",
                    f"exit_code={completed.returncode}",
                    "stdout:",
                    completed.stdout,
                    "stderr:",
                    completed.stderr,
                ]
            ),
            encoding="utf-8",
        )
    if completed.returncode == 0:
        return
    raise SmokeError(
        f"{label} failed with exit code {completed.returncode}\n"
        f"install_log={install_log_path}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}\n"
        f"log_tail:\n{_read_log_tail(install_log_path)}"
    )


def _install_windows_msi(
    *,
    artifact_path: Path,
    temp_root: Path,
    product_name: str,
    env: dict[str, str],
) -> WindowsInstallResult:
    install_log_path = temp_root / "msi-install.log"
    preexisting_candidates = {
        _normalize_path_text(path)
        for path in _find_windows_installed_app_candidates(product_name=product_name, env=env)
    }
    _run_windows_installer(
        [
            "msiexec",
            "/i",
            str(artifact_path),
            "/qn",
            "/norestart",
            "/l*v",
            str(install_log_path),
            "ALLUSERS=2",
            "MSIINSTALLPERUSER=1",
        ],
        cwd=temp_root,
        env=env,
        install_log_path=install_log_path,
        label="msiexec-install",
    )

    candidates = _find_windows_installed_app_candidates(product_name=product_name, env=env)
    app_executable = _choose_windows_installed_app(
        candidates,
        preexisting_candidates=preexisting_candidates,
        product_name=product_name,
    )
    return WindowsInstallResult(
        app_executable=app_executable,
        install_log_path=install_log_path,
        install_root=app_executable.parent,
        installer_kind="msi",
        installer_path=artifact_path,
    )


def _install_windows_nsis(
    *,
    artifact_path: Path,
    temp_root: Path,
    product_name: str,
    env: dict[str, str],
) -> WindowsInstallResult:
    install_log_path = temp_root / "nsis-install.log"
    preexisting_candidates = {
        _normalize_path_text(path)
        for path in _find_windows_installed_app_candidates(product_name=product_name, env=env)
    }
    _run_windows_installer(
        [str(artifact_path), "/S"],
        cwd=artifact_path.parent,
        env=env,
        install_log_path=install_log_path,
        label="nsis-install",
    )

    candidates = _find_windows_installed_app_candidates(product_name=product_name, env=env)
    app_executable = _choose_windows_installed_app(
        candidates,
        preexisting_candidates=preexisting_candidates,
        product_name=product_name,
    )
    return WindowsInstallResult(
        app_executable=app_executable,
        install_log_path=install_log_path,
        install_root=app_executable.parent,
        installer_kind="nsis",
        installer_path=artifact_path,
    )


def _install_windows_bundle(
    *,
    artifact_path: Path,
    temp_root: Path,
    product_name: str,
    env: dict[str, str],
) -> WindowsInstallResult:
    installer_kind = _artifact_kind(artifact_path, platform_tag="windows")
    if installer_kind == "nsis":
        return _install_windows_nsis(
            artifact_path=artifact_path,
            temp_root=temp_root,
            product_name=product_name,
            env=env,
        )
    return _install_windows_msi(
        artifact_path=artifact_path,
        temp_root=temp_root,
        product_name=product_name,
        env=env,
    )


def _write_wave(
    path: Path,
    *,
    channels: int,
    frequency_hz: float,
    phase_offset: float = 0.0,
    duration_s: float = 0.15,
    sample_rate_hz: int = 48_000,
) -> None:
    frames = max(128, int(duration_s * sample_rate_hz))
    samples: list[int] = []
    for index in range(frames):
        base = 0.32 * math.sin((2.0 * math.pi * frequency_hz * index / sample_rate_hz) + phase_offset)
        for channel_index in range(channels):
            sample = base if channel_index == 0 else 0.28 * math.sin(
                (2.0 * math.pi * (frequency_hz * 1.01) * index / sample_rate_hz) + phase_offset
            )
            samples.append(int(max(-1.0, min(1.0, sample)) * 32767.0))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _create_tiny_fixture(root: Path) -> Path:
    stems_dir = root / "stems"
    fixture_rate_hz = 44_100
    _write_wave(
        stems_dir / "kick.wav",
        channels=1,
        frequency_hz=55.0,
        sample_rate_hz=fixture_rate_hz,
    )
    _write_wave(
        stems_dir / "snare.wav",
        channels=1,
        frequency_hz=190.0,
        phase_offset=0.4,
        sample_rate_hz=fixture_rate_hz,
    )
    _write_wave(
        stems_dir / "pad_stereo.wav",
        channels=2,
        frequency_hz=330.0,
        phase_offset=0.8,
        sample_rate_hz=fixture_rate_hz,
    )
    return stems_dir


def _resolve_required_tool(tool_name: str) -> str:
    resolved = shutil.which(tool_name)
    if resolved is None:
        raise SmokeError(
            f"Required tool '{tool_name}' is not on PATH. "
            "Install FFmpeg/ffprobe before running the packaged desktop smoke."
        )
    return resolved


def _launch_smoke_app(
    *,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    summary_path: Path,
    timeout_s: float,
) -> tuple[int | None, str, str]:
    def _read_capture(handle: Any) -> str:
        handle.flush()
        handle.seek(0)
        return handle.read()

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_capture, tempfile.TemporaryFile(
        mode="w+",
        encoding="utf-8",
    ) as stderr_capture:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=stdout_capture,
            stderr=stderr_capture,
            text=True,
            encoding="utf-8",
        )

        started_at = time.monotonic()
        while True:
            if summary_path.is_file():
                break
            return_code = process.poll()
            if return_code is not None:
                stdout = _read_capture(stdout_capture)
                stderr = _read_capture(stderr_capture)
                raise SmokeError(
                    "Packaged app exited before writing the smoke summary.\n"
                    f"exit_code={return_code}\nstdout:\n{stdout}\nstderr:\n{stderr}"
                )
            if time.monotonic() - started_at > timeout_s:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                stdout = _read_capture(stdout_capture)
                stderr = _read_capture(stderr_capture)
                raise SmokeError(
                    "Timed out waiting for the packaged app smoke summary.\n"
                    f"stdout:\n{stdout}\nstderr:\n{stderr}"
                )
            time.sleep(1.0)

        summary_seen_at = time.monotonic()
        while process.poll() is None and time.monotonic() - summary_seen_at <= 30:
            time.sleep(1.0)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        stdout = _read_capture(stdout_capture)
        stderr = _read_capture(stderr_capture)
        return process.returncode, stdout, stderr


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SmokeError(f"{label} was not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SmokeError(f"{label} was not a JSON object: {path}")
    return payload


def _iter_outputs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for renderer_manifest in manifest.get("renderer_manifests", []):
        if not isinstance(renderer_manifest, dict):
            continue
        for output in renderer_manifest.get("outputs", []):
            if isinstance(output, dict):
                outputs.append(output)
    return outputs


def _output_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for output in _iter_outputs(manifest):
        output_id = _coerce_str(output.get("output_id")).strip()
        if output_id and output_id not in indexed:
            indexed[output_id] = output
    return indexed


def _deliverable_summary_rows(
    receipt: dict[str, Any],
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    for candidate in (
        receipt.get("deliverable_summary_rows"),
        manifest.get("deliverable_summary_rows"),
    ):
        if isinstance(candidate, list):
            rows = [item for item in candidate if isinstance(item, dict)]
            if rows:
                return rows
    return []


def _find_summary_row(
    *,
    deliverable: dict[str, Any],
    output: dict[str, Any],
    summary_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    deliverable_id = _coerce_str(deliverable.get("deliverable_id")).strip()
    output_id = _coerce_str(output.get("output_id")).strip()
    output_file_path = _coerce_str(output.get("file_path")).strip()
    for row in summary_rows:
        if _coerce_str(row.get("output_id")).strip() == output_id and output_id:
            return row
    for row in summary_rows:
        if _coerce_str(row.get("deliverable_id")).strip() == deliverable_id and deliverable_id:
            return row
    for row in summary_rows:
        if _coerce_str(row.get("file_path")).strip() == output_file_path and output_file_path:
            return row
    return {}


def _resolve_render_output_path(
    *,
    file_path: str,
    artifact_paths: dict[str, Any],
) -> Path | None:
    normalized_file_path = file_path.strip()
    if not normalized_file_path:
        return None
    candidate = Path(normalized_file_path)
    if candidate.is_absolute():
        return candidate

    workspace_dir = Path(str(artifact_paths.get("workspaceDir", ""))).resolve()
    render_manifest_path = Path(str(artifact_paths.get("renderManifestPath", ""))).resolve()
    render_dir = workspace_dir / "render"
    candidates = (
        render_dir / normalized_file_path,
        workspace_dir / normalized_file_path,
        render_manifest_path.parent / normalized_file_path,
    )
    for resolved in candidates:
        if resolved.is_file():
            return resolved
    return candidates[0]


def _decode_pcm_peak_abs(data: bytes, *, sample_width: int) -> float:
    peak = 0.0
    if sample_width == 1:
        for raw in data:
            sample = abs((int(raw) - 128) / 128.0)
            if sample > peak:
                peak = sample
        return peak

    if sample_width == 2:
        sample_count = len(data) // 2
        if sample_count <= 0:
            return 0.0
        for sample in struct.unpack(f"<{sample_count}h", data[: sample_count * 2]):
            normalized = abs(float(sample) / 32768.0)
            if normalized > peak:
                peak = normalized
        return peak

    if sample_width == 3:
        sample_count = len(data) // 3
        for index in range(sample_count):
            offset = index * 3
            word = data[offset: offset + 3]
            signed = int.from_bytes(
                word + (b"\xff" if word[2] & 0x80 else b"\x00"),
                byteorder="little",
                signed=True,
            )
            normalized = abs(float(signed) / 8388608.0)
            if normalized > peak:
                peak = normalized
        return peak

    if sample_width == 4:
        sample_count = len(data) // 4
        if sample_count <= 0:
            return 0.0
        for sample in struct.unpack(f"<{sample_count}i", data[: sample_count * 4]):
            normalized = abs(float(sample) / 2147483648.0)
            if normalized > peak:
                peak = normalized
        return peak

    raise SmokeError(f"Unsupported WAV sample width for packaged smoke audio check: {sample_width}")


def _read_wave_audio_summary(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "audio_exists": False,
            "audio_error": "missing_output_path",
            "audio_channels": None,
            "audio_frame_count": None,
            "audio_sample_rate_hz": None,
            "audio_duration_seconds": None,
            "audio_peak_abs": None,
            "audio_all_zero": None,
        }
    if not path.is_file():
        return {
            "audio_exists": False,
            "audio_error": "missing_output_file",
            "audio_channels": None,
            "audio_frame_count": None,
            "audio_sample_rate_hz": None,
            "audio_duration_seconds": None,
            "audio_peak_abs": None,
            "audio_all_zero": None,
        }
    try:
        with wave.open(str(path), "rb") as handle:
            channels = int(handle.getnchannels())
            sample_width = int(handle.getsampwidth())
            sample_rate_hz = int(handle.getframerate())
            frame_count = int(handle.getnframes())
            peak_abs = 0.0
            while True:
                chunk = handle.readframes(4096)
                if not chunk:
                    break
                chunk_peak = _decode_pcm_peak_abs(chunk, sample_width=sample_width)
                if chunk_peak > peak_abs:
                    peak_abs = chunk_peak
    except (OSError, EOFError, wave.Error) as exc:
        return {
            "audio_exists": False,
            "audio_error": f"wave_read_failed:{exc}",
            "audio_channels": None,
            "audio_frame_count": None,
            "audio_sample_rate_hz": None,
            "audio_duration_seconds": None,
            "audio_peak_abs": None,
            "audio_all_zero": None,
        }

    duration_seconds = (
        round(frame_count / sample_rate_hz, 6)
        if frame_count >= 0 and sample_rate_hz > 0
        else None
    )
    return {
        "audio_exists": True,
        "audio_error": None,
        "audio_channels": channels,
        "audio_frame_count": frame_count,
        "audio_sample_rate_hz": sample_rate_hz,
        "audio_duration_seconds": duration_seconds,
        "audio_peak_abs": round(peak_abs, 8),
        "audio_all_zero": peak_abs <= SILENT_OUTPUT_LINEAR_TOLERANCE,
    }


def _expected_receipt_lifecycle_status(result_bucket: str) -> str | None:
    if result_bucket in {"diagnostics_only", "full_failure"}:
        return "blocked"
    if result_bucket in {"partial_success", "success_no_master", "valid_master"}:
        return "completed"
    return None


def _normalize_summary_for_report(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        return None
    return json.loads(_canonical_payload(summary))


def _default_scene_binding_summary() -> dict[str, Any]:
    return {
        "status": "not_applicable",
        "reference_count": 0,
        "bound_count": 0,
        "unbound_count": 0,
        "rewritten_count": 0,
        "rewritten_refs": [],
        "binding_warnings": [],
        "failure_reason": None,
    }


def _normalize_scene_binding_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
    normalized = _default_scene_binding_summary()
    if isinstance(summary, dict):
        normalized.update(json.loads(_canonical_payload(summary)))
    return normalized


def _default_scene_stem_overlap_summary() -> dict[str, Any]:
    return {
        "status": "not_applicable",
        "scene_mode": None,
        "reference_count": 0,
        "matched_count": 0,
        "unique_matched_stem_count": 0,
        "unresolved_count": 0,
        "duplicate_bound_ref_count": 0,
        "overlap_ratio": None,
        "minimum_ratio": None,
        "duplicated_stem_ids": [],
        "unresolved_refs": [],
        "issue_ids": [],
        "failure_reason": None,
    }


def _default_preflight_summary() -> dict[str, Any]:
    return {
        "final_decision": "not_run",
        "blocked_gates": [],
        "issues": [],
        "primary_issue_id": None,
        "primary_message": None,
        "scene_stem_overlap_summary": _default_scene_stem_overlap_summary(),
    }


def _normalize_preflight_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
    normalized = _default_preflight_summary()
    if isinstance(summary, dict):
        normalized.update(json.loads(_canonical_payload(summary)))
    scene_overlap_summary = normalized.get("scene_stem_overlap_summary")
    normalized["scene_stem_overlap_summary"] = _default_scene_stem_overlap_summary()
    if isinstance(scene_overlap_summary, dict):
        normalized["scene_stem_overlap_summary"].update(
            json.loads(_canonical_payload(scene_overlap_summary))
        )
    return normalized


def _derive_root_cause(
    *,
    preflight_summary: dict[str, Any],
    deliverables_summary: dict[str, Any] | None,
    result_summary: dict[str, Any] | None,
    master_outputs: list[dict[str, Any]],
    has_decoded_audio_output: bool,
    has_valid_master_audio_output: bool,
) -> dict[str, Any]:
    primary_issue_id = _coerce_str(preflight_summary.get("primary_issue_id")).strip() or None
    primary_message = _coerce_str(preflight_summary.get("primary_message")).strip() or None
    scene_overlap_summary = preflight_summary.get("scene_stem_overlap_summary")
    if not isinstance(scene_overlap_summary, dict):
        scene_overlap_summary = _default_scene_stem_overlap_summary()

    overlap_status = _coerce_str(scene_overlap_summary.get("status")).strip() or None
    result_bucket = _coerce_str((deliverables_summary or {}).get("result_bucket")).strip() or None
    top_failure_reason = (
        _coerce_str((result_summary or {}).get("top_failure_reason")).strip()
        or _coerce_str((deliverables_summary or {}).get("top_failure_reason")).strip()
        or None
    )

    category: str | None = None
    message: str | None = None
    if primary_issue_id == "ISSUE.RENDER.SCENE_STEM_BINDING_EMPTY":
        category = "scene_overlap_empty"
        message = primary_message or "Scene references do not match analyzed stems."
    elif primary_issue_id == "ISSUE.RENDER.SCENE_STEM_BINDING_PARTIAL":
        category = "scene_overlap_partial"
        message = primary_message or "Scene references only partially match analyzed stems."
    elif primary_issue_id == "ISSUE.RENDER.SCENE_STEM_BINDING_AMBIGUOUS":
        category = "scene_overlap_ambiguous"
        message = primary_message or "Multiple scene references collapse onto the same analyzed stem."
    elif top_failure_reason == "RENDER_RESULT.NO_DECODABLE_STEMS" or not has_decoded_audio_output:
        category = "no_decodable_stems"
        message = (
            _coerce_str((result_summary or {}).get("message")).strip()
            or "No decodable stems reached any master deliverable."
        )
    elif (
        result_bucket not in _VALID_MASTER_RESULT_BUCKETS
        and master_outputs
        and not has_valid_master_audio_output
    ):
        category = "all_masters_invalid"
        message = (
            _coerce_str((result_summary or {}).get("message")).strip()
            or "All rendered masters were invalid or diagnostic-only outputs."
        )
        if top_failure_reason == "RENDER_RESULT.SILENT_OUTPUT":
            category = "silent_invalid_master"
            message = (
                _coerce_str((result_summary or {}).get("message")).strip()
                or "Rendered master outputs were effectively silent and invalid."
            )

    return {
        "category": category,
        "issue_id": primary_issue_id,
        "message": message,
        "overlap_status": overlap_status,
        "result_bucket": result_bucket,
        "top_failure_reason": top_failure_reason,
    }


def summarize_workspace_render_truth(*, artifact_paths: dict[str, Any]) -> dict[str, Any]:
    render_manifest_path = Path(str(artifact_paths.get("renderManifestPath", ""))).resolve()
    render_receipt_path = Path(str(artifact_paths.get("renderReceiptPath", ""))).resolve()
    render_qa_path = Path(str(artifact_paths.get("renderQaPath", ""))).resolve()

    manifest = _load_json_object(render_manifest_path, label="render manifest")
    receipt = _load_json_object(render_receipt_path, label="safe-render receipt")
    qa = _load_json_object(render_qa_path, label="render QA")

    manifest_deliverables_summary = _normalize_summary_for_report(
        manifest.get("deliverables_summary")
    )
    receipt_deliverables_summary = _normalize_summary_for_report(
        receipt.get("deliverables_summary")
    )
    qa_deliverables_summary = _normalize_summary_for_report(qa.get("deliverables_summary"))
    manifest_result_summary = _normalize_summary_for_report(manifest.get("result_summary"))
    receipt_result_summary = _normalize_summary_for_report(receipt.get("result_summary"))
    manifest_scene_binding_summary = _normalize_scene_binding_summary(
        manifest.get("scene_binding_summary")
    )
    receipt_scene_binding_summary = _normalize_scene_binding_summary(
        receipt.get("scene_binding_summary")
    )
    manifest_preflight_summary = _normalize_preflight_summary(
        manifest.get("preflight_summary")
    )
    receipt_preflight_summary = _normalize_preflight_summary(
        receipt.get("preflight_summary")
    )

    outputs_by_id = _output_index(manifest)
    summary_rows = _deliverable_summary_rows(receipt, manifest)
    master_outputs: list[dict[str, Any]] = []
    for deliverable in manifest.get("deliverables", []):
        if not isinstance(deliverable, dict):
            continue
        if _coerce_str(deliverable.get("artifact_role")).strip().lower() != "master":
            continue
        output_ids = [
            item.strip()
            for item in deliverable.get("output_ids", [])
            if isinstance(item, str) and item.strip()
        ] or [""]
        for output_id in output_ids:
            output = outputs_by_id.get(output_id, {})
            summary_row = _find_summary_row(
                deliverable=deliverable,
                output=output,
                summary_rows=summary_rows,
            )
            output_file_path = (
                _coerce_str(summary_row.get("file_path")).strip()
                or _coerce_str(output.get("file_path")).strip()
            )
            resolved_output_path = _resolve_render_output_path(
                file_path=output_file_path,
                artifact_paths=artifact_paths,
            )
            audio_summary = _read_wave_audio_summary(resolved_output_path)
            metadata = output.get("metadata")
            metadata_dict = metadata if isinstance(metadata, dict) else {}
            resampling = metadata_dict.get("resampling")
            resampling_dict = resampling if isinstance(resampling, dict) else {}
            sample_rate_hz = (
                _coerce_int(summary_row.get("sample_rate_hz"))
                or _coerce_int(output.get("sample_rate_hz"))
                or _coerce_int(audio_summary.get("audio_sample_rate_hz"))
            )
            rendered_frame_count = (
                _coerce_int(summary_row.get("rendered_frame_count"))
                or _coerce_int(deliverable.get("rendered_frame_count"))
                or _coerce_int(audio_summary.get("audio_frame_count"))
            )
            duration_seconds = (
                _coerce_float(summary_row.get("duration_seconds"))
                or _coerce_float(deliverable.get("duration_seconds"))
                or _coerce_float(audio_summary.get("audio_duration_seconds"))
            )
            master_outputs.append(
                {
                    "deliverable_id": _coerce_str(deliverable.get("deliverable_id")).strip() or None,
                    "output_id": output_id or None,
                    "layout": (
                        _coerce_str(summary_row.get("layout")).strip()
                        or _coerce_str(deliverable.get("target_layout_id")).strip()
                        or _coerce_str(output.get("layout_id")).strip()
                        or None
                    ),
                    "file_path": output_file_path or None,
                    "resolved_output_path": (
                        resolved_output_path.as_posix() if resolved_output_path is not None else None
                    ),
                    "status": _coerce_str(deliverable.get("status")).strip() or None,
                    "is_valid_master": bool(deliverable.get("is_valid_master")),
                    "decoded_stem_count": _coerce_int(deliverable.get("decoded_stem_count")),
                    "rendered_frame_count": rendered_frame_count,
                    "duration_seconds": round(duration_seconds, 6) if duration_seconds is not None else None,
                    "channel_count": (
                        _coerce_int(summary_row.get("channel_count"))
                        or _coerce_int(output.get("channel_count"))
                        or _coerce_int(audio_summary.get("audio_channels"))
                    ),
                    "sample_rate_hz": sample_rate_hz,
                    "failure_reason": _coerce_str(deliverable.get("failure_reason")).strip() or None,
                    "warning_codes": sorted(
                        {
                            code.strip()
                            for code in deliverable.get("warning_codes", [])
                            if isinstance(code, str) and code.strip()
                        }
                    ),
                    "uniform_source_sample_rate_hz": _coerce_int(
                        resampling_dict.get("uniform_source_sample_rate_hz")
                    ),
                    "output_sample_rate_hz": _coerce_int(
                        resampling_dict.get("output_sample_rate_hz")
                    ),
                    "sample_rate_policy": _coerce_str(
                        resampling_dict.get("sample_rate_policy")
                    ).strip() or None,
                    "sample_rate_policy_reason": _coerce_str(
                        resampling_dict.get("sample_rate_policy_reason")
                    ).strip() or None,
                    "resample_applied": (
                        bool(resampling_dict.get("resample_applied"))
                        if isinstance(resampling_dict.get("resample_applied"), bool)
                        else None
                    ),
                    **audio_summary,
                }
            )

    master_outputs.sort(
        key=lambda row: (
            _coerce_str(row.get("layout")).strip(),
            _coerce_str(row.get("file_path")).strip(),
            _coerce_str(row.get("deliverable_id")).strip(),
        )
    )
    valid_master_outputs = [
        row
        for row in master_outputs
        if row.get("is_valid_master") is True
    ]
    qa_error_ids = sorted(
        {
            _coerce_str(issue.get("issue_id")).strip()
            for issue in qa.get("issues", [])
            if isinstance(issue, dict) and _coerce_str(issue.get("severity")).strip() == "error"
        }
    )
    result_bucket = _coerce_str(
        (manifest_deliverables_summary or {}).get("result_bucket")
    ).strip()
    receipt_status = _coerce_str(receipt.get("status")).strip()
    expected_receipt_status = _expected_receipt_lifecycle_status(result_bucket)
    scene_overlap_summary = manifest_preflight_summary.get("scene_stem_overlap_summary")
    if not isinstance(scene_overlap_summary, dict):
        scene_overlap_summary = _default_scene_stem_overlap_summary()
    has_non_zero_scene_report_overlap = (
        _coerce_str(scene_overlap_summary.get("status")).strip() in {"clean", "partial"}
        and (_coerce_int(scene_overlap_summary.get("matched_count")) or 0) > 0
    )
    root_cause = _derive_root_cause(
        preflight_summary=manifest_preflight_summary,
        deliverables_summary=manifest_deliverables_summary,
        result_summary=manifest_result_summary,
        master_outputs=master_outputs,
        has_decoded_audio_output=any(
            isinstance(row.get("decoded_stem_count"), int) and row["decoded_stem_count"] > 0
            for row in master_outputs
        ),
        has_valid_master_audio_output=any(
            (
                row.get("audio_exists") is True
                and row.get("audio_all_zero") is False
                and isinstance(row.get("decoded_stem_count"), int)
                and row["decoded_stem_count"] > 0
                and isinstance(row.get("duration_seconds"), (int, float))
                and float(row["duration_seconds"]) > MIN_MEANINGFUL_DURATION_SECONDS
            )
            for row in valid_master_outputs
        ),
    )
    return {
        "agreement": {
            "deliverables_summary": (
                manifest_deliverables_summary is not None
                and manifest_deliverables_summary == receipt_deliverables_summary
                and manifest_deliverables_summary == qa_deliverables_summary
            ),
            "scene_binding_summary": (
                manifest_scene_binding_summary == receipt_scene_binding_summary
            ),
            "preflight_summary": (
                manifest_preflight_summary == receipt_preflight_summary
            ),
            "result_summary": (
                manifest_result_summary is not None
                and manifest_result_summary == receipt_result_summary
            ),
            "receipt_lifecycle_status": (
                expected_receipt_status is not None and receipt_status == expected_receipt_status
            ),
        },
        "deliverables_summary": manifest_deliverables_summary,
        "scene_binding_summary": manifest_scene_binding_summary,
        "preflight_summary": manifest_preflight_summary,
        "result_summary": manifest_result_summary,
        "receipt_status": receipt_status or None,
        "expected_receipt_status": expected_receipt_status,
        "master_outputs": master_outputs,
        "valid_master_outputs": valid_master_outputs,
        "has_decoded_audio_output": any(
            isinstance(row.get("decoded_stem_count"), int) and row["decoded_stem_count"] > 0
            for row in master_outputs
        ),
        "has_meaningful_duration_output": any(
            isinstance(row.get("duration_seconds"), (int, float))
            and float(row["duration_seconds"]) > MIN_MEANINGFUL_DURATION_SECONDS
            for row in valid_master_outputs
        ),
        "has_non_silent_output": any(
            row.get("audio_all_zero") is False
            for row in valid_master_outputs
        ),
        "has_valid_master_audio_output": any(
            (
                row.get("audio_exists") is True
                and row.get("audio_all_zero") is False
                and isinstance(row.get("decoded_stem_count"), int)
                and row["decoded_stem_count"] > 0
                and isinstance(row.get("duration_seconds"), (int, float))
                and float(row["duration_seconds"]) > MIN_MEANINGFUL_DURATION_SECONDS
            )
            for row in valid_master_outputs
        ),
        "has_uniform_rate_preservation_output": any(
            (
                isinstance(row.get("uniform_source_sample_rate_hz"), int)
                and row["uniform_source_sample_rate_hz"] > 0
                and row.get("sample_rate_hz") == row.get("uniform_source_sample_rate_hz")
                and row.get("output_sample_rate_hz") == row.get("uniform_source_sample_rate_hz")
                and row.get("sample_rate_policy") == "uniform_source_rate_preserve"
            )
            for row in valid_master_outputs
        ),
        "has_non_zero_scene_report_overlap": has_non_zero_scene_report_overlap,
        "root_cause": root_cause,
        "qa_error_ids": qa_error_ids,
        "minimum_meaningful_duration_seconds": MIN_MEANINGFUL_DURATION_SECONDS,
    }


def _validate_workspace_render_truth(*, artifact_paths: dict[str, Any]) -> dict[str, Any]:
    truth = summarize_workspace_render_truth(artifact_paths=artifact_paths)
    agreement = truth.get("agreement")
    if not isinstance(agreement, dict):
        raise SmokeError("Packaged smoke render truth summary was malformed.")
    if agreement.get("deliverables_summary") is not True:
        raise SmokeError(
            "Packaged smoke render artifacts disagreed about deliverable status.\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    if agreement.get("scene_binding_summary") is not True:
        raise SmokeError(
            "Packaged smoke manifest and receipt disagreed about scene binding normalization.\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    if agreement.get("preflight_summary") is not True:
        raise SmokeError(
            "Packaged smoke manifest and receipt disagreed about preflight overlap diagnostics.\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    if agreement.get("result_summary") is not True:
        raise SmokeError(
            "Packaged smoke manifest and receipt disagreed about the top-level render result summary.\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    if agreement.get("receipt_lifecycle_status") is not True:
        raise SmokeError(
            "Packaged smoke receipt lifecycle status did not match the deliverable result bucket.\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    root_cause = truth.get("root_cause")
    if not isinstance(root_cause, dict):
        root_cause = {}
    root_cause_category = _coerce_str(root_cause.get("category")).strip()
    root_cause_message = _coerce_str(root_cause.get("message")).strip()
    if root_cause_category == "scene_overlap_empty":
        raise SmokeError(
            "Packaged smoke failed before render because scene references do not match analyzed stems.\n"
            f"root_cause={root_cause_message or 'scene/report overlap was zero'}\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    if truth.get("has_non_zero_scene_report_overlap") is not True:
        preflight_summary = truth.get("preflight_summary")
        if isinstance(preflight_summary, dict):
            scene_overlap_summary = preflight_summary.get("scene_stem_overlap_summary")
            if isinstance(scene_overlap_summary, dict) and _coerce_str(
                scene_overlap_summary.get("status")
            ).strip() in {"clean", "partial", "failed"}:
                raise SmokeError(
                    "Packaged smoke did not verify any non-zero overlap between the scene and analyzed session stems.\n"
                    f"{json.dumps(truth, indent=2, sort_keys=True)}"
                )
    if truth.get("has_decoded_audio_output") is not True:
        if root_cause_category == "no_decodable_stems":
            raise SmokeError(
                "Packaged smoke failed because no decodable stems reached any master deliverable.\n"
                f"root_cause={root_cause_message or 'none of the planned stems decoded'}\n"
                f"{json.dumps(truth, indent=2, sort_keys=True)}"
            )
        raise SmokeError(
            "Packaged smoke did not produce any deliverable with decoded_stem_count > 0.\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    if truth.get("has_valid_master_audio_output") is not True and root_cause_category in {
        "all_masters_invalid",
        "silent_invalid_master",
    }:
        raise SmokeError(
            "Packaged smoke only produced invalid masters; no deliverable qualified as a valid master.\n"
            f"root_cause={root_cause_message or 'all master outputs were invalid'}\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    if truth.get("has_meaningful_duration_output") is not True:
        raise SmokeError(
            "Packaged smoke did not produce any valid master longer than the minimum meaningful duration.\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    if truth.get("has_non_silent_output") is not True:
        raise SmokeError(
            "Packaged smoke only produced all-zero valid-master outputs.\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    if truth.get("has_valid_master_audio_output") is not True:
        raise SmokeError(
            "Packaged smoke did not produce a valid master with decoded audio, meaningful duration, and non-silent signal.\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    if truth.get("has_uniform_rate_preservation_output") is not True:
        raise SmokeError(
            "Packaged smoke did not preserve the uniform source sample rate in the rendered valid master.\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    result_bucket = _coerce_str(
        ((truth.get("deliverables_summary") or {}) if isinstance(truth.get("deliverables_summary"), dict) else {}).get("result_bucket")
    ).strip()
    if result_bucket not in _VALID_MASTER_RESULT_BUCKETS:
        raise SmokeError(
            "Packaged smoke ended without a valid-master result bucket.\n"
            f"{json.dumps(truth, indent=2, sort_keys=True)}"
        )
    return truth


def _validate_summary(
    *,
    summary: dict[str, Any],
    repo_root: Path,
    allow_repo_data_root: bool,
) -> dict[str, Any]:
    if not bool(summary.get("appLaunchVerified")):
        raise SmokeError("Packaged desktop smoke summary did not confirm the app launch.")
    if not bool(summary.get("ok")):
        raise SmokeError(
            "Packaged desktop smoke summary reported failure.\n"
            f"{json.dumps(summary, indent=2, sort_keys=True)}"
        )

    doctor = summary.get("doctor")
    if not isinstance(doctor, dict) or not bool(doctor.get("ok")):
        raise SmokeError("Doctor did not complete successfully in packaged smoke mode.")
    for exit_code_key, command_label in (
        ("versionExitCode", "--version"),
        ("pluginsExitCode", "plugins validate"),
        ("envDoctorExitCode", "env doctor"),
    ):
        if doctor.get(exit_code_key) != 0:
            raise SmokeError(
                "Doctor did not complete successfully in packaged smoke mode.\n"
                f"sidecar_probe={command_label}\n"
                f"exit_code={doctor.get(exit_code_key)!r}"
            )

    checks = doctor.get("checks")
    if not isinstance(checks, dict):
        raise SmokeError("Doctor summary did not include env-doctor checks.")

    required_true = (
        "cache_dir_writable",
        "data_root_readable",
        "ffmpeg_available",
        "ffprobe_available",
        "numpy_available",
        "reportlab_available",
        "temp_dir_writable",
    )
    failing_checks = [key for key in required_true if checks.get(key) is not True]
    if failing_checks:
        raise SmokeError(f"Doctor checks failed in packaged smoke mode: {', '.join(failing_checks)}")

    data_root = doctor.get("dataRoot")
    if isinstance(data_root, str) and data_root and not allow_repo_data_root:
        if _path_is_under(data_root, repo_root):
            raise SmokeError(
                "Packaged sidecar resolved MMO data back to the repo checkout instead of bundled data.\n"
                f"data_root={data_root}"
            )

    artifact_paths = summary.get("artifactPaths")
    if not isinstance(artifact_paths, dict):
        raise SmokeError("Smoke summary did not include artifact paths.")

    required_artifact_keys = (
        "busPlanCsvPath",
        "busPlanPath",
        "projectValidationPath",
        "renderManifestPath",
        "renderQaPath",
        "renderReceiptPath",
        "reportPath",
        "scanReportPath",
        "sceneLintPath",
        "scenePath",
        "stemsMapPath",
    )
    missing_files = [
        f"{key}={path_value}"
        for key in required_artifact_keys
        for path_value in [artifact_paths.get(key)]
        if not isinstance(path_value, str) or not Path(path_value).is_file()
    ]
    if missing_files:
        raise SmokeError(
            "Packaged smoke did not produce the expected artifact files.\n"
            + "\n".join(missing_files)
        )

    render_dir = artifact_paths.get("workspaceDir")
    if not isinstance(render_dir, str) or not Path(render_dir).is_dir():
        raise SmokeError("Smoke summary workspaceDir is missing or not a directory.")

    workflow_stages_completed = summary.get("workflowStagesCompleted")
    if not isinstance(workflow_stages_completed, list):
        raise SmokeError("Smoke summary did not include workflowStagesCompleted.")
    normalized_stages = [
        stage.strip()
        for stage in workflow_stages_completed
        if isinstance(stage, str) and stage.strip()
    ]
    if normalized_stages != list(_EXPECTED_SMOKE_WORKFLOW_STAGES):
        raise SmokeError(
            "Packaged smoke did not complete the expected desktop workflow sequence.\n"
            f"expected={list(_EXPECTED_SMOKE_WORKFLOW_STAGES)}\n"
            f"actual={normalized_stages}"
        )

    results_inspection = summary.get("resultsInspection")
    if not isinstance(results_inspection, dict):
        raise SmokeError("Smoke summary did not include resultsInspection.")
    for key in (
        "manifestLoaded",
        "receiptLoaded",
        "qaLoaded",
        "deliverablesSummaryLoaded",
        "resultSummaryLoaded",
        "deliverableSummaryRowsLoaded",
    ):
        if results_inspection.get(key) is not True:
            raise SmokeError(
                "Packaged smoke did not finish inspecting the packaged render outputs in the Results view.\n"
                f"missing={key}"
            )

    return _validate_workspace_render_truth(artifact_paths=artifact_paths)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run packaged MMO Desktop smoke checks against a built Tauri bundle.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root (defaults to this script's parent).",
    )
    parser.add_argument(
        "--bundle-root",
        default=str(DEFAULT_BUNDLE_ROOT),
        help="Directory containing built Tauri bundle artifacts.",
    )
    parser.add_argument(
        "--artifact",
        default="",
        help="Explicit path to the bundle artifact to smoke (.msi, .app, or .AppImage).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=300.0,
        help="Timeout for the packaged app smoke run.",
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        help="Render target to use for the packaged smoke run.",
    )
    parser.add_argument(
        "--layout-standard",
        default=DEFAULT_LAYOUT_STANDARD,
        help="Layout standard to use for the packaged smoke run.",
    )
    parser.add_argument(
        "--allow-repo-data-root",
        action="store_true",
        help="Allow the packaged sidecar to resolve data_root back to the repo checkout.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary smoke workspace on disk for debugging.",
    )
    parser.add_argument(
        "--windows-install-state-path",
        default="",
        help="Optional JSON path for persisting Windows install state for later signature checks or cleanup.",
    )
    parser.add_argument(
        "--defer-windows-cleanup",
        action="store_true",
        help="Do not uninstall the Windows smoke install automatically; requires --windows-install-state-path.",
    )
    parser.add_argument(
        "--cleanup-windows-install-state",
        default="",
        help="Run best-effort Windows uninstall cleanup from a saved install-state JSON file, then exit.",
    )
    return parser.parse_args()


def _cleanup_windows_install_state(
    *,
    state_path: Path,
    keep_temp: bool,
) -> int:
    payload = _load_windows_install_state(state_path)
    if payload is None:
        print(
            json.dumps(
                {
                    "cleanup": {
                        "attempted": False,
                        "notes": ["Windows install state file was missing or unreadable."],
                        "ok": False,
                    },
                    "state_path": state_path.as_posix(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    cleanup_result = _cleanup_windows_install(state=payload, env=os.environ.copy())
    temp_root_raw = payload.get("temp_root")
    if not keep_temp and isinstance(temp_root_raw, str) and temp_root_raw:
        shutil.rmtree(Path(temp_root_raw), ignore_errors=True)

    print(
        json.dumps(
            {
                "cleanup": _windows_cleanup_payload(cleanup_result),
                "state_path": state_path.as_posix(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    args = _parse_args()
    if args.cleanup_windows_install_state:
        return _cleanup_windows_install_state(
            state_path=Path(args.cleanup_windows_install_state).resolve(),
            keep_temp=bool(args.keep_temp),
        )

    if args.defer_windows_cleanup and not args.windows_install_state_path:
        print(
            "error: --defer-windows-cleanup requires --windows-install-state-path",
            file=sys.stderr,
        )
        return 2

    repo_root = Path(args.repo_root).resolve()
    platform_tag = _platform_tag()
    product_name = _read_product_name(repo_root)
    windows_install_state_path = (
        Path(args.windows_install_state_path).resolve()
        if isinstance(args.windows_install_state_path, str) and args.windows_install_state_path.strip()
        else None
    )
    defer_windows_cleanup = bool(args.defer_windows_cleanup)

    if args.artifact:
        artifact_path = Path(args.artifact).resolve()
    else:
        bundle_root = Path(args.bundle_root)
        if not bundle_root.is_absolute():
            bundle_root = (repo_root / bundle_root).resolve()
        artifact_path = _find_artifact(bundle_root=bundle_root, platform_tag=platform_tag)
    if not artifact_path.exists():
        print(f"error: artifact does not exist: {artifact_path}", file=sys.stderr)
        return 2

    temp_root = Path(tempfile.mkdtemp(prefix="mmo-desktop-smoke-")).resolve()
    env = os.environ.copy()
    windows_install_result: WindowsInstallResult | None = None
    installed_sidecar_paths: list[Path] = []
    cleanup_result: WindowsCleanupResult | None = None
    result_payload: dict[str, Any] | None = None
    error_message: str | None = None
    launch_stdout = ""
    launch_stderr = ""
    try:
        fixture_root = temp_root / "fixture"
        stems_dir = _create_tiny_fixture(fixture_root)
        workspace_dir = temp_root / "workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        summary_path = temp_root / "desktop-smoke-summary.json"
        sidecar_bundle_root: Path | None = None

        if platform_tag == "windows":
            windows_install_result = _install_windows_bundle(
                artifact_path=artifact_path,
                temp_root=temp_root,
                product_name=product_name,
                env=env,
            )
            sidecar_bundle_root = windows_install_result.install_root
            installed_sidecar_paths = _find_sidecar_binaries(
                sidecar_bundle_root,
                platform_tag=platform_tag,
            )
            if windows_install_state_path is not None:
                _write_windows_install_state(
                    windows_install_state_path,
                    _windows_install_state_payload(
                        artifact_path=artifact_path,
                        product_name=product_name,
                        temp_root=temp_root,
                        install_result=windows_install_result,
                        installed_sidecar_paths=installed_sidecar_paths,
                    ),
                )
            command = [str(windows_install_result.app_executable)]
            launch_cwd = windows_install_result.app_executable.parent
        elif platform_tag == "macos":
            app_executable = _find_main_app_executable(
                artifact_path,
                platform_tag=platform_tag,
                product_name=product_name,
            )
            sidecar_bundle_root = artifact_path
            command = [str(app_executable)]
            launch_cwd = app_executable.parent
        else:
            command = [str(artifact_path)]
            launch_cwd = artifact_path.parent

        env["MMO_CACHE_DIR"] = os.fspath(temp_root / "cache")
        env["MMO_TEMP_DIR"] = os.fspath(temp_root / "temp")
        env["MMO_DESKTOP_SMOKE_LAYOUT_STANDARD"] = args.layout_standard
        env["MMO_DESKTOP_SMOKE_RENDER_TARGET"] = args.target
        env["MMO_DESKTOP_SMOKE_STEMS_DIR"] = os.fspath(stems_dir)
        env["MMO_DESKTOP_SMOKE_SUMMARY_PATH"] = os.fspath(summary_path)
        env["MMO_DESKTOP_SMOKE_WORKSPACE_DIR"] = os.fspath(workspace_dir)
        env["MMO_FFMPEG_PATH"] = _resolve_required_tool("ffmpeg")
        env["MMO_FFPROBE_PATH"] = _resolve_required_tool("ffprobe")
        if platform_tag == "linux" and artifact_path.suffix == ".AppImage":
            env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")

        if sidecar_bundle_root is not None:
            _probe_packaged_sidecar(
                bundle_root=sidecar_bundle_root,
                platform_tag=platform_tag,
                env=env,
            )

        return_code, stdout, stderr = _launch_smoke_app(
            command=command,
            cwd=launch_cwd,
            env=env,
            summary_path=summary_path,
            timeout_s=float(args.timeout_seconds),
        )
        launch_stdout = stdout
        launch_stderr = stderr

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(summary, dict):
            raise SmokeError("Packaged desktop smoke summary was not a JSON object.")

        render_truth = _validate_summary(
            summary=summary,
            repo_root=repo_root,
            allow_repo_data_root=bool(args.allow_repo_data_root),
        )

        payload = {
            "artifact": artifact_path.as_posix(),
            "ok": True,
            "platform": platform_tag,
            "return_code": return_code,
            "stderr_lines": [line for line in stderr.splitlines() if line.strip()],
            "stdout_lines": [line for line in stdout.splitlines() if line.strip()],
            "render_truth": render_truth,
            "summary_path": summary_path.as_posix(),
            "workspace_dir": workspace_dir.as_posix(),
        }
        if windows_install_result is not None:
            payload.update(
                {
                    "install_log_path": windows_install_result.install_log_path.as_posix(),
                    "install_root": windows_install_result.install_root.as_posix(),
                    "installed_sidecar_paths": [path.as_posix() for path in installed_sidecar_paths],
                    "installer_kind": windows_install_result.installer_kind,
                    "installer_path": windows_install_result.installer_path.as_posix(),
                    "launched_app": windows_install_result.app_executable.as_posix(),
                }
            )
        if defer_windows_cleanup and windows_install_result is not None:
            payload["cleanup_deferred"] = True
            if windows_install_state_path is not None:
                payload["windows_install_state_path"] = windows_install_state_path.as_posix()
        result_payload = payload
    except SmokeError as exc:
        error_message = str(exc)
    finally:
        if platform_tag == "windows" and windows_install_result is not None and not defer_windows_cleanup:
            cleanup_result = _cleanup_windows_install(
                state=_windows_install_state_payload(
                    artifact_path=artifact_path,
                    product_name=product_name,
                    temp_root=temp_root,
                    install_result=windows_install_result,
                    installed_sidecar_paths=installed_sidecar_paths,
                ),
                env=env,
            )

        if args.keep_temp or defer_windows_cleanup:
            reason = (
                " for deferred Windows cleanup"
                if defer_windows_cleanup and not args.keep_temp
                else ""
            )
            print(f"packaged desktop smoke temp root kept at {temp_root}{reason}", file=sys.stderr)
        else:
            shutil.rmtree(temp_root, ignore_errors=True)

    if result_payload is not None:
        if cleanup_result is not None:
            result_payload["cleanup"] = _windows_cleanup_payload(cleanup_result)
        print(json.dumps(result_payload, indent=2, sort_keys=True))
        return 0

    if error_message is not None:
        if platform_tag == "windows":
            install_log_path = (
                windows_install_result.install_log_path
                if windows_install_result is not None
                else temp_root / "installer.log"
            )
            install_root = windows_install_result.install_root if windows_install_result is not None else None
            message_parts = [
                error_message,
                _windows_install_receipt(
                    product_name=product_name,
                    env=env,
                    installer_path=artifact_path,
                    install_log_path=install_log_path,
                    install_root=install_root,
                    launch_stdout=launch_stdout,
                    launch_stderr=launch_stderr,
                ),
            ]
            if cleanup_result is not None:
                message_parts.append(_windows_cleanup_receipt(cleanup_result))
            elif defer_windows_cleanup and windows_install_result is not None:
                message_parts.append(
                    "Windows cleanup receipt:\n"
                    "- attempted: False\n"
                    "- note: Cleanup was deferred to a follow-up step."
                )
            error_message = "\n".join(message_parts)
        print(f"error: {error_message}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
