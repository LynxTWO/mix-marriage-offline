"""Run packaged MMO Desktop smoke checks against built Tauri bundles."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_ROOT = REPO_ROOT / "gui" / "desktop-tauri" / "src-tauri" / "target" / "release" / "bundle"
DEFAULT_TARGET = "TARGET.STEREO.2_0"
DEFAULT_LAYOUT_STANDARD = "SMPTE"


class SmokeError(RuntimeError):
    """Raised when the packaged desktop smoke flow fails."""


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


def _read_product_name(repo_root: Path) -> str:
    config_path = repo_root / "gui" / "desktop-tauri" / "src-tauri" / "tauri.conf.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    product_name = payload.get("productName")
    if not isinstance(product_name, str) or not product_name.strip():
        raise SmokeError(f"Missing productName in {config_path}")
    return product_name.strip()


def _artifact_suffixes_for_platform(platform_tag: str) -> tuple[str, ...]:
    if platform_tag == "windows":
        return (".msi",)
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
    return candidates[0]


def _looks_like_sidecar_name(name: str, platform_tag: str) -> bool:
    normalized = name.casefold()
    if not normalized.startswith("mmo-"):
        return False
    if platform_tag == "windows":
        return "windows" in normalized or "msvc" in normalized
    if platform_tag == "macos":
        return "darwin" in normalized or "apple" in normalized
    if platform_tag == "linux":
        return "linux" in normalized or "gnu" in normalized
    return False


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


def _find_sidecar_binary(root: Path, *, platform_tag: str) -> Path:
    candidates = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and _looks_like_sidecar_name(path.name, platform_tag)
    )
    if not candidates:
        raise SmokeError(f"Could not find a packaged sidecar under {root}")
    return candidates[0]


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


def _stage_windows_installer(*, artifact_path: Path, stage_root: Path, product_name: str) -> Path:
    stage_root.mkdir(parents=True, exist_ok=True)
    command = [
        "msiexec",
        "/a",
        str(artifact_path),
        "/qn",
        f"TARGETDIR={stage_root}",
    ]
    _run_command(command, cwd=stage_root, label="msiexec-admin")

    preferred = stage_root / f"{product_name}.exe"
    if preferred.is_file():
        return preferred
    return _find_main_app_executable(stage_root, platform_tag="windows", product_name=product_name)


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
    _write_wave(stems_dir / "kick.wav", channels=1, frequency_hz=55.0)
    _write_wave(stems_dir / "snare.wav", channels=1, frequency_hz=190.0, phase_offset=0.4)
    _write_wave(stems_dir / "pad_stereo.wav", channels=2, frequency_hz=330.0, phase_offset=0.8)
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
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    started_at = time.monotonic()
    while True:
        if summary_path.is_file():
            break
        return_code = process.poll()
        if return_code is not None:
            stdout, stderr = process.communicate()
            raise SmokeError(
                "Packaged app exited before writing the smoke summary.\n"
                f"exit_code={return_code}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        if time.monotonic() - started_at > timeout_s:
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            raise SmokeError(
                "Timed out waiting for the packaged app smoke summary.\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        time.sleep(1.0)

    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()

    return process.returncode, stdout, stderr


def _validate_summary(
    *,
    summary: dict[str, Any],
    repo_root: Path,
    allow_repo_data_root: bool,
) -> None:
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
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.repo_root).resolve()
    platform_tag = _platform_tag()
    product_name = _read_product_name(repo_root)

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
    try:
        fixture_root = temp_root / "fixture"
        stems_dir = _create_tiny_fixture(fixture_root)
        workspace_dir = temp_root / "workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        summary_path = temp_root / "desktop-smoke-summary.json"
        sidecar_bundle_root: Path | None = None

        if platform_tag == "windows":
            stage_root = temp_root / "installed"
            app_executable = _stage_windows_installer(
                artifact_path=artifact_path,
                stage_root=stage_root,
                product_name=product_name,
            )
            sidecar_bundle_root = stage_root
            command = [str(app_executable)]
            launch_cwd = app_executable.parent
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

        env = os.environ.copy()
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

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(summary, dict):
            raise SmokeError("Packaged desktop smoke summary was not a JSON object.")

        _validate_summary(
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
            "summary_path": summary_path.as_posix(),
            "workspace_dir": workspace_dir.as_posix(),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except SmokeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if args.keep_temp:
            print(f"packaged desktop smoke temp root kept at {temp_root}", file=sys.stderr)
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
