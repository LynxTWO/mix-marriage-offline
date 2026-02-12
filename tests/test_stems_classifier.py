import json
import tempfile
import unittest
import wave
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.roles import load_roles
from mmo.core.stems_classifier import classify_stems
from mmo.core.stems_index import build_stems_index


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


class TestStemsClassifier(unittest.TestCase):
    def test_classify_stems_covers_common_patterns(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        roles_payload = load_roles(repo_root / "ontology" / "roles.yaml")
        validator = _schema_validator(repo_root / "schemas" / "stems_map.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "stems_root"
            _write_tiny_wav(root / "stems" / "kick.wav")
            _write_tiny_wav(root / "stems" / "snare top.wav")
            _write_tiny_wav(root / "stems" / "vox lead.wav")
            _write_tiny_wav(root / "stems" / "gtr L.wav")
            _write_tiny_wav(root / "stems" / "gtr R.wav")
            _write_tiny_wav(root / "stems" / "bass DI.wav")

            stems_index = build_stems_index(root, root_dir="demo_stems")
            stems_map = classify_stems(
                stems_index,
                roles_payload,
                stems_index_ref="demo/stems_index.json",
                roles_ref="ontology/roles.yaml",
            )
            validator.validate(stems_map)

            assignments = stems_map.get("assignments")
            self.assertIsInstance(assignments, list)
            if not isinstance(assignments, list):
                return
            by_rel_path = {
                item.get("rel_path"): item
                for item in assignments
                if isinstance(item, dict) and isinstance(item.get("rel_path"), str)
            }

            self.assertEqual(by_rel_path["stems/kick.wav"]["role_id"], "ROLE.DRUM.KICK")
            self.assertEqual(by_rel_path["stems/snare top.wav"]["role_id"], "ROLE.DRUM.SNARE")
            self.assertEqual(by_rel_path["stems/vox lead.wav"]["role_id"], "ROLE.VOCAL.LEAD")
            self.assertEqual(by_rel_path["stems/gtr L.wav"]["role_id"], "ROLE.GTR.ELECTRIC_L")
            self.assertEqual(by_rel_path["stems/gtr R.wav"]["role_id"], "ROLE.GTR.ELECTRIC_R")
            self.assertEqual(by_rel_path["stems/bass DI.wav"]["role_id"], "ROLE.BASS.DI")

            left_link = by_rel_path["stems/gtr L.wav"].get("link_group_id")
            right_link = by_rel_path["stems/gtr R.wav"].get("link_group_id")
            self.assertIsInstance(left_link, str)
            self.assertEqual(left_link, right_link)

    def test_folder_tokens_boost_role_matches(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        roles_payload = load_roles(repo_root / "ontology" / "roles.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "stems_root"
            _write_tiny_wav(root / "Drums" / "tone.wav")

            stems_index = build_stems_index(root)
            stems_map = classify_stems(stems_index, roles_payload)
            assignments = stems_map.get("assignments")
            self.assertIsInstance(assignments, list)
            if not isinstance(assignments, list) or not assignments:
                return

            assignment = assignments[0]
            self.assertEqual(assignment.get("role_id"), "ROLE.BUS.DRUMS")
            reasons = assignment.get("reasons")
            self.assertIsInstance(reasons, list)
            if not isinstance(reasons, list):
                return
            self.assertIn("folder_token=drums(+1)", reasons)

    def test_tie_breaks_are_deterministic(self) -> None:
        roles_payload = {
            "roles": {
                "ROLE.OTHER.UNKNOWN": {
                    "label": "Unknown",
                    "kind": "utility",
                    "inference": {"keywords": [], "regex": []},
                },
                "ROLE.TEST.AAA": {
                    "label": "AAA",
                    "kind": "source",
                    "inference": {"keywords": ["clash"], "regex": []},
                },
                "ROLE.TEST.BBB": {
                    "label": "BBB",
                    "kind": "source",
                    "inference": {"keywords": ["clash"], "regex": []},
                },
            }
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "stems_root"
            _write_tiny_wav(root / "stems" / "clash.wav")
            stems_index = build_stems_index(root)

            first = classify_stems(stems_index, roles_payload)
            second = classify_stems(stems_index, roles_payload)
            self.assertEqual(first, second)

            assignments = first.get("assignments")
            self.assertIsInstance(assignments, list)
            if not isinstance(assignments, list) or not assignments:
                return
            assignment = assignments[0]
            self.assertEqual(assignment.get("role_id"), "ROLE.TEST.AAA")
            reasons = assignment.get("reasons")
            self.assertIsInstance(reasons, list)
            if not isinstance(reasons, list):
                return
            self.assertIn("tie_break=lex", reasons)


if __name__ == "__main__":
    unittest.main()
