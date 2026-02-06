import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import jsonschema


class TestPresetPacks(unittest.TestCase):
    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _python_cmd(self) -> str:
        return os.fspath(os.getenv("PYTHON", "") or sys.executable)

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self._repo_root() / "src")
        return subprocess.run(
            [self._python_cmd(), "-m", "mmo", *args],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_index_schema_accepts_packs(self) -> None:
        repo_root = self._repo_root()
        index = json.loads((repo_root / "presets" / "index.json").read_text(encoding="utf-8"))
        schema = json.loads(
            (repo_root / "schemas" / "presets_index.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(schema).validate(index)

        packs = index.get("packs")
        self.assertIsInstance(packs, list)
        self.assertTrue(packs)

    def test_pack_preset_ids_exist(self) -> None:
        repo_root = self._repo_root()
        index = json.loads((repo_root / "presets" / "index.json").read_text(encoding="utf-8"))

        preset_ids = {
            item.get("preset_id")
            for item in index.get("presets", [])
            if isinstance(item, dict)
        }
        packs = index.get("packs", [])
        self.assertIsInstance(packs, list)
        for pack in packs:
            self.assertIsInstance(pack, dict)
            preset_ids_in_pack = pack.get("preset_ids", [])
            self.assertIsInstance(preset_ids_in_pack, list)
            for preset_id in preset_ids_in_pack:
                self.assertIn(preset_id, preset_ids)

    def test_cli_preset_pack_commands_are_deterministic(self) -> None:
        first_list = self._run_cli("presets", "packs", "list", "--format", "json")
        second_list = self._run_cli("presets", "packs", "list", "--format", "json")
        self.assertEqual(first_list.returncode, 0, msg=first_list.stderr)
        self.assertEqual(second_list.returncode, 0, msg=second_list.stderr)
        self.assertEqual(first_list.stdout, second_list.stdout)

        list_payload = json.loads(first_list.stdout)
        self.assertIsInstance(list_payload, list)
        self.assertEqual(
            [item.get("pack_id") for item in list_payload if isinstance(item, dict)],
            ["PACK.VIBE_STARTER"],
        )

        first_show = self._run_cli(
            "presets",
            "packs",
            "show",
            "PACK.VIBE_STARTER",
            "--format",
            "text",
        )
        second_show = self._run_cli(
            "presets",
            "packs",
            "show",
            "PACK.VIBE_STARTER",
            "--format",
            "text",
        )
        self.assertEqual(first_show.returncode, 0, msg=first_show.stderr)
        self.assertEqual(second_show.returncode, 0, msg=second_show.stderr)
        self.assertEqual(first_show.stdout, second_show.stdout)

        lines = [line for line in first_show.stdout.splitlines() if line.strip()]
        self.assertTrue(lines)
        self.assertEqual(lines[0], "PACK.VIBE_STARTER  Vibe starter")
        self.assertIn("PRESET.VIBE.WARM_INTIMATE  Warm intimate", lines)
        self.assertIn("PRESET.VIBE.BRIGHT_AIRY  Bright airy", lines)
        self.assertIn("PRESET.VIBE.PUNCHY_TIGHT  Punchy tight", lines)
        self.assertIn("PRESET.VIBE.WIDE_CINEMATIC  Wide cinematic", lines)
        self.assertIn("PRESET.VIBE.DENSE_GLUE  Dense glue", lines)
        self.assertIn("PRESET.VIBE.TRANSLATION_SAFE  Translation safe", lines)


if __name__ == "__main__":
    unittest.main()
