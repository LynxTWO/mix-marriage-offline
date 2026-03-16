from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_FROZEN_ENTRYPOINT = _REPO_ROOT / "src" / "mmo" / "_frozen_cli_entrypoint.py"


def _load_build_binaries_module():
    module_path = _REPO_ROOT / "tools" / "build_binaries.py"
    spec = importlib.util.spec_from_file_location("build_binaries", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load build_binaries.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFrozenCliEntrypoint(unittest.TestCase):
    def test_build_binaries_defaults_to_frozen_stub(self) -> None:
        module = _load_build_binaries_module()
        self.assertEqual(module.DEFAULT_ENTRYPOINT, _FROZEN_ENTRYPOINT)

    def test_frozen_entrypoint_uses_absolute_imports_only(self) -> None:
        tree = ast.parse(_FROZEN_ENTRYPOINT.read_text(encoding="utf-8"))
        import_from_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]

        self.assertTrue(import_from_nodes, "Frozen entrypoint should import mmo.cli.")
        self.assertTrue(
            all(node.level == 0 for node in import_from_nodes),
            "Frozen entrypoint must avoid package-relative imports.",
        )
        self.assertTrue(
            any(node.module == "mmo.cli" for node in import_from_nodes),
            "Frozen entrypoint must dispatch through mmo.cli.",
        )

    def test_frozen_entrypoint_answers_version_when_run_as_script(self) -> None:
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH", "")
        src_path = os.fspath(_REPO_ROOT / "src")
        env["PYTHONPATH"] = (
            src_path
            if not existing_pythonpath
            else os.pathsep.join((src_path, existing_pythonpath))
        )

        completed = subprocess.run(
            [sys.executable, os.fspath(_FROZEN_ENTRYPOINT), "--version"],
            cwd=_REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        self.assertRegex(completed.stdout.strip(), re.compile(r"\b\d+\.\d+\.\d+\b"))


if __name__ == "__main__":
    unittest.main()
