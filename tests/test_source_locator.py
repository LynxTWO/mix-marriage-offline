from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any

from mmo.core.session import build_session_from_stems_dir
from mmo.core.source_locator import (
    portable_stem_locator_metadata,
    RESOLUTION_MODE_FILE_PATH_ABSOLUTE,
    RESOLUTION_MODE_STEMS_DIR_RELATIVE,
    RESOLUTION_MODE_UNRESOLVED,
    RESOLUTION_MODE_WORKSPACE_SOURCE_REF,
    RESOLVE_ERROR_NOT_FOUND,
    resolve_session_stems,
    stem_locator_metadata,
)
from mmo.plugins.renderers.placement_mixdown_renderer import PlacementMixdownRenderer


def _write_mono_wav(
    path: Path,
    *,
    sample_rate_hz: int = 48_000,
    duration_s: float = 0.12,
    amplitude: float = 0.25,
    freq_hz: float = 220.0,
) -> None:
    frame_count = int(sample_rate_hz * duration_s)
    samples = [
        int(amplitude * 32767.0 * math.sin(2.0 * math.pi * freq_hz * index / sample_rate_hz))
        for index in range(frame_count)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class TestSourceLocator(unittest.TestCase):
    def test_resolves_explicit_absolute_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source_path = temp / "absolute.wav"
            _write_mono_wav(source_path)

            session = {
                "stems_dir": (temp / "unused").resolve().as_posix(),
                "stems": [
                    {
                        "stem_id": "STEM.ABS",
                        "file_path": source_path.resolve().as_posix(),
                    }
                ],
            }

            resolved = resolve_session_stems(session)[0]
            self.assertEqual(resolved["resolution_mode"], RESOLUTION_MODE_FILE_PATH_ABSOLUTE)
            self.assertEqual(resolved["resolved_path"], source_path.resolve().as_posix())
            self.assertIsNone(resolved["resolve_error_code"])

    def test_resolves_stems_dir_relative_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            source_path = stems_dir / "drums" / "kick.wav"
            _write_mono_wav(source_path)

            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "stems": [
                    {
                        "stem_id": "STEM.REL",
                        "file_path": "drums/kick.wav",
                    }
                ],
            }

            resolved = resolve_session_stems(session)[0]
            self.assertEqual(resolved["resolution_mode"], RESOLUTION_MODE_STEMS_DIR_RELATIVE)
            self.assertEqual(resolved["resolved_path"], source_path.resolve().as_posix())
            self.assertEqual(resolved["source_ref"], "drums/kick.wav")

    def test_resolves_workspace_relative_source_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            workspace_dir = temp / "workspace"
            source_path = workspace_dir / "sources" / "vox.wav"
            _write_mono_wav(source_path)

            session = {
                "stems_dir": (workspace_dir / "missing_stems").resolve().as_posix(),
                "workspace_dir": workspace_dir.resolve().as_posix(),
                "stems": [
                    {
                        "stem_id": "STEM.WORKSPACE",
                        "file_path": "missing.wav",
                        "workspace_relative_path": "sources/vox.wav",
                        "source_ref": "sources/vox.wav",
                    }
                ],
            }

            resolved = resolve_session_stems(session)[0]
            self.assertEqual(
                resolved["resolution_mode"],
                RESOLUTION_MODE_WORKSPACE_SOURCE_REF,
            )
            self.assertEqual(resolved["resolved_path"], source_path.resolve().as_posix())
            self.assertEqual(resolved["workspace_relative_path"], "sources/vox.wav")

    def test_unresolved_stem_emits_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            workspace_dir = temp / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            stems_dir = temp / "stems"
            stems_dir.mkdir(parents=True, exist_ok=True)

            session = {
                "stems_dir": stems_dir.resolve().as_posix(),
                "workspace_dir": workspace_dir.resolve().as_posix(),
                "stems": [
                    {
                        "stem_id": "STEM.MISSING",
                        "file_path": "ghost.wav",
                        "workspace_relative_path": "sources/ghost.wav",
                        "source_ref": "sources/ghost.wav",
                    }
                ],
            }

            resolved = resolve_session_stems(session)[0]
            self.assertEqual(resolved["resolution_mode"], RESOLUTION_MODE_UNRESOLVED)
            self.assertEqual(resolved["resolve_error_code"], RESOLVE_ERROR_NOT_FOUND)
            detail = str(resolved["resolve_error_detail"])
            self.assertIn((stems_dir / "ghost.wav").resolve().as_posix(), detail)
            self.assertIn((workspace_dir / "sources" / "ghost.wav").resolve().as_posix(), detail)

    def test_analysis_and_placement_render_share_resolved_stems(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stems_dir = temp / "stems"
            _write_mono_wav(stems_dir / "lead.wav")

            session = build_session_from_stems_dir(stems_dir)
            expected = [
                portable_stem_locator_metadata(stem, workspace_dir=None)
                for stem in session.get("stems", [])
                if isinstance(stem, dict)
            ]

            manifest = PlacementMixdownRenderer().render(
                session,
                recommendations=[],
                output_dir=temp / "renders",
            )

            self.assertEqual(manifest.get("stem_resolution"), expected)
            outputs = manifest.get("outputs")
            self.assertIsInstance(outputs, list)
            if isinstance(outputs, list):
                self.assertGreaterEqual(len(outputs), 1)
