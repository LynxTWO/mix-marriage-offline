"""Tests for the cross-platform resource resolver (mmo.resources)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock
from uuid import uuid4


@contextmanager
def _manual_temp_dir() -> Path:
    root = (Path(tempfile.gettempdir()).resolve() / "mmo_resources_tests").resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"tmp_{os.getpid()}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class TestDataRoot(unittest.TestCase):
    def test_data_root_returns_path_with_required_subdirs(self) -> None:
        from mmo.resources import data_root

        root = data_root()
        self.assertIsInstance(root, Path)
        for subdir in ("schemas", "ontology", "presets"):
            self.assertTrue(
                (root / subdir).is_dir(),
                f"Expected {root / subdir} to be a directory",
            )

    def test_schemas_dir_contains_anchor(self) -> None:
        from mmo.resources import schemas_dir

        d = schemas_dir()
        self.assertTrue(d.is_dir())
        self.assertTrue(
            (d / "report.schema.json").is_file(),
            "Expected report.schema.json in schemas_dir",
        )

    def test_ontology_dir_contains_anchor(self) -> None:
        from mmo.resources import ontology_dir

        d = ontology_dir()
        self.assertTrue(d.is_dir())
        self.assertTrue(
            (d / "roles.yaml").is_file(),
            "Expected roles.yaml in ontology_dir",
        )

    def test_presets_dir_contains_anchor(self) -> None:
        from mmo.resources import presets_dir

        d = presets_dir()
        self.assertTrue(d.is_dir())
        self.assertTrue(
            (d / "index.json").is_file(),
            "Expected index.json in presets_dir",
        )


class TestDataRootEnvOverride(unittest.TestCase):
    def test_mmo_data_root_override_valid(self) -> None:
        from mmo.resources import data_root

        with _manual_temp_dir() as tmp:
            for subdir in ("schemas", "ontology", "presets"):
                (tmp / subdir).mkdir()
            with mock.patch.dict(os.environ, {"MMO_DATA_ROOT": os.fspath(tmp)}):
                root = data_root()
            self.assertEqual(root, tmp.resolve())

    def test_mmo_data_root_override_invalid_raises(self) -> None:
        from mmo.resources import data_root

        with _manual_temp_dir() as tmp:
            # No required subdirs inside tmp.
            with mock.patch.dict(os.environ, {"MMO_DATA_ROOT": os.fspath(tmp)}):
                with self.assertRaises(RuntimeError):
                    data_root()


class TestDefaultCacheDir(unittest.TestCase):
    def test_default_cache_dir_is_absolute(self) -> None:
        from mmo.resources import default_cache_dir

        d = default_cache_dir()
        self.assertIsInstance(d, Path)
        self.assertTrue(d.is_absolute(), f"Expected absolute path, got {d}")

    def test_mmo_cache_dir_override(self) -> None:
        from mmo.resources import default_cache_dir

        with _manual_temp_dir() as tmp:
            with mock.patch.dict(os.environ, {"MMO_CACHE_DIR": os.fspath(tmp)}):
                d = default_cache_dir()
            self.assertEqual(d, tmp.resolve())


class TestDefaultTempDir(unittest.TestCase):
    def test_default_temp_dir_is_absolute_directory(self) -> None:
        from mmo.resources import default_temp_dir

        d = default_temp_dir()
        self.assertIsInstance(d, Path)
        self.assertTrue(d.is_absolute(), f"Expected absolute path, got {d}")
        self.assertTrue(d.is_dir(), f"Expected directory, got {d}")

    def test_mmo_temp_dir_override(self) -> None:
        from mmo.resources import default_temp_dir

        with _manual_temp_dir() as tmp:
            with mock.patch.dict(os.environ, {"MMO_TEMP_DIR": os.fspath(tmp)}):
                d = default_temp_dir()
            self.assertEqual(d, tmp.resolve())

    def test_default_temp_dir_uses_os_temp_when_repo_root_missing(self) -> None:
        from mmo import resources

        with _manual_temp_dir() as tmp:
            expected = (tmp.resolve() / "mmo_tmp" / str(os.getpid())).resolve()
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("MMO_TEMP_DIR", None)
                with mock.patch("mmo.resources._repo_checkout_root", return_value=None):
                    with mock.patch("tempfile.gettempdir", return_value=os.fspath(tmp)):
                        resolved = resources.default_temp_dir()
        self.assertEqual(resolved, expected)

    def test_default_temp_dir_repo_temp_unlink_failure_falls_back_to_os_temp(self) -> None:
        from mmo.resources import default_temp_dir

        repo_root = Path(__file__).resolve().parents[1]
        repo_temp = (repo_root / ".mmo_tmp" / "repo_unlink_failure").resolve()
        original_unlink = Path.unlink

        def failing_unlink(path_obj: Path, *args: object, **kwargs: object) -> None:
            if path_obj.name.startswith(".mmo_temp_probe_") and path_obj.parent.resolve() == repo_temp:
                raise OSError("unlink blocked")
            return original_unlink(path_obj, *args, **kwargs)

        with _manual_temp_dir() as tmp:
            expected = (tmp.resolve() / "mmo_tmp" / str(os.getpid())).resolve()
            with mock.patch.dict(os.environ, {"MMO_TEMP_DIR": os.fspath(repo_temp)}, clear=False):
                with mock.patch("tempfile.gettempdir", return_value=os.fspath(tmp)):
                    with mock.patch("pathlib.Path.unlink", new=failing_unlink):
                        resolved = default_temp_dir()
        self.assertEqual(resolved, expected)

    def test_default_temp_dir_unavailable_raises_stable_error(self) -> None:
        from mmo import resources

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MMO_TEMP_DIR", None)
            with mock.patch("mmo.resources._repo_checkout_root", return_value=None):
                with mock.patch(
                    "mmo.resources._ensure_real_directory",
                    side_effect=RuntimeError("MMO temporary directory is unavailable."),
                ):
                    with mock.patch("tempfile.gettempdir", return_value="."):
                        with self.assertRaises(RuntimeError) as raised:
                            resources.default_temp_dir()
        self.assertEqual(str(raised.exception), "MMO temporary directory is unavailable.")


if __name__ == "__main__":
    unittest.main()
