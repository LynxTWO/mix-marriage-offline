import tempfile
import unittest
from pathlib import Path

import yaml

from mmo.core.roles import list_roles, load_roles, resolve_role


def _sorted_roles_mapping(raw_roles: dict[str, object]) -> dict[str, object]:
    ordered: dict[str, object] = {}
    meta = raw_roles.get("_meta")
    if isinstance(meta, dict):
        ordered["_meta"] = dict(meta)
    for role_id in sorted(raw_roles.keys()):
        if role_id == "_meta":
            continue
        ordered[role_id] = raw_roles[role_id]
    return ordered


class TestRolesRegistry(unittest.TestCase):
    def test_load_roles_success(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry_path = repo_root / "ontology" / "roles.yaml"

        first = load_roles(registry_path)
        second = load_roles(registry_path)
        self.assertEqual(first, second)

        roles = first.get("roles")
        self.assertIsInstance(roles, dict)
        if not isinstance(roles, dict):
            return

        role_ids = [
            role_id
            for role_id, entry in roles.items()
            if (
                isinstance(role_id, str)
                and role_id != "_meta"
                and isinstance(entry, dict)
            )
        ]
        self.assertEqual(role_ids, sorted(role_ids))
        self.assertIn("ROLE.BASS.AMP", role_ids)

    def test_resolve_role_unknown_error_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry_path = repo_root / "ontology" / "roles.yaml"
        unknown_role_id = "ROLE.UNKNOWN.TEST"

        known_ids = list_roles(registry_path)
        expected = (
            f"Unknown role_id: {unknown_role_id}. "
            f"Known role_ids: {', '.join(known_ids)}"
        )

        with self.assertRaises(ValueError) as first:
            resolve_role(unknown_role_id, registry_path)
        with self.assertRaises(ValueError) as second:
            resolve_role(unknown_role_id, registry_path)

        self.assertEqual(str(first.exception), str(second.exception))
        self.assertEqual(str(first.exception), expected)

    def test_load_roles_regex_compile_failure_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry_path = repo_root / "ontology" / "roles.yaml"
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))

        self.assertIsInstance(payload, dict)
        if not isinstance(payload, dict):
            return
        raw_roles = payload.get("roles")
        self.assertIsInstance(raw_roles, dict)
        if not isinstance(raw_roles, dict):
            return

        payload["roles"] = _sorted_roles_mapping(raw_roles)
        roles = payload["roles"]

        bass_amp = roles.get("ROLE.BASS.AMP")
        self.assertIsInstance(bass_amp, dict)
        if not isinstance(bass_amp, dict):
            return
        bass_amp_inference = bass_amp.get("inference")
        self.assertIsInstance(bass_amp_inference, dict)
        if not isinstance(bass_amp_inference, dict):
            return
        bass_amp_inference["regex"] = ["("]

        bass_di = roles.get("ROLE.BASS.DI")
        self.assertIsInstance(bass_di, dict)
        if not isinstance(bass_di, dict):
            return
        bass_di_inference = bass_di.get("inference")
        self.assertIsInstance(bass_di_inference, dict)
        if not isinstance(bass_di_inference, dict):
            return
        bass_di_inference["regex"] = ["["]

        expected = (
            "Roles registry inference regex patterns failed to compile: "
            "ROLE.BASS.AMP: (, ROLE.BASS.DI: ["
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            broken_registry_path = Path(temp_dir) / "roles.invalid.yaml"
            broken_registry_path.write_text(
                yaml.safe_dump(payload, sort_keys=False),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as first:
                load_roles(broken_registry_path)
            with self.assertRaises(ValueError) as second:
                load_roles(broken_registry_path)

        self.assertEqual(str(first.exception), str(second.exception))
        self.assertEqual(str(first.exception), expected)


if __name__ == "__main__":
    unittest.main()
