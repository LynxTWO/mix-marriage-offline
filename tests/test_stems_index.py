import hashlib
import json
import tempfile
import unittest
import wave
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from mmo.core.stems_index import (
    build_stems_index,
    find_stem_sets,
    pick_best_stem_set,
    resolve_stem_sets,
)


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


class TestStemsIndex(unittest.TestCase):
    def test_find_stem_sets_prefers_leaf_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "stems_root"
            _write_tiny_wav(root / "album" / "stems" / "kick.wav")
            _write_tiny_wav(root / "album" / "stems" / "sub" / "room.wav")
            _write_tiny_wav(root / "bonus" / "tracks" / "bass.wav")

            sets = find_stem_sets(root)
            rel_dirs = [path.relative_to(root.resolve()).as_posix() for path in sets]
            self.assertEqual(rel_dirs, ["album/stems/sub", "bonus/tracks"])

    def test_find_stem_sets_uses_root_when_root_contains_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "stems_root"
            _write_tiny_wav(root / "mix.wav")
            _write_tiny_wav(root / "nested" / "kick.wav")

            sets = find_stem_sets(root)
            self.assertEqual(sets, [root.resolve()])

    def test_build_stems_index_is_deterministic_and_schema_valid(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        validator = _schema_validator(repo_root / "schemas" / "stems_index.schema.json")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "stems_root"
            _write_tiny_wav(root / "Disc 01" / "stems" / "01_Kick-L.wav")
            _write_tiny_wav(root / "Disc 01" / "stems" / "02_Snare.wav")

            first = build_stems_index(root, root_dir="demo_input")
            second = build_stems_index(root, root_dir="demo_input")

            self.assertEqual(first, second)
            validator.validate(first)
            self.assertEqual(first.get("root_dir"), "demo_input")

            stem_sets = first.get("stem_sets")
            self.assertIsInstance(stem_sets, list)
            if not isinstance(stem_sets, list) or not stem_sets:
                return
            stem_set = stem_sets[0]
            rel_dir = "Disc 01/stems"
            expected_set_id = "STEMSET." + hashlib.sha1(rel_dir.encode("utf-8")).hexdigest()[:10]
            self.assertEqual(stem_set.get("set_id"), expected_set_id)

            files = first.get("files")
            self.assertIsInstance(files, list)
            if not isinstance(files, list):
                return
            rel_paths = [item.get("rel_path") for item in files if isinstance(item, dict)]
            self.assertEqual(rel_paths, sorted(rel_paths))

            kick_rel = "Disc 01/stems/01_Kick-L.wav"
            kick_entry = next((item for item in files if item.get("rel_path") == kick_rel), None)
            self.assertIsInstance(kick_entry, dict)
            if not isinstance(kick_entry, dict):
                return
            expected_file_id = "STEMFILE." + hashlib.sha1(kick_rel.encode("utf-8")).hexdigest()[:10]
            self.assertEqual(kick_entry.get("file_id"), expected_file_id)

    def test_tokenization_handles_numeric_prefixes_and_lr_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "stems_root"
            _write_tiny_wav(root / "Album One" / "stems" / "01_Lead-Vox_L.wav")
            _write_tiny_wav(root / "Album One" / "stems" / "1 - Guitar.Right.wav")
            _write_tiny_wav(root / "Album One" / "stems" / "02 - Pad(Left).wav")
            _write_tiny_wav(root / "Album One" / "stems" / "03_Bass_R.wav")

            payload = build_stems_index(root)
            files = payload.get("files")
            self.assertIsInstance(files, list)
            if not isinstance(files, list):
                return

            tokens_by_basename = {
                item.get("basename"): item.get("tokens")
                for item in files
                if isinstance(item, dict) and isinstance(item.get("basename"), str)
            }
            self.assertEqual(tokens_by_basename.get("01_Lead-Vox_L"), ["lead", "vox", "l"])
            self.assertEqual(tokens_by_basename.get("1 - Guitar.Right"), ["guitar", "right"])
            self.assertEqual(tokens_by_basename.get("02 - Pad(Left)"), ["pad", "left"])
            self.assertEqual(tokens_by_basename.get("03_Bass_R"), ["bass", "r"])

            folder_tokens = next(
                (
                    item.get("folder_tokens")
                    for item in files
                    if isinstance(item, dict) and item.get("basename") == "01_Lead-Vox_L"
                ),
                None,
            )
            self.assertEqual(folder_tokens, ["album", "one", "stems"])

    def test_pick_best_stem_set_uses_hint_then_file_count_then_rel_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "stems_root"
            _write_tiny_wav(root / "tracks" / "a.wav")
            _write_tiny_wav(root / "tracks" / "b.wav")
            _write_tiny_wav(root / "stems" / "lead.wav")
            _write_tiny_wav(root / "alpha" / "kick.wav")
            _write_tiny_wav(root / "alpha" / "snare.wav")
            _write_tiny_wav(root / "alpha" / "bass.wav")

            stem_sets = resolve_stem_sets(root)
            best = pick_best_stem_set(stem_sets)
            self.assertIsInstance(best, dict)
            if not isinstance(best, dict):
                return
            self.assertEqual(best.get("rel_dir"), "tracks")


if __name__ == "__main__":
    unittest.main()
