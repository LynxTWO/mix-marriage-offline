import contextlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.cli import main


def _write_tiny_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8)


def _schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    registry = Registry()
    for candidate in sorted(schema_path.parent.glob("*.schema.json")):
        schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(candidate.resolve().as_uri(), resource)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, resource)
    root_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(root_schema, registry=registry)


class TestCliStemsBusPlan(unittest.TestCase):
    def _run_main(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(args)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_bus_plan_from_stems_map(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "bus_plan.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_root = temp_path / "stems_root"
            stems_dir = stems_root / "stems"
            stems_map_path = temp_path / "stems_map.json"
            bus_plan_path = temp_path / "bus_plan.json"
            bus_plan_csv_path = temp_path / "bus_plan.csv"
            bus_plan_2_path = temp_path / "bus_plan_2.json"

            _write_tiny_wav(stems_dir / "Kick1.wav")
            _write_tiny_wav(stems_dir / "Snare1.wav")
            _write_tiny_wav(stems_dir / "Synth01.wav")
            _write_tiny_wav(stems_dir / "SFX1.wav")

            classify_exit, _, classify_stderr = self._run_main(
                [
                    "stems",
                    "classify",
                    "--root",
                    str(stems_root),
                    "--out",
                    str(stems_map_path),
                ]
            )
            self.assertEqual(classify_exit, 0, msg=classify_stderr)

            bus_exit, _, bus_stderr = self._run_main(
                [
                    "stems",
                    "bus-plan",
                    "--map",
                    str(stems_map_path),
                    "--out",
                    str(bus_plan_path),
                    "--csv",
                    str(bus_plan_csv_path),
                ]
            )
            self.assertEqual(bus_exit, 0, msg=bus_stderr)

            bus_plan_payload = json.loads(bus_plan_path.read_text(encoding="utf-8"))
            validator.validate(bus_plan_payload)

            assignments = bus_plan_payload.get("assignments")
            self.assertIsInstance(assignments, list)
            if not isinstance(assignments, list):
                return

            by_file_path = {
                item.get("file_path"): item
                for item in assignments
                if isinstance(item, dict) and isinstance(item.get("file_path"), str)
            }

            self.assertEqual(
                by_file_path["stems/Kick1.wav"]["bus_id"],
                "BUS.DRUMS.KICK",
            )
            self.assertEqual(
                by_file_path["stems/Snare1.wav"]["bus_id"],
                "BUS.DRUMS.SNARE",
            )
            self.assertEqual(
                by_file_path["stems/Synth01.wav"]["bus_id"],
                "BUS.MUSIC.SYNTH",
            )
            self.assertEqual(
                by_file_path["stems/SFX1.wav"]["bus_id"],
                "BUS.FX.SFX",
            )

            self.assertTrue(bus_plan_csv_path.exists())
            csv_text = bus_plan_csv_path.read_text(encoding="utf-8")
            self.assertIn("stem_id,file_path,role_id,confidence,bus_id,bus_path", csv_text)
            self.assertIn("stems/Kick1.wav", csv_text)

            bus_exit_2, _, bus_stderr_2 = self._run_main(
                [
                    "stems",
                    "bus-plan",
                    "--map",
                    str(stems_map_path),
                    "--out",
                    str(bus_plan_2_path),
                ]
            )
            self.assertEqual(bus_exit_2, 0, msg=bus_stderr_2)

            self.assertEqual(
                bus_plan_path.read_text(encoding="utf-8"),
                bus_plan_2_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
