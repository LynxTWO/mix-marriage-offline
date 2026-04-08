from __future__ import annotations

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from mmo.core.stems_index import (
    build_stems_index,
    discover_audio_files,
    find_stem_sets,
    resolve_stem_sets,
)


def _write_tiny_wav(path: Path, *, channels: int = 2, sample_rate: int = 48000) -> None:
    """Write a minimal valid 16-bit PCM WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * channels * 10)


class TestStemsIndexChaos(unittest.TestCase):
    # ------------------------------------------------------------------
    # Empty and missing-root cases
    # ------------------------------------------------------------------

    def test_non_existent_root_raises(self) -> None:
        with self.assertRaises(ValueError) as exc:
            discover_audio_files(Path("/this/does/not/exist/ever"))
        self.assertIn("does not exist", str(exc.exception).lower())

    def test_root_is_file_not_dir_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a_file = Path(tmp) / "not_a_dir.wav"
            _write_tiny_wav(a_file)
            with self.assertRaises(ValueError) as exc:
                discover_audio_files(a_file)
        self.assertIn("directory", str(exc.exception).lower())

    def test_empty_folder_returns_no_audio_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = discover_audio_files(Path(tmp))
        self.assertEqual(result, [])

    def test_empty_folder_returns_no_stem_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = find_stem_sets(Path(tmp))
        self.assertEqual(result, [])

    # ------------------------------------------------------------------
    # Junk files are ignored
    # ------------------------------------------------------------------

    def test_non_audio_files_not_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".DS_Store").write_bytes(b"\x00")
            (root / "Thumbs.db").write_bytes(b"\x00")
            (root / "notes.txt").write_text("session notes\n", encoding="utf-8")
            (root / "cover.jpg").write_bytes(b"\xff\xd8\xff")
            (root / "session.als").write_bytes(b"\x00")
            result = discover_audio_files(root)
        self.assertEqual(result, [])

    def test_hidden_junk_in_stems_folder_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tiny_wav(root / "01_kick.wav")
            (root / ".gitkeep").write_text("", encoding="utf-8")
            (root / "render_log.txt").write_text("log data\n", encoding="utf-8")
            result = discover_audio_files(root)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "01_kick.wav")

    # ------------------------------------------------------------------
    # Unicode and unusual filenames
    # ------------------------------------------------------------------

    def test_unicode_stem_name_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tiny_wav(root / "café_lead_vocal.wav")
            result = discover_audio_files(root)
        self.assertEqual(len(result), 1)

    def test_spaces_in_stem_name_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tiny_wav(root / "01 kick drum main.wav")
            result = discover_audio_files(root)
        self.assertEqual(len(result), 1)

    def test_long_stem_name_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            long_name = "A" * 120 + "_stem.wav"
            _write_tiny_wav(root / long_name)
            result = discover_audio_files(root)
        self.assertEqual(len(result), 1)

    def test_mixed_case_extensions_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tiny_wav(root / "kick.WAV")
            _write_tiny_wav(root / "snare.Wav")
            result = discover_audio_files(root)
        self.assertEqual(len(result), 2)

    # ------------------------------------------------------------------
    # Stem set discovery
    # ------------------------------------------------------------------

    def test_audio_files_in_root_form_single_stem_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tiny_wav(root / "01_kick.wav")
            _write_tiny_wav(root / "02_snare.wav")
            _write_tiny_wav(root / "03_bass.wav")
            sets = find_stem_sets(root)
        self.assertEqual(len(sets), 1)
        self.assertEqual(sets[0].resolve(), root.resolve())

    def test_stems_index_includes_all_discovered_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tiny_wav(root / "01_kick.wav")
            _write_tiny_wav(root / "02_snare.wav")
            index = build_stems_index(root)
        stem_names = {f["rel_path"].split("/")[-1] for f in index["files"]}
        self.assertIn("01_kick.wav", stem_names)
        self.assertIn("02_snare.wav", stem_names)

    def test_stems_index_file_count_matches_discovered_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(5):
                _write_tiny_wav(root / f"{i + 1:02d}_stem.wav")
            index = build_stems_index(root)
        self.assertEqual(len(index["files"]), 5)

    def test_resolve_stem_sets_returns_public_fields_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tiny_wav(root / "01_kick.wav")
            sets = resolve_stem_sets(root)
        self.assertEqual(len(sets), 1)
        public_keys = set(sets[0].keys())
        # Internal keys starting with _ must not leak
        self.assertFalse(any(k.startswith("_") for k in public_keys))
        self.assertIn("set_id", public_keys)
        self.assertIn("file_count", public_keys)
        self.assertIn("rel_dir", public_keys)

    # ------------------------------------------------------------------
    # Mixed and partial stem sets
    # ------------------------------------------------------------------

    def test_only_junk_files_produces_empty_stem_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "session.als").write_bytes(b"\x00")
            (root / "notes.txt").write_text("notes", encoding="utf-8")
            sets = find_stem_sets(root)
        self.assertEqual(sets, [])

    def test_single_stem_file_still_forms_valid_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tiny_wav(root / "01_lead_vocal.wav")
            index = build_stems_index(root)
        self.assertEqual(len(index["files"]), 1)
        self.assertEqual(len(index["stem_sets"]), 1)

    def test_stems_index_version_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tiny_wav(root / "01_kick.wav")
            index = build_stems_index(root)
        # build_stems_index uses "version", not "schema_version"
        self.assertIn("version", index)

    def test_stem_ids_are_unique_across_differently_named_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_tiny_wav(root / "kick.wav")
            _write_tiny_wav(root / "snare.wav")
            _write_tiny_wav(root / "bass.wav")
            index = build_stems_index(root)
        stem_ids = [f["stem_id"] for f in index["files"]]
        self.assertEqual(len(stem_ids), len(set(stem_ids)), "stem_ids must be unique")


if __name__ == "__main__":
    unittest.main()
