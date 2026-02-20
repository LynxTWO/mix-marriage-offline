import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import pytest


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


def _to_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class _WritableTemporaryDirectory:
    """Fallback TemporaryDirectory for Windows sandboxes with mode=0o700 ACL issues."""

    def __init__(
        self,
        suffix: str | None = None,
        prefix: str | None = None,
        dir: str | None = None,
        ignore_cleanup_errors: bool = False,
        delete: bool = True,
    ) -> None:
        self._suffix = "" if suffix is None else suffix
        self._prefix = "tmp" if prefix is None else prefix
        self._dir = tempfile.gettempdir() if dir is None else dir
        self._ignore_cleanup_errors = ignore_cleanup_errors
        self._delete = delete
        self.name: str | None = None

    def _create(self) -> str:
        base = Path(self._dir)
        base.mkdir(parents=True, exist_ok=True)
        while True:
            candidate = base / f"{self._prefix}{uuid.uuid4().hex}{self._suffix}"
            try:
                os.mkdir(os.fspath(candidate))
                return os.fspath(candidate)
            except FileExistsError:
                continue

    def __enter__(self) -> str:
        if self.name is None:
            self.name = self._create()
        return self.name

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        if not self._delete or self.name is None:
            return
        shutil.rmtree(self.name, ignore_errors=self._ignore_cleanup_errors)
        self.name = None

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        try:
            self.cleanup()
        except Exception:
            pass


def _temporary_directory_is_writable() -> bool:
    try:
        with tempfile.TemporaryDirectory() as path:
            probe_path = Path(path) / ".mmo_probe"
            probe_path.write_text("ok", encoding="utf-8")
        return True
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def _enforce_selected_temp_dir() -> None:
    from mmo.resources import temp_dir

    temp_root = temp_dir()
    temp_root_text = os.fspath(temp_root)

    original_env = {name: os.environ.get(name) for name in ("TMPDIR", "TMP", "TEMP")}
    original_tempdir = tempfile.tempdir
    original_tempdir_class = tempfile.TemporaryDirectory
    try:
        os.environ["TMPDIR"] = temp_root_text
        os.environ["TMP"] = temp_root_text
        os.environ["TEMP"] = temp_root_text
        tempfile.tempdir = temp_root_text

        active_temp = Path(tempfile.gettempdir()).resolve()
        resolved_root = temp_root.resolve()
        assert _is_within(active_temp, resolved_root), (
            "tempfile.gettempdir() must be inside selected temp root: "
            f"tempfile={_to_posix(active_temp)} root={_to_posix(resolved_root)}"
        )
        if os.name == "nt" and not _temporary_directory_is_writable():
            tempfile.TemporaryDirectory = _WritableTemporaryDirectory
            assert _temporary_directory_is_writable(), (
                "TemporaryDirectory fallback failed under selected temp root: "
                f"{_to_posix(resolved_root)}"
            )
        yield
    finally:
        tempfile.TemporaryDirectory = original_tempdir_class
        tempfile.tempdir = original_tempdir
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
