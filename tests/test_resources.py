"""Tests for the cross-platform resource resolver (mmo.resources)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

        with tempfile.TemporaryDirectory() as tmp:
            for subdir in ("schemas", "ontology", "presets"):
                (Path(tmp) / subdir).mkdir()
            with mock.patch.dict(os.environ, {"MMO_DATA_ROOT": tmp}):
                root = data_root()
            self.assertEqual(root, Path(tmp).resolve())

    def test_mmo_data_root_override_invalid_raises(self) -> None:
        from mmo.resources import data_root

        with tempfile.TemporaryDirectory() as tmp:
            # No required subdirs inside tmp.
            with mock.patch.dict(os.environ, {"MMO_DATA_ROOT": tmp}):
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

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MMO_CACHE_DIR": tmp}):
                d = default_cache_dir()
            self.assertEqual(d, Path(tmp).resolve())


if __name__ == "__main__":
    unittest.main()
