from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from mmo.core.bus_plan import build_bus_plan
from mmo.core.roles import load_roles
from mmo.core.scene_builder import build_scene_from_bus_plan
from mmo.core.session import build_session_from_stems_dir
from mmo.core.stem_identity import canonical_stem_ids_for_rel_paths
from mmo.core.stems_classifier import classify_stems
from mmo.core.stems_index import build_stems_index


def _write_tiny_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x01" * 16)


class TestStemIdentity(unittest.TestCase):
    def test_duplicate_basenames_are_unique_and_deterministic(self) -> None:
        rel_paths = [
            "album_a/Kick.wav",
            "album_b/Kick.wav",
            "album_b/Snare.wav",
        ]

        first = canonical_stem_ids_for_rel_paths(rel_paths)
        second = canonical_stem_ids_for_rel_paths(rel_paths)

        self.assertEqual(first, second)
        self.assertEqual(first["album_a/Kick.wav"], "album_a_kick")
        self.assertEqual(first["album_b/Kick.wav"], "album_b_kick")
        self.assertEqual(first["album_b/Snare.wav"], "snare")
        self.assertEqual(len(set(first.values())), len(rel_paths))

    def test_same_file_keeps_same_stem_id_across_pipeline(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        roles = load_roles(repo_root / "ontology" / "roles.yaml")

        with tempfile.TemporaryDirectory() as temp_dir:
            stems_root = Path(temp_dir) / "stems"
            _write_tiny_wav(stems_root / "drums" / "Kick.wav")
            _write_tiny_wav(stems_root / "vocals" / "LeadVox.wav")
            _write_tiny_wav(stems_root / "fx" / "HallVerbReturn.wav")

            stems_index = build_stems_index(stems_root, root_dir="fixtures/stems_identity")
            stems_map = classify_stems(
                stems_index,
                roles,
                stems_index_ref="fixtures/stems_identity/stems_index.json",
                roles_ref="ontology/roles.yaml",
            )
            bus_plan = build_bus_plan(stems_map, roles)
            scene = build_scene_from_bus_plan(
                stems_map,
                bus_plan,
                profile_id="PROFILE.ASSIST",
                stems_map_ref="fixtures/stems_identity/stems_map.json",
                bus_plan_ref="fixtures/stems_identity/bus_plan.json",
            )
            session = build_session_from_stems_dir(stems_root)

            by_rel_path_index = {
                row["rel_path"]: row["stem_id"]
                for row in stems_index.get("files", [])
                if isinstance(row, dict)
                and isinstance(row.get("rel_path"), str)
                and isinstance(row.get("stem_id"), str)
            }
            by_rel_path_map = {
                row["rel_path"]: row["stem_id"]
                for row in stems_map.get("assignments", [])
                if isinstance(row, dict)
                and isinstance(row.get("rel_path"), str)
                and isinstance(row.get("stem_id"), str)
            }
            by_rel_path_bus = {
                row["file_path"]: row["stem_id"]
                for row in bus_plan.get("assignments", [])
                if isinstance(row, dict)
                and isinstance(row.get("file_path"), str)
                and isinstance(row.get("stem_id"), str)
            }
            by_rel_path_session = {
                row["file_path"]: row["stem_id"]
                for row in session.get("stems", [])
                if isinstance(row, dict)
                and isinstance(row.get("file_path"), str)
                and isinstance(row.get("stem_id"), str)
            }

            by_stem_id_scene: set[str] = set()
            for row in scene.get("objects", []):
                if isinstance(row, dict) and isinstance(row.get("stem_id"), str):
                    by_stem_id_scene.add(row["stem_id"])
            for row in scene.get("beds", []):
                if not isinstance(row, dict):
                    continue
                for stem_id in row.get("stem_ids", []):
                    if isinstance(stem_id, str):
                        by_stem_id_scene.add(stem_id)

            expected = {
                "drums/Kick.wav": "kick",
                "fx/HallVerbReturn.wav": "hallverbreturn",
                "vocals/LeadVox.wav": "leadvox",
            }

            self.assertEqual(by_rel_path_index, expected)
            self.assertEqual(by_rel_path_map, expected)
            self.assertEqual(by_rel_path_bus, expected)
            self.assertEqual(by_rel_path_session, expected)
            self.assertEqual(by_stem_id_scene, set(expected.values()))
            self.assertTrue(all(not stem_id.startswith("STEMFILE.") for stem_id in by_stem_id_scene))


if __name__ == "__main__":
    unittest.main()
