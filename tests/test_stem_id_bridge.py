from __future__ import annotations

import unittest

from mmo.core.stem_id_bridge import (
    report_stem_ids_by_relative_path,
    rewrite_scene_build_locks_stem_ids,
    rewrite_scene_stem_ids,
    scene_stem_id_aliases_from_stems_map,
)


class TestStemIdBridge(unittest.TestCase):
    def test_scene_stem_id_aliases_match_report_by_relative_path(self) -> None:
        report = {
            "session": {
                "stems_dir": "/tmp/workspace",
                "stems": [
                    {"stem_id": "kick", "file_path": "stems/Kick.wav"},
                    {"stem_id": "leadvox", "file_path": "stems/LeadVox.wav"},
                ],
            }
        }
        stems_map = {
            "assignments": [
                {"file_id": "STEMFILE.1111111111", "rel_path": "stems/Kick.wav"},
                {"file_id": "STEMFILE.2222222222", "rel_path": "stems/LeadVox.wav"},
            ]
        }

        self.assertEqual(
            report_stem_ids_by_relative_path(report),
            {
                "stems/kick.wav": "kick",
                "stems/leadvox.wav": "leadvox",
            },
        )
        self.assertEqual(
            scene_stem_id_aliases_from_stems_map(stems_map=stems_map, report=report),
            {
                "STEMFILE.1111111111": "kick",
                "STEMFILE.2222222222": "leadvox",
            },
        )

    def test_rewrite_scene_stem_ids_updates_objects_beds_and_stereo_hints(self) -> None:
        scene = {
            "objects": [
                {
                    "object_id": "OBJ.STEMFILE.1111111111",
                    "stem_id": "STEMFILE.1111111111",
                    "role_id": "ROLE.DRUM.KICK",
                    "group_bus": "BUS.DRUMS",
                }
            ],
            "beds": [
                {
                    "bed_id": "BED.MUSIC",
                    "bus_id": "BUS.MUSIC.SYNTH",
                    "stem_ids": ["STEMFILE.2222222222"],
                }
            ],
            "metadata": {
                "stereo_hints": [
                    {
                        "object_id": "OBJ.STEMFILE.1111111111",
                        "stem_id": "STEMFILE.1111111111",
                    }
                ]
            },
        }

        rewritten = rewrite_scene_stem_ids(
            scene,
            {
                "STEMFILE.1111111111": "kick",
                "STEMFILE.2222222222": "padwide",
            },
        )

        self.assertEqual(rewritten["objects"][0]["stem_id"], "kick")
        self.assertEqual(rewritten["objects"][0]["object_id"], "OBJ.kick")
        self.assertEqual(rewritten["beds"][0]["stem_ids"], ["padwide"])
        self.assertEqual(rewritten["metadata"]["stereo_hints"][0]["stem_id"], "kick")
        self.assertEqual(rewritten["metadata"]["stereo_hints"][0]["object_id"], "OBJ.kick")

    def test_rewrite_scene_build_locks_stem_ids_prefers_existing_new_key(self) -> None:
        locks = {
            "version": "0.1.0",
            "overrides": {
                "STEMFILE.1111111111": {"role_id": "ROLE.DRUM.KICK"},
                "kick": {"role_id": "ROLE.DRUM.KICK"},
            },
        }

        rewritten = rewrite_scene_build_locks_stem_ids(
            locks,
            {"STEMFILE.1111111111": "kick"},
        )

        self.assertEqual(list(rewritten["overrides"].keys()), ["kick"])


if __name__ == "__main__":
    unittest.main()
