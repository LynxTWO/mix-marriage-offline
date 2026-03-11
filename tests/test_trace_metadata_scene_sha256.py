"""Regression tests: scene_sha256 is path-stable across OS/runner paths."""

from __future__ import annotations

from mmo.core.trace_metadata import _canonical_sha256, _canonicalize_scene_for_hash


def _hash(payload: object) -> str:
    return _canonical_sha256(_canonicalize_scene_for_hash(payload))


def _minimal_scene(*, stems_dir: str, stems_index_ref: str, bus_plan_ref: str, stems_map_ref: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "source": {"stems_dir": stems_dir, "created_from": "draft"},
        "source_refs": {
            "stems_index_ref": stems_index_ref,
            "bus_plan_ref": bus_plan_ref,
            "stems_map_ref": stems_map_ref,
        },
        "objects": [
            {
                "stem_id": "STEMFILE.abc123",
                "role_id": "ROLE.DRUM.KICK",
                "label": "kick",
            }
        ],
        "beds": [],
    }


def test_stems_index_ref_path_stable() -> None:
    """Same logical scene with different absolute stems_index_ref paths hashes identically."""
    scene_linux = _minimal_scene(
        stems_dir="/projects/session/stems",
        stems_index_ref="/home/runner/work/golden_small_stereo",
        bus_plan_ref="/tmp/run1/bus_plan.json",
        stems_map_ref="/tmp/run1/stems_map.json",
    )
    scene_windows = _minimal_scene(
        stems_dir="C:\\Users\\runner\\session\\stems",
        stems_index_ref="C:\\Users\\runner\\golden_small_stereo",
        bus_plan_ref="C:\\tmp\\run1\\bus_plan.json",
        stems_map_ref="C:\\tmp\\run1\\stems_map.json",
    )
    scene_macos = _minimal_scene(
        stems_dir="/Users/runner/session/stems",
        stems_index_ref="/Users/runner/golden_small_stereo",
        bus_plan_ref="/private/tmp/run1/bus_plan.json",
        stems_map_ref="/private/tmp/run1/stems_map.json",
    )
    assert _hash(scene_linux) == _hash(scene_windows) == _hash(scene_macos)


def test_stems_dir_always_replaced() -> None:
    """Different absolute stems_dir values all collapse to the same placeholder."""
    base = _minimal_scene(
        stems_dir="/SCENE/INTENT",
        stems_index_ref="stems_index.json",
        bus_plan_ref="bus_plan.json",
        stems_map_ref="stems_map.json",
    )
    absolute = _minimal_scene(
        stems_dir="/home/runner/work/session/stems",
        stems_index_ref="stems_index.json",
        bus_plan_ref="bus_plan.json",
        stems_map_ref="stems_map.json",
    )
    assert _hash(base) == _hash(absolute)


def test_file_path_separator_stable() -> None:
    """Relative file_path values with different OS separators hash identically."""
    scene_posix = {"file_path": "stems/kick.wav", "stem_id": "STEMFILE.abc"}
    scene_win = {"file_path": "stems\\kick.wav", "stem_id": "STEMFILE.abc"}
    assert _hash(scene_posix) == _hash(scene_win)


def test_file_path_absolute_reduced_to_basename() -> None:
    """Absolute file_path is reduced to basename for stable hashing."""
    scene_abs_linux = {"file_path": "/home/runner/stems/kick.wav", "stem_id": "STEMFILE.abc"}
    scene_abs_win = {"file_path": "C:\\runner\\stems\\kick.wav", "stem_id": "STEMFILE.abc"}
    scene_rel = {"file_path": "kick.wav", "stem_id": "STEMFILE.abc"}
    assert _hash(scene_abs_linux) == _hash(scene_abs_win) == _hash(scene_rel)


def test_semantic_differences_preserved() -> None:
    """Different stem_ids and role_ids still produce different hashes."""
    scene_kick = _minimal_scene(
        stems_dir="/a/b",
        stems_index_ref="/a/b",
        bus_plan_ref="bus_plan.json",
        stems_map_ref="stems_map.json",
    )
    scene_kick["objects"] = [{"stem_id": "STEMFILE.kick", "role_id": "ROLE.DRUM.KICK"}]
    scene_snare = dict(scene_kick)
    scene_snare["objects"] = [{"stem_id": "STEMFILE.snare", "role_id": "ROLE.DRUM.SNARE"}]
    assert _hash(scene_kick) != _hash(scene_snare)
