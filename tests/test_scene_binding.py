from __future__ import annotations

import unittest

from mmo.core.scene_binding import (
    SCENE_BINDING_MODE_BASENAME,
    SCENE_BINDING_MODE_FILE_PATH,
    SCENE_BINDING_MODE_SOURCE_REF,
    SCENE_BINDING_WARNING_AMBIGUOUS_BASENAME,
    bind_scene_inputs_to_session,
)


def _session_payload() -> dict:
    return {
        "stems_dir": "/workspace/stems",
        "workspace_dir": "/workspace",
        "stems": [
            {
                "stem_id": "kick",
                "file_path": "stems/drums/Kick.wav",
                "workspace_relative_path": "imports/drums/Kick.wav",
                "source_ref": "imports/drums/Kick.wav",
            },
            {
                "stem_id": "snare",
                "file_path": "stems/drums/Snare.wav",
                "workspace_relative_path": "imports/drums/Snare.wav",
                "source_ref": "imports/drums/Snare.wav",
            },
            {
                "stem_id": "pad",
                "file_path": "stems/music/Pad.wav",
                "workspace_relative_path": "imports/music/Pad.wav",
                "source_ref": "imports/music/Pad.wav",
            },
        ],
    }


class TestSceneBinding(unittest.TestCase):
    def test_exact_stem_id_binding_is_clean(self) -> None:
        scene_payload = {
            "objects": [{"object_id": "OBJ.kick", "stem_id": "kick"}],
            "beds": [{"bed_id": "BED.FIELD.001", "stem_ids": ["pad"]}],
        }

        bound_scene, bound_locks, summary = bind_scene_inputs_to_session(
            scene_payload=scene_payload,
            session_payload=_session_payload(),
            locks_payload=None,
        )

        self.assertEqual(bound_scene, scene_payload)
        self.assertIsNone(bound_locks)
        self.assertEqual(summary["status"], "clean")
        self.assertEqual(summary["bound_count"], 2)
        self.assertEqual(summary["unbound_count"], 0)
        self.assertEqual(summary["rewritten_count"], 0)

    def test_old_path_based_refs_rewrite_to_canonical_ids(self) -> None:
        scene_payload = {
            "objects": [{"object_id": "OBJ.old.kick", "stem_id": "imports/drums/Kick.wav"}],
            "beds": [{"bed_id": "BED.MUSIC", "stem_ids": ["stems/music/Pad.wav"]}],
        }
        locks_payload = {
            "version": "0.1.0",
            "overrides": {
                "imports/drums/Kick.wav": {"role_id": "ROLE.DRUM.KICK"},
            },
        }

        bound_scene, bound_locks, summary = bind_scene_inputs_to_session(
            scene_payload=scene_payload,
            session_payload=_session_payload(),
            locks_payload=locks_payload,
        )

        self.assertEqual(bound_scene["objects"][0]["stem_id"], "kick")
        self.assertEqual(bound_scene["beds"][0]["stem_ids"], ["pad"])
        self.assertEqual(sorted(bound_locks["overrides"].keys()), ["kick"])
        self.assertEqual(summary["status"], "rewritten")
        self.assertEqual(summary["bound_count"], 3)
        self.assertEqual(summary["rewritten_count"], 3)
        self.assertEqual(summary["unbound_count"], 0)
        self.assertEqual(
            {row["binding_mode"] for row in summary["rewritten_refs"]},
            {SCENE_BINDING_MODE_SOURCE_REF, SCENE_BINDING_MODE_FILE_PATH},
        )

    def test_unique_basename_fallback_binds_only_when_unique(self) -> None:
        scene_payload = {
            "objects": [{"object_id": "OBJ.kick.wav", "stem_id": "Kick.wav"}],
            "beds": [],
        }

        bound_scene, _bound_locks, summary = bind_scene_inputs_to_session(
            scene_payload=scene_payload,
            session_payload=_session_payload(),
            locks_payload=None,
        )

        self.assertEqual(bound_scene["objects"][0]["stem_id"], "kick")
        self.assertEqual(summary["status"], "rewritten")
        self.assertEqual(summary["rewritten_refs"][0]["binding_mode"], SCENE_BINDING_MODE_BASENAME)

    def test_ambiguous_basename_fallback_refuses_to_bind(self) -> None:
        session_payload = {
            "stems_dir": "/workspace/stems",
            "workspace_dir": "/workspace",
            "stems": [
                {
                    "stem_id": "drums_kick",
                    "file_path": "stems/drums/Kick.wav",
                },
                {
                    "stem_id": "samples_kick",
                    "file_path": "stems/samples/Kick.wav",
                },
            ],
        }
        scene_payload = {
            "objects": [{"object_id": "OBJ.kick.wav", "stem_id": "Kick.wav"}],
            "beds": [],
        }

        bound_scene, _bound_locks, summary = bind_scene_inputs_to_session(
            scene_payload=scene_payload,
            session_payload=session_payload,
            locks_payload=None,
        )

        self.assertEqual(bound_scene["objects"][0]["stem_id"], "Kick.wav")
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["bound_count"], 0)
        self.assertEqual(summary["unbound_count"], 1)
        self.assertEqual(
            summary["binding_warnings"][0]["warning_code"],
            SCENE_BINDING_WARNING_AMBIGUOUS_BASENAME,
        )
        self.assertEqual(
            summary["binding_warnings"][0]["candidates"],
            ["drums_kick", "samples_kick"],
        )


if __name__ == "__main__":
    unittest.main()
