"""Build and stage the MMO CLI sidecar for the Tauri desktop app."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAURI_SRC = REPO_ROOT / "gui" / "desktop-tauri" / "src-tauri"
DEFAULT_BASE_NAME = "mmo"


def _binary_suffix(target_triple: str) -> str:
    return ".exe" if "windows" in target_triple.casefold() else ""


def _platform_tag_for_target(target_triple: str) -> str:
    normalized = target_triple.casefold()
    if "windows" in normalized:
        return "windows"
    if "darwin" in normalized or "apple" in normalized:
        return "macos"
    if "linux" in normalized:
        return "linux"
    raise ValueError(f"Unsupported target triple for MMO sidecar staging: {target_triple}")


def _arch_tag_for_target(target_triple: str) -> str:
    arch = target_triple.split("-", 1)[0].casefold().strip()
    mapping = {
        "amd64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
        "x64": "x86_64",
        "x86_64": "x86_64",
    }
    normalized = mapping.get(arch, arch)
    if not normalized:
        raise ValueError(f"Unsupported target triple for MMO sidecar staging: {target_triple}")
    return normalized


def sidecar_binary_name(*, target_triple: str, base_name: str = DEFAULT_BASE_NAME) -> str:
    # Tauri looks for the staged binary by target triple, not by the friendlier
    # release artifact name that build_binaries.py emits.
    return f"{base_name}-{target_triple}{_binary_suffix(target_triple)}"


def build_binary_name_for_target(
    *,
    target_triple: str,
    base_name: str = DEFAULT_BASE_NAME,
) -> str:
    return (
        f"{base_name}-{_platform_tag_for_target(target_triple)}-"
        f"{_arch_tag_for_target(target_triple)}{_binary_suffix(target_triple)}"
    )


def _rustc_host_target() -> str:
    explicit_target = os.environ.get("MMO_TAURI_TARGET_TRIPLE", "").strip()
    if explicit_target:
        # An explicit target wins over rustc host discovery because release and
        # CI packaging can stage sidecars for a target other than this machine.
        return explicit_target

    try:
        completed = subprocess.run(
            ["rustc", "-vV"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Rust is required to prepare the Tauri sidecar. Install `rustc` or "
            "set MMO_TAURI_TARGET_TRIPLE explicitly."
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError(
            "Failed to resolve the Rust host target via `rustc -vV`. "
            "Set MMO_TAURI_TARGET_TRIPLE explicitly if needed."
        )

    for line in completed.stdout.splitlines():
        prefix = "host:"
        if line.startswith(prefix):
            host = line[len(prefix) :].strip()
            if host:
                return host
            break
    raise RuntimeError("Could not determine the Rust host target from `rustc -vV`.")


def _iter_source_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    if not path.exists():
        return
    for candidate in sorted(path.rglob("*")):
        if candidate.is_file():
            yield candidate


def _latest_source_mtime(paths: Iterable[Path]) -> float:
    latest = 0.0
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        latest = max(latest, mtime)
    return latest


def is_sidecar_up_to_date(
    sidecar_path: Path,
    *,
    repo_root: Path,
) -> bool:
    if not sidecar_path.is_file():
        return False

    source_inputs = (
        repo_root / "pyproject.toml",
        repo_root / "src" / "mmo",
        repo_root / "tools" / "build_binaries.py",
        repo_root / "tools" / "prepare_tauri_sidecar.py",
    )
    # Watch only the inputs that can change the staged CLI payload. Frontend and
    # Rust edits should not force a sidecar rebuild by themselves.
    latest_input_mtime = _latest_source_mtime(
        source_file
        for source_input in source_inputs
        for source_file in _iter_source_files(source_input)
    )
    try:
        sidecar_mtime = sidecar_path.stat().st_mtime
    except OSError:
        return False
    return sidecar_mtime >= latest_input_mtime


def _ensure_executable(path: Path) -> None:
    if _binary_suffix(path.name):
        return
    # The copied Unix sidecar can lose its execute bit when staged on fresh
    # filesystems. Restore it here instead of relying on the temp build dir.
    current_mode = path.stat().st_mode
    path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def prepare_tauri_sidecar(
    *,
    repo_root: Path,
    tauri_src: Path,
    target_triple: str,
    python_executable: str,
    force: bool = False,
    base_name: str = DEFAULT_BASE_NAME,
) -> Path:
    binaries_dir = (tauri_src / "binaries").resolve()
    # Stage under src-tauri/binaries so dev, build, and packaged smoke all hit
    # the same sidecar location that tauri.conf.json bundles.
    binaries_dir.mkdir(parents=True, exist_ok=True)

    staged_sidecar_path = binaries_dir / sidecar_binary_name(
        target_triple=target_triple,
        base_name=base_name,
    )
    if not force and is_sidecar_up_to_date(staged_sidecar_path, repo_root=repo_root):
        return staged_sidecar_path

    with tempfile.TemporaryDirectory(
        dir=binaries_dir,
        prefix=".sidecar-build-",
    ) as temp_dir:
        # Build into a throwaway sibling dir first. A failed build should not
        # leave a half-written sidecar at the bundled path.
        build_output_dir = Path(temp_dir)
        command = [
            python_executable,
            str((repo_root / "tools" / "build_binaries.py").resolve()),
            "--repo-root",
            str(repo_root.resolve()),
            "--output-dir",
            str(build_output_dir),
            "--name",
            base_name,
            "--no-archive",
        ]
        completed = subprocess.run(
            command,
            cwd=repo_root,
            check=False,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError("Failed to build the MMO sidecar binary.")

        built_binary_path = build_output_dir / build_binary_name_for_target(
            target_triple=target_triple,
            base_name=base_name,
        )
        if not built_binary_path.is_file():
            raise RuntimeError(
                f"Built sidecar was not found at {built_binary_path.as_posix()}."
            )

        # Copy the release-shaped binary into the Tauri bundle name only after
        # the build completed and the expected output path exists.
        shutil.copy2(built_binary_path, staged_sidecar_path)
        _ensure_executable(staged_sidecar_path)
    return staged_sidecar_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and stage the MMO sidecar for gui/desktop-tauri.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root (defaults to this tool's parent).",
    )
    parser.add_argument(
        "--tauri-src",
        default=str(DEFAULT_TAURI_SRC),
        help="Path to the Tauri src-tauri directory.",
    )
    parser.add_argument(
        "--target-triple",
        default=None,
        help="Rust target triple for the sidecar filename (defaults to rustc host).",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable to use for tools/build_binaries.py.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild the sidecar even if the staged binary looks up to date.",
    )
    return parser.parse_args()


def main() -> int:
    try:
        args = _parse_args()
        repo_root = Path(args.repo_root).resolve()
        tauri_src = Path(args.tauri_src).resolve()
        target_triple = (
            args.target_triple.strip()
            if isinstance(args.target_triple, str) and args.target_triple.strip()
            else _rustc_host_target()
        )
        staged_path = prepare_tauri_sidecar(
            repo_root=repo_root,
            tauri_src=tauri_src,
            target_triple=target_triple,
            python_executable=args.python,
            force=bool(args.force),
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(staged_path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
