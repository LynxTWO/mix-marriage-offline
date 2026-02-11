import os
import sys
from pathlib import Path
from typing import Optional


def _resolved_path(path_value: str) -> Optional[Path]:
    try:
        return Path(path_value).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _prefer_repo_src() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = (repo_root / "src").resolve()
    if not src_dir.is_dir():
        return

    existing_index = None
    for index, entry in enumerate(sys.path):
        if _resolved_path(entry) == src_dir:
            existing_index = index
            break

    if existing_index == 0:
        return

    if existing_index is not None:
        sys.path.pop(existing_index)

    sys.path.insert(0, str(src_dir))


def _repair_stdio_if_needed() -> None:
    if os.name != "nt":
        return

    for attr, fallback in (("stdout", "__stdout__"), ("stderr", "__stderr__")):
        stream = getattr(sys, attr, None)
        fallback_stream = getattr(sys, fallback, None)

        if stream is None or getattr(stream, "closed", False):
            if fallback_stream is not None and not getattr(fallback_stream, "closed", False):
                setattr(sys, attr, fallback_stream)
            continue

        try:
            stream.flush()
        except OSError:
            if fallback_stream is not None and not getattr(fallback_stream, "closed", False):
                setattr(sys, attr, fallback_stream)


def pytest_sessionstart(session) -> None:
    _repair_stdio_if_needed()


_prefer_repo_src()
