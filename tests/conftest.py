import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Optional

import pytest


def _schema_store_from_registry(registry: object) -> dict[str, dict]:
    resources = getattr(registry, "_resources", None)
    if not isinstance(resources, Mapping):
        return {}

    store: dict[str, dict] = {}
    for uri, resource in resources.items():
        if not isinstance(uri, str):
            continue
        contents = getattr(resource, "contents", None)
        if not isinstance(contents, dict):
            continue
        store[uri] = contents
        schema_id = contents.get("$id")
        if isinstance(schema_id, str) and schema_id:
            store[schema_id] = contents
    return store


def _patch_jsonschema_registry_kwarg_compat() -> None:
    try:
        import jsonschema
    except ImportError:
        return

    validator_cls = getattr(jsonschema, "Draft202012Validator", None)
    if validator_cls is None:
        return
    try:
        validator_cls({})
    except Exception:
        return
    try:
        validator_cls({}, registry=None)
        return
    except TypeError:
        pass
    except Exception:
        return

    resolver_cls = getattr(jsonschema, "RefResolver", None)
    if resolver_cls is None:
        return

    class _CompatDraft202012Validator(validator_cls):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            registry = kwargs.pop("registry", None)
            schema = args[0] if args else kwargs.get("schema")
            if registry is not None and isinstance(schema, dict) and "resolver" not in kwargs:
                store = _schema_store_from_registry(registry)
                if store:
                    kwargs["resolver"] = resolver_cls.from_schema(schema, store=store)
            super().__init__(*args, **kwargs)

    _CompatDraft202012Validator.__name__ = validator_cls.__name__
    _CompatDraft202012Validator.__qualname__ = validator_cls.__qualname__
    jsonschema.Draft202012Validator = _CompatDraft202012Validator  # type: ignore[attr-defined]


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

    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    existing_entries = [entry for entry in existing_pythonpath.split(os.pathsep) if entry]
    filtered_entries: list[str] = []
    for entry in existing_entries:
        if _resolved_path(entry) == src_dir:
            continue
        filtered_entries.append(entry)
    filtered_entries.insert(0, str(src_dir))
    os.environ["PYTHONPATH"] = os.pathsep.join(filtered_entries)


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
_patch_jsonschema_registry_kwarg_compat()


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
