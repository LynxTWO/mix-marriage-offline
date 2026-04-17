from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional


def _command_for_path(path: Path) -> List[str]:
    # Repo tests and packaged tools can point at Python shims. Wrap them with
    # the active interpreter so explicit tool paths behave the same on every OS.
    if path.suffix.lower() == ".py":
        return [sys.executable, str(path)]
    return [str(path)]


def _resolve_explicit_tool(env_var: str) -> Optional[List[str]]:
    env_path = os.environ.get(env_var)
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return _command_for_path(candidate)
        # An explicit override is an authority claim. Fail closed here instead
        # of silently switching to a different binary from PATH.
        return None
    return []


def resolve_ffmpeg_cmd() -> Optional[List[str]]:
    explicit = _resolve_explicit_tool("MMO_FFMPEG_PATH")
    if explicit is None:
        return None
    if explicit:
        return explicit

    found = shutil.which("ffmpeg")
    if not found:
        return None
    return [found]


def resolve_ffprobe_cmd() -> Optional[List[str]]:
    explicit = _resolve_explicit_tool("MMO_FFPROBE_PATH")
    if explicit is None:
        return None
    if explicit:
        return explicit

    ffmpeg_env = os.environ.get("MMO_FFMPEG_PATH")
    if ffmpeg_env:
        ffmpeg_path = Path(ffmpeg_env)
        if not ffmpeg_path.exists():
            return None

        # Pair ffprobe with the explicit ffmpeg install before falling back to
        # PATH, or metadata can come from a different tool build.
        candidate_paths: list[Path] = []
        renamed = ffmpeg_path.name.replace("ffmpeg", "ffprobe", 1)
        if renamed != ffmpeg_path.name:
            candidate_paths.append(ffmpeg_path.with_name(renamed))
        if ffmpeg_path.suffix:
            candidate_paths.append(ffmpeg_path.with_name(f"ffprobe{ffmpeg_path.suffix}"))
        candidate_paths.append(ffmpeg_path.with_name("ffprobe"))

        seen: set[str] = set()
        for candidate in candidate_paths:
            key = candidate.as_posix()
            if key in seen:
                continue
            seen.add(key)
            if candidate.exists():
                return _command_for_path(candidate)
        return None

    found = shutil.which("ffprobe")
    if not found:
        return None
    return [found]
