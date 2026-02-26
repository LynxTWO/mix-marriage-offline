"""Build one-click MMO installers for Windows, macOS, and Linux."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSION = "0.0.0"
_APP_ICON_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7+Lk0AAAAA"
    "SUVORK5CYII="
)


class InstallerBuildError(RuntimeError):
    """Raised when installer packaging or signing fails."""


def _platform_tag() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform.replace("/", "_")


def _arch_tag() -> str:
    raw = platform.machine().strip().lower()
    mapping = {
        "amd64": "x86_64",
        "x86-64": "x86_64",
        "x64": "x86_64",
        "aarch64": "arm64",
        "arm64e": "arm64",
    }
    normalized = mapping.get(raw, raw)
    return normalized or "unknown"


def _binary_suffix(platform_tag: str) -> str:
    return ".exe" if platform_tag == "windows" else ""


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    label: str,
    env: dict[str, str] | None = None,
) -> None:
    printable = " ".join(shlex.quote(part) for part in command)
    print(f"[{label}] {printable}")
    completed = subprocess.run(command, cwd=cwd, env=env)
    if completed.returncode != 0:
        raise InstallerBuildError(f"{label} failed with exit code {completed.returncode}")


def _write_sha256(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum_path = Path(f"{path}.sha256")
    checksum_path.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return checksum_path


def _detect_repo_version(repo_root: Path) -> str:
    init_path = repo_root / "src" / "mmo" / "__init__.py"
    if not init_path.exists():
        return DEFAULT_VERSION
    text = init_path.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if match is None:
        return DEFAULT_VERSION
    version = match.group(1).strip()
    return version or DEFAULT_VERSION


def _normalize_version(raw: str) -> str:
    version = raw.strip()
    if version.lower().startswith("v"):
        version = version[1:]
    return version or DEFAULT_VERSION


def _resolve_binary(
    *,
    input_dir: Path,
    artifact_name: str,
    platform_tag: str,
    arch_tag: str,
) -> Path:
    expected = input_dir / f"{artifact_name}-{platform_tag}-{arch_tag}{_binary_suffix(platform_tag)}"
    if expected.exists():
        return expected
    raise InstallerBuildError(
        f"Required binary not found: {expected}. "
        "Run tools/build_binaries.py --with-gui first."
    )


def _copy_executable(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if not sys.platform.startswith("win"):
        destination.chmod(destination.stat().st_mode | 0o111)


def _sign_windows_executable(
    path: Path,
    *,
    signing_enabled: bool,
    strict_signing: bool,
) -> None:
    if not signing_enabled:
        return

    pfx_path_raw = os.getenv("MMO_WINDOWS_PFX_PATH", "").strip()
    if not pfx_path_raw:
        print(f"[sign/windows] Skipping {path.name}: MMO_WINDOWS_PFX_PATH not configured.")
        return

    signtool = shutil.which("signtool")
    if signtool is None:
        message = "signtool is not available on PATH."
        if strict_signing:
            raise InstallerBuildError(message)
        print(f"[sign/windows] Skipping {path.name}: {message}")
        return

    pfx_path = Path(pfx_path_raw).expanduser().resolve()
    if not pfx_path.exists():
        raise InstallerBuildError(f"Configured PFX does not exist: {pfx_path}")

    command = [
        signtool,
        "sign",
        "/fd",
        "SHA256",
        "/f",
        str(pfx_path),
    ]
    pfx_password = os.getenv("MMO_WINDOWS_PFX_PASSWORD", "")
    if pfx_password:
        command.extend(["/p", pfx_password])

    timestamp_url = os.getenv("MMO_WINDOWS_TIMESTAMP_URL", "http://timestamp.digicert.com").strip()
    if timestamp_url:
        command.extend(["/tr", timestamp_url, "/td", "SHA256"])
    command.append(str(path))
    _run_command(command, cwd=path.parent, label="sign/windows")


def _sign_macos_app(
    app_path: Path,
    *,
    signing_enabled: bool,
    strict_signing: bool,
) -> None:
    if not signing_enabled:
        return

    identity = os.getenv("MMO_MACOS_SIGN_IDENTITY", "").strip()
    if not identity:
        print(
            f"[sign/macos] Skipping {app_path.name}: MMO_MACOS_SIGN_IDENTITY not configured."
        )
        return

    codesign = shutil.which("codesign")
    if codesign is None:
        message = "codesign is not available on PATH."
        if strict_signing:
            raise InstallerBuildError(message)
        print(f"[sign/macos] Skipping {app_path.name}: {message}")
        return

    _run_command(
        [
            codesign,
            "--force",
            "--deep",
            "--options",
            "runtime",
            "--timestamp",
            "--sign",
            identity,
            str(app_path),
        ],
        cwd=app_path.parent,
        label="sign/macos",
    )
    _run_command(
        [codesign, "--verify", "--deep", "--strict", "--verbose=2", str(app_path)],
        cwd=app_path.parent,
        label="verify/macos",
    )


def _sign_linux_appimage(
    appimage_path: Path,
    *,
    signing_enabled: bool,
    strict_signing: bool,
) -> Path | None:
    if not signing_enabled:
        return None

    key_id = os.getenv("MMO_LINUX_GPG_KEY_ID", "").strip()
    if not key_id:
        print(
            f"[sign/linux] Skipping {appimage_path.name}: MMO_LINUX_GPG_KEY_ID not configured."
        )
        return None

    gpg = shutil.which("gpg")
    if gpg is None:
        message = "gpg is not available on PATH."
        if strict_signing:
            raise InstallerBuildError(message)
        print(f"[sign/linux] Skipping {appimage_path.name}: {message}")
        return None

    signature_path = Path(f"{appimage_path}.asc")
    _run_command(
        [
            gpg,
            "--batch",
            "--yes",
            "--armor",
            "--detach-sign",
            "--local-user",
            key_id,
            "--output",
            str(signature_path),
            str(appimage_path),
        ],
        cwd=appimage_path.parent,
        label="sign/linux",
    )
    return signature_path


def _build_windows_installer(
    *,
    input_dir: Path,
    output_dir: Path,
    version: str,
    arch_tag: str,
    cli_name: str,
    gui_name: str,
    signing_enabled: bool,
    strict_signing: bool,
) -> list[Path]:
    cli_binary = _resolve_binary(
        input_dir=input_dir,
        artifact_name=cli_name,
        platform_tag="windows",
        arch_tag=arch_tag,
    )
    gui_binary = _resolve_binary(
        input_dir=input_dir,
        artifact_name=gui_name,
        platform_tag="windows",
        arch_tag=arch_tag,
    )

    stage_dir = output_dir / ".installer-build-windows"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    cli_stage = stage_dir / "mmo.exe"
    gui_stage = stage_dir / "mmo-gui.exe"
    _copy_executable(cli_binary, cli_stage)
    _copy_executable(gui_binary, gui_stage)
    _sign_windows_executable(
        cli_stage, signing_enabled=signing_enabled, strict_signing=strict_signing
    )
    _sign_windows_executable(
        gui_stage, signing_enabled=signing_enabled, strict_signing=strict_signing
    )

    iscc = shutil.which("iscc")
    if iscc is None:
        raise InstallerBuildError(
            "Inno Setup compiler (iscc) is required to build the Windows installer."
        )

    output_base_name = f"mmo-setup-windows-{arch_tag}-v{version}"
    installer_script = stage_dir / "installer.iss"
    installer_script.write_text(
        "\n".join(
            [
                "[Setup]",
                "AppId={{9A0A8430-5D9D-45D7-BB70-60A713293961}",
                "AppName=Mix Marriage Offline",
                f"AppVersion={version}",
                "AppPublisher=Mix Marriage Offline",
                "DefaultDirName={autopf}\\Mix Marriage Offline",
                "DefaultGroupName=Mix Marriage Offline",
                "DisableProgramGroupPage=yes",
                f"OutputDir={output_dir}",
                f"OutputBaseFilename={output_base_name}",
                "Compression=lzma",
                "SolidCompression=yes",
                "ArchitecturesAllowed=x64compatible",
                "ArchitecturesInstallIn64BitMode=x64compatible",
                "WizardStyle=modern",
                "UninstallDisplayIcon={app}\\mmo-gui.exe",
                "",
                "[Tasks]",
                'Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"',
                "",
                "[Files]",
                f'Source: "{cli_stage}"; DestDir: "{{app}}"; Flags: ignoreversion',
                f'Source: "{gui_stage}"; DestDir: "{{app}}"; Flags: ignoreversion',
                "",
                "[Icons]",
                'Name: "{group}\\Mix Marriage Offline"; Filename: "{app}\\mmo-gui.exe"',
                'Name: "{group}\\MMO CLI"; Filename: "{app}\\mmo.exe"',
                'Name: "{autodesktop}\\Mix Marriage Offline"; Filename: "{app}\\mmo-gui.exe"; Tasks: desktopicon',
                "",
            ]
        ),
        encoding="utf-8",
    )

    _run_command([iscc, str(installer_script)], cwd=stage_dir, label="iscc")

    installer_path = output_dir / f"{output_base_name}.exe"
    if not installer_path.exists():
        raise InstallerBuildError(f"Expected Inno Setup output missing: {installer_path}")

    _sign_windows_executable(
        installer_path, signing_enabled=signing_enabled, strict_signing=strict_signing
    )
    checksum_path = _write_sha256(installer_path)
    return [installer_path, checksum_path]


def _build_macos_app_bundle(
    *,
    input_dir: Path,
    output_dir: Path,
    version: str,
    arch_tag: str,
    cli_name: str,
    gui_name: str,
    signing_enabled: bool,
    strict_signing: bool,
) -> list[Path]:
    cli_binary = _resolve_binary(
        input_dir=input_dir,
        artifact_name=cli_name,
        platform_tag="macos",
        arch_tag=arch_tag,
    )
    gui_binary = _resolve_binary(
        input_dir=input_dir,
        artifact_name=gui_name,
        platform_tag="macos",
        arch_tag=arch_tag,
    )

    app_name = f"MMO-v{version}-macos-{arch_tag}.app"
    app_path = output_dir / app_name
    if app_path.exists():
        shutil.rmtree(app_path)

    contents = app_path / "Contents"
    macos_dir = contents / "MacOS"
    resources_dir = contents / "Resources"
    bin_dir = resources_dir / "bin"
    macos_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)

    gui_target = macos_dir / "mmo-gui"
    cli_target = bin_dir / "mmo"
    launcher_target = macos_dir / "MMO"

    _copy_executable(gui_binary, gui_target)
    _copy_executable(cli_binary, cli_target)
    launcher_target.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
                'exec "$HERE/mmo-gui" "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    launcher_target.chmod(launcher_target.stat().st_mode | 0o111)

    info_plist = contents / "Info.plist"
    info_plist.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
                '<plist version="1.0">',
                "<dict>",
                "  <key>CFBundleName</key>",
                "  <string>Mix Marriage Offline</string>",
                "  <key>CFBundleDisplayName</key>",
                "  <string>Mix Marriage Offline</string>",
                "  <key>CFBundleIdentifier</key>",
                "  <string>io.mixmarriageoffline.mmo</string>",
                "  <key>CFBundleVersion</key>",
                f"  <string>{version}</string>",
                "  <key>CFBundleShortVersionString</key>",
                f"  <string>{version}</string>",
                "  <key>CFBundlePackageType</key>",
                "  <string>APPL</string>",
                "  <key>CFBundleExecutable</key>",
                "  <string>MMO</string>",
                "  <key>LSMinimumSystemVersion</key>",
                "  <string>12.0</string>",
                "  <key>NSHighResolutionCapable</key>",
                "  <true/>",
                "</dict>",
                "</plist>",
                "",
            ]
        ),
        encoding="utf-8",
    )

    _sign_macos_app(
        app_path, signing_enabled=signing_enabled, strict_signing=strict_signing
    )

    archive_path = output_dir / f"{app_name}.zip"
    if archive_path.exists():
        archive_path.unlink()
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app_path.rglob("*")):
            archive.write(path, arcname=str(Path(app_name) / path.relative_to(app_path)))

    zip_checksum = _write_sha256(archive_path)
    return [app_path, archive_path, zip_checksum]


def _build_linux_appimage(
    *,
    input_dir: Path,
    output_dir: Path,
    version: str,
    arch_tag: str,
    cli_name: str,
    gui_name: str,
    signing_enabled: bool,
    strict_signing: bool,
) -> list[Path]:
    cli_binary = _resolve_binary(
        input_dir=input_dir,
        artifact_name=cli_name,
        platform_tag="linux",
        arch_tag=arch_tag,
    )
    gui_binary = _resolve_binary(
        input_dir=input_dir,
        artifact_name=gui_name,
        platform_tag="linux",
        arch_tag=arch_tag,
    )

    app_dir = output_dir / f"MMO-v{version}-linux-{arch_tag}.AppDir"
    if app_dir.exists():
        shutil.rmtree(app_dir)

    usr_bin_dir = app_dir / "usr" / "bin"
    desktop_dir = app_dir / "usr" / "share" / "applications"
    icon_dir = app_dir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    usr_bin_dir.mkdir(parents=True, exist_ok=True)
    desktop_dir.mkdir(parents=True, exist_ok=True)
    icon_dir.mkdir(parents=True, exist_ok=True)

    cli_target = usr_bin_dir / "mmo"
    gui_target = usr_bin_dir / "mmo-gui"
    _copy_executable(cli_binary, cli_target)
    _copy_executable(gui_binary, gui_target)

    app_run = app_dir / "AppRun"
    app_run.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
                'exec "$HERE/usr/bin/mmo-gui" "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    app_run.chmod(app_run.stat().st_mode | 0o111)

    desktop_payload = "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=Mix Marriage Offline",
            "Comment=Offline deterministic stem-folder mixing assistant",
            "Exec=mmo-gui %F",
            "Icon=mmo",
            "Categories=AudioVideo;Audio;Music;",
            "Terminal=false",
            "",
        ]
    )
    (app_dir / "mmo.desktop").write_text(desktop_payload, encoding="utf-8")
    (desktop_dir / "mmo.desktop").write_text(desktop_payload, encoding="utf-8")

    icon_bytes = base64.b64decode(_APP_ICON_BASE64)
    (app_dir / "mmo.png").write_bytes(icon_bytes)
    (icon_dir / "mmo.png").write_bytes(icon_bytes)

    appimage_tool_raw = os.getenv("APPIMAGETOOL", "").strip()
    appimage_tool = Path(appimage_tool_raw) if appimage_tool_raw else None
    if appimage_tool is None:
        resolved = shutil.which("appimagetool")
        appimage_tool = Path(resolved) if resolved else None
    if appimage_tool is None:
        raise InstallerBuildError(
            "appimagetool was not found. Install it or set APPIMAGETOOL."
        )

    output_appimage = output_dir / f"mmo-v{version}-linux-{arch_tag}.AppImage"
    if output_appimage.exists():
        output_appimage.unlink()

    command = [str(appimage_tool), str(app_dir), str(output_appimage)]
    env = os.environ.copy()
    if appimage_tool.suffix == ".AppImage":
        env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")
    _run_command(command, cwd=output_dir, label="appimagetool", env=env)

    if not output_appimage.exists():
        raise InstallerBuildError(f"Expected AppImage output missing: {output_appimage}")

    output_appimage.chmod(output_appimage.stat().st_mode | 0o111)
    signature_path = _sign_linux_appimage(
        output_appimage, signing_enabled=signing_enabled, strict_signing=strict_signing
    )

    artifacts: list[Path] = [output_appimage, _write_sha256(output_appimage)]
    if signature_path is not None:
        artifacts.append(signature_path)
        artifacts.append(_write_sha256(signature_path))
    return artifacts


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build one-click MMO installers from prebuilt binaries."
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root (defaults to this script's parent).",
    )
    parser.add_argument(
        "--input-dir",
        default="dist",
        help="Directory containing binary artifacts from tools/build_binaries.py.",
    )
    parser.add_argument(
        "--output-dir",
        default="dist/installers",
        help="Directory where installer artifacts are written.",
    )
    parser.add_argument(
        "--version",
        default="",
        help="Release version (v-prefix is accepted). Defaults to src/mmo/__init__.py.",
    )
    parser.add_argument(
        "--name",
        default="mmo",
        help="Base CLI artifact name from tools/build_binaries.py.",
    )
    parser.add_argument(
        "--gui-name",
        default="mmo-gui",
        help="Base GUI artifact name from tools/build_binaries.py.",
    )
    parser.add_argument(
        "--platform",
        choices=("auto", "windows", "macos", "linux"),
        default="auto",
        help="Target installer platform (auto = current runtime platform).",
    )
    parser.add_argument(
        "--no-sign",
        action="store_true",
        help="Skip signing steps even if signing credentials are configured.",
    )
    parser.add_argument(
        "--strict-signing",
        action="store_true",
        help="Fail when signing is configured but required tools are unavailable.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.repo_root).resolve()

    input_dir = Path(args.input_dir)
    if not input_dir.is_absolute():
        input_dir = (repo_root / input_dir).resolve()
    if not input_dir.exists():
        print(f"error: input dir does not exist: {input_dir}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (repo_root / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    version_source = args.version.strip() or _detect_repo_version(repo_root)
    version = _normalize_version(version_source)
    platform_tag = _platform_tag() if args.platform == "auto" else args.platform
    arch_tag = _arch_tag()
    signing_enabled = not args.no_sign

    print(f"Preparing installers for version {version} on {platform_tag}/{arch_tag}.")

    try:
        if platform_tag == "windows":
            artifacts = _build_windows_installer(
                input_dir=input_dir,
                output_dir=output_dir,
                version=version,
                arch_tag=arch_tag,
                cli_name=args.name,
                gui_name=args.gui_name,
                signing_enabled=signing_enabled,
                strict_signing=bool(args.strict_signing),
            )
        elif platform_tag == "macos":
            artifacts = _build_macos_app_bundle(
                input_dir=input_dir,
                output_dir=output_dir,
                version=version,
                arch_tag=arch_tag,
                cli_name=args.name,
                gui_name=args.gui_name,
                signing_enabled=signing_enabled,
                strict_signing=bool(args.strict_signing),
            )
        elif platform_tag == "linux":
            artifacts = _build_linux_appimage(
                input_dir=input_dir,
                output_dir=output_dir,
                version=version,
                arch_tag=arch_tag,
                cli_name=args.name,
                gui_name=args.gui_name,
                signing_enabled=signing_enabled,
                strict_signing=bool(args.strict_signing),
            )
        else:
            print(f"error: unsupported platform: {platform_tag}", file=sys.stderr)
            return 2
    except InstallerBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for artifact in artifacts:
        print(f"Created: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
