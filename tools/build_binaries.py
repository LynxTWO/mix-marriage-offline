"""Build cross-platform MMO binaries with PyInstaller and Nuitka fallback."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
DEFAULT_ENTRYPOINT = SRC_DIR / "mmo" / "__main__.py"


class BuildError(RuntimeError):
    """Raised when one build backend fails."""


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


def _binary_suffix() -> str:
    return ".exe" if sys.platform.startswith("win") else ""


def _run_command(command: list[str], *, cwd: Path, label: str) -> None:
    printable = " ".join(shlex.quote(part) for part in command)
    print(f"[{label}] {printable}")
    completed = subprocess.run(command, cwd=cwd)
    if completed.returncode != 0:
        raise BuildError(f"{label} failed with exit code {completed.returncode}")


def _resolve_built_binary(
    *,
    output_dir: Path,
    binary_stem: str,
    binary_name: str,
    backend_label: str,
) -> Path:
    direct = output_dir / binary_name
    if direct.exists():
        return direct

    fallback_names = [binary_stem + _binary_suffix(), binary_stem]
    for name in fallback_names:
        candidate = output_dir / name
        if candidate.exists():
            return candidate

    candidates = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name.startswith(binary_stem)
    )
    if not candidates:
        raise BuildError(
            f"{backend_label} completed but no binary matching '{binary_stem}' was produced."
        )
    if _binary_suffix():
        for candidate in candidates:
            if candidate.suffix.lower() == ".exe":
                return candidate
    return candidates[0]


def _build_with_pyinstaller(
    *,
    repo_root: Path,
    src_dir: Path,
    entrypoint: Path,
    build_dir: Path,
    binary_stem: str,
    binary_name: str,
) -> Path:
    if importlib.util.find_spec("PyInstaller") is None:
        raise BuildError("PyInstaller is not installed.")

    dist_dir = build_dir / "pyinstaller_dist"
    work_dir = build_dir / "pyinstaller_work"
    spec_dir = build_dir / "pyinstaller_spec"
    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        binary_stem,
        "--paths",
        str(src_dir),
        "--collect-data",
        "mmo.data",
        "--collect-submodules",
        "mmo.cli_commands",
        "--collect-submodules",
        "mmo.plugins",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        str(entrypoint),
    ]
    _run_command(command, cwd=repo_root, label="pyinstaller")
    return _resolve_built_binary(
        output_dir=dist_dir,
        binary_stem=binary_stem,
        binary_name=binary_name,
        backend_label="PyInstaller",
    )


def _build_with_nuitka(
    *,
    repo_root: Path,
    src_dir: Path,
    entrypoint: Path,
    build_dir: Path,
    binary_stem: str,
    binary_name: str,
) -> Path:
    if importlib.util.find_spec("nuitka") is None:
        raise BuildError("Nuitka is not installed.")

    output_dir = build_dir / "nuitka_dist"
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = src_dir / "mmo" / "data"
    include_data_dir = f"{data_dir}=mmo/data"
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--onefile",
        "--remove-output",
        "--assume-yes-for-downloads",
        "--include-package=mmo",
        f"--output-dir={output_dir}",
        f"--output-filename={binary_name}",
        f"--include-data-dir={include_data_dir}",
        str(entrypoint),
    ]
    _run_command(command, cwd=repo_root, label="nuitka")
    return _resolve_built_binary(
        output_dir=output_dir,
        binary_stem=binary_stem,
        binary_name=binary_name,
        backend_label="Nuitka",
    )


def _archive_binary(*, binary_path: Path, output_dir: Path, binary_stem: str) -> Path:
    if sys.platform.startswith("win"):
        archive_path = output_dir / f"{binary_stem}.zip"
        with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(binary_path, arcname=binary_path.name)
        return archive_path

    archive_path = output_dir / f"{binary_stem}.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        archive.add(binary_path, arcname=binary_path.name)
    return archive_path


def _write_sha256(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum_path = Path(f"{path}.sha256")
    checksum_path.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return checksum_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build MMO CLI binaries with PyInstaller and Nuitka fallback."
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root (defaults to this script's parent).",
    )
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Directory where release artifacts are written.",
    )
    parser.add_argument(
        "--entrypoint",
        default="src/mmo/__main__.py",
        help="CLI entrypoint file to compile.",
    )
    parser.add_argument(
        "--name",
        default="mmo",
        help="Base artifact name (platform and arch tags are appended).",
    )
    parser.add_argument(
        "--prefer",
        choices=("pyinstaller", "nuitka"),
        default="pyinstaller",
        help="Preferred backend; the other backend is used as fallback.",
    )
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip .zip/.tar.gz packaging and only emit the raw binary.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(args.repo_root).resolve()
    src_dir = (repo_root / "src").resolve()

    entrypoint = Path(args.entrypoint)
    if not entrypoint.is_absolute():
        entrypoint = (repo_root / entrypoint).resolve()
    if not entrypoint.exists():
        print(f"error: entrypoint does not exist: {entrypoint}", file=sys.stderr)
        return 2
    if not src_dir.exists():
        print(f"error: src dir does not exist: {src_dir}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (repo_root / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    build_dir = output_dir / ".binary-build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    binary_stem = f"{args.name}-{_platform_tag()}-{_arch_tag()}"
    binary_name = f"{binary_stem}{_binary_suffix()}"
    backend_order = ["pyinstaller", "nuitka"]
    if args.prefer == "nuitka":
        backend_order.reverse()

    failures: list[str] = []
    built_binary: Path | None = None
    selected_backend: str | None = None
    for backend in backend_order:
        try:
            if backend == "pyinstaller":
                built_binary = _build_with_pyinstaller(
                    repo_root=repo_root,
                    src_dir=src_dir,
                    entrypoint=entrypoint,
                    build_dir=build_dir,
                    binary_stem=binary_stem,
                    binary_name=binary_name,
                )
            else:
                built_binary = _build_with_nuitka(
                    repo_root=repo_root,
                    src_dir=src_dir,
                    entrypoint=entrypoint,
                    build_dir=build_dir,
                    binary_stem=binary_stem,
                    binary_name=binary_name,
                )
            selected_backend = backend
            break
        except BuildError as exc:
            message = f"{backend}: {exc}"
            failures.append(message)
            print(f"warning: {message}", file=sys.stderr)

    if built_binary is None or selected_backend is None:
        print("error: all binary build backends failed.", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    final_binary = output_dir / binary_name
    shutil.copy2(built_binary, final_binary)
    if not sys.platform.startswith("win"):
        final_binary.chmod(final_binary.stat().st_mode | 0o111)
    binary_checksum = _write_sha256(final_binary)
    print(f"Built binary ({selected_backend}): {final_binary}")
    print(f"SHA256: {binary_checksum}")

    if args.no_archive:
        return 0

    archive = _archive_binary(
        binary_path=final_binary,
        output_dir=output_dir,
        binary_stem=binary_stem,
    )
    archive_checksum = _write_sha256(archive)
    print(f"Built archive: {archive}")
    print(f"SHA256: {archive_checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
