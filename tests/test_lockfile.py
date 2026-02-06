import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from mmo.cli import main
from mmo.core.lockfile import build_lockfile, verify_lockfile


def _schema_validator(schema_path: Path) -> jsonschema.Draft202012Validator:
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

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


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


class TestLockfile(unittest.TestCase):
    def test_build_lockfile_is_deterministic_and_schema_valid(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "lockfile.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            _write_bytes(stems_dir / "a.bin", b"\x00\x01\x02\x03")
            _write_bytes(stems_dir / "nested" / "b.bin", b"abc\x00xyz")
            _write_bytes(stems_dir / ".DS_Store", b"ignore")
            _write_bytes(stems_dir / ".git" / "config", b"ignore")

            first = build_lockfile(stems_dir)
            second = build_lockfile(stems_dir)
            self.assertEqual(first, second)

            validator.validate(first)
            self.assertEqual(first["root_dir"], stems_dir.resolve().as_posix())

            rel_paths = [item["rel_path"] for item in first["files"]]
            self.assertEqual(rel_paths, sorted(rel_paths))
            self.assertEqual(rel_paths, ["a.bin", "nested/b.bin"])

    def test_verify_lockfile_ok(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            _write_bytes(stems_dir / "a.bin", b"hello")
            _write_bytes(stems_dir / "nested" / "b.bin", b"world")
            lock = build_lockfile(stems_dir)

            result = verify_lockfile(stems_dir, lock)
            self.assertEqual(
                result,
                {
                    "ok": True,
                    "missing": [],
                    "extra": [],
                    "changed": [],
                },
            )

    def test_verify_lockfile_detects_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            _write_bytes(stems_dir / "a.bin", b"hello")
            _write_bytes(stems_dir / "nested" / "b.bin", b"world")
            lock = build_lockfile(stems_dir)

            _write_bytes(stems_dir / "nested" / "b.bin", b"WORLD!")
            result = verify_lockfile(stems_dir, lock)

            self.assertFalse(result["ok"])
            self.assertEqual(result["missing"], [])
            self.assertEqual(result["extra"], [])
            self.assertEqual(len(result["changed"]), 1)
            self.assertEqual(result["changed"][0]["rel"], "nested/b.bin")
            self.assertNotEqual(
                result["changed"][0]["expected_sha"],
                result["changed"][0]["actual_sha"],
            )

    def test_verify_lockfile_detects_extra(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            _write_bytes(stems_dir / "a.bin", b"hello")
            _write_bytes(stems_dir / "nested" / "b.bin", b"world")
            lock = build_lockfile(stems_dir)

            _write_bytes(stems_dir / "extra.bin", b"new")
            result = verify_lockfile(stems_dir, lock)

            self.assertFalse(result["ok"])
            self.assertEqual(result["missing"], [])
            self.assertEqual(result["extra"], ["extra.bin"])
            self.assertEqual(result["changed"], [])

    def test_verify_lockfile_detects_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            _write_bytes(stems_dir / "a.bin", b"hello")
            _write_bytes(stems_dir / "nested" / "b.bin", b"world")
            lock = build_lockfile(stems_dir)

            (stems_dir / "nested" / "b.bin").unlink()
            result = verify_lockfile(stems_dir, lock)

            self.assertFalse(result["ok"])
            self.assertEqual(result["missing"], ["nested/b.bin"])
            self.assertEqual(result["extra"], [])
            self.assertEqual(result["changed"], [])

    def test_cli_lock_verify_returns_non_zero_on_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            lock_path = temp_path / "lock.json"
            verify_path = temp_path / "verify.json"

            _write_bytes(stems_dir / "a.bin", b"hello")
            _write_bytes(stems_dir / "nested" / "b.bin", b"world")

            write_exit = main(
                [
                    "lock",
                    "write",
                    str(stems_dir),
                    "--out",
                    str(lock_path),
                ]
            )
            self.assertEqual(write_exit, 0)
            self.assertTrue(lock_path.exists())

            _write_bytes(stems_dir / "nested" / "b.bin", b"WORLD!")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                verify_exit = main(
                    [
                        "lock",
                        "verify",
                        str(stems_dir),
                        "--lock",
                        str(lock_path),
                        "--out",
                        str(verify_path),
                    ]
                )
            self.assertEqual(verify_exit, 1)
            self.assertIn("drift detected", stdout.getvalue().lower())

            verify_payload = json.loads(verify_path.read_text(encoding="utf-8"))
            self.assertFalse(verify_payload["ok"])
            self.assertEqual(verify_payload["missing"], [])
            self.assertEqual(verify_payload["extra"], [])
            self.assertEqual(len(verify_payload["changed"]), 1)
            self.assertEqual(
                verify_path.read_text(encoding="utf-8"),
                json.dumps(verify_payload, indent=2, sort_keys=True) + "\n",
            )

    def test_cli_lock_paths_inside_stems_are_excluded_from_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            stems_dir = temp_path / "stems"
            lock_path = stems_dir / "lock.json"
            verify_path = stems_dir / "verify.json"

            _write_bytes(stems_dir / "a.bin", b"hello")
            _write_bytes(stems_dir / "nested" / "b.bin", b"world")

            first_write_exit = main(
                [
                    "lock",
                    "write",
                    str(stems_dir),
                    "--out",
                    str(lock_path),
                ]
            )
            self.assertEqual(first_write_exit, 0)
            first_lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertNotIn("lock.json", [item["rel_path"] for item in first_lock_payload["files"]])

            second_write_exit = main(
                [
                    "lock",
                    "write",
                    str(stems_dir),
                    "--out",
                    str(lock_path),
                ]
            )
            self.assertEqual(second_write_exit, 0)
            second_lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(first_lock_payload, second_lock_payload)

            first_verify_exit = main(
                [
                    "lock",
                    "verify",
                    str(stems_dir),
                    "--lock",
                    str(lock_path),
                    "--out",
                    str(verify_path),
                ]
            )
            self.assertEqual(first_verify_exit, 0)

            second_verify_exit = main(
                [
                    "lock",
                    "verify",
                    str(stems_dir),
                    "--lock",
                    str(lock_path),
                    "--out",
                    str(verify_path),
                ]
            )
            self.assertEqual(second_verify_exit, 0)

            verify_payload = json.loads(verify_path.read_text(encoding="utf-8"))
            self.assertTrue(verify_payload["ok"])
            self.assertEqual(verify_payload["missing"], [])
            self.assertEqual(verify_payload["extra"], [])
            self.assertEqual(verify_payload["changed"], [])

    def test_lockfile_schema_rejects_backslash_rel_path(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "lockfile.schema.json")
        payload = {
            "schema_version": "0.1.0",
            "root_dir": "C:/tmp/stems",
            "files": [
                {
                    "rel_path": r"nested\b.bin",
                    "size_bytes": 1,
                    "sha256": "00" * 32,
                }
            ],
        }
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate(payload)


if __name__ == "__main__":
    unittest.main()
