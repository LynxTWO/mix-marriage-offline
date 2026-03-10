from __future__ import annotations

import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from mmo.core.media_tags import RawTag, canonicalize_tag_bag, tag_bag_from_mapping
from mmo.core.tag_export import build_ffmpeg_tag_export_args, metadata_receipt_mapping
from mmo.core.trace_metadata import trace_tag_bag_from_metadata
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd
from mmo.dsp.decoders import read_metadata
from mmo.dsp.transcode import transcode_wav_to_format


class TestTagExport(unittest.TestCase):
    def _write_fixture_ffprobe(self, temp_path: Path, fixture_dir: Path) -> Path:
        script_path = temp_path / "fixture_ffprobe.py"
        script_path.write_text(
            (
                "import json\n"
                "import os\n"
                "import pathlib\n"
                "import sys\n"
                "\n"
                "base = pathlib.Path(sys.argv[0]).resolve().parent / 'fixtures'\n"
                "suffix = os.path.splitext(sys.argv[-1])[1].lower()\n"
                "mapping = {\n"
                "    '.flac': 'flac_ffprobe_payload.json',\n"
                "    '.wv': 'wv_ffprobe_payload.json',\n"
                "}\n"
                "name = mapping.get(suffix)\n"
                "if name is None:\n"
                "    print(json.dumps({'streams': [], 'format': {}}))\n"
                "else:\n"
                "    print((base / name).read_text(encoding='utf-8'))\n"
            ),
            encoding="utf-8",
        )
        script_fixture_dir = temp_path / "fixtures"
        script_fixture_dir.mkdir(parents=True, exist_ok=True)
        for fixture_name in ("flac_ffprobe_payload.json", "wv_ffprobe_payload.json"):
            (script_fixture_dir / fixture_name).write_text(
                (fixture_dir / fixture_name).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        return script_path

    def test_flac_and_wv_custom_tags_are_preserved_and_embedded(self) -> None:
        fixture_dir = Path(__file__).resolve().parent / "fixtures" / "tag_export"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            ffprobe_script = self._write_fixture_ffprobe(temp_path, fixture_dir)
            flac_path = temp_path / "in.flac"
            wv_path = temp_path / "in.wv"
            flac_path.write_bytes(b"")
            wv_path.write_bytes(b"")

            with mock.patch.dict(os.environ, {"MMO_FFPROBE_PATH": str(ffprobe_script)}):
                flac_metadata = read_metadata(flac_path)
                wv_metadata = read_metadata(wv_path)

            flac_tag_bag = tag_bag_from_mapping(flac_metadata.get("tags"))
            wv_tag_bag = tag_bag_from_mapping(wv_metadata.get("tags"))

            self.assertIn("mmo_custom", flac_tag_bag.normalized)
            self.assertIn("x_custom_flac", flac_tag_bag.normalized)
            self.assertIn("mmo_custom", wv_tag_bag.normalized)
            self.assertIn("x_custom_wv", wv_tag_bag.normalized)

            flac_args, flac_embedded, flac_skipped, flac_warnings = build_ffmpeg_tag_export_args(
                flac_tag_bag,
                "flac",
            )
            wv_args, wv_embedded, wv_skipped, wv_warnings = build_ffmpeg_tag_export_args(
                wv_tag_bag,
                "wv",
            )

            self.assertIn("mmo_custom=flac-custom-value", flac_args)
            self.assertIn("mmo_custom=wv-custom-value", wv_args)
            self.assertIn("mmo_custom", {key.lower() for key in flac_embedded})
            self.assertIn("mmo_custom", {key.lower() for key in wv_embedded})
            self.assertEqual(flac_skipped, [])
            self.assertEqual(wv_skipped, [])
            self.assertEqual(flac_warnings, [])
            self.assertEqual(wv_warnings, [])

    def test_wav_export_policy_embeds_info_subset_and_reports_skips(self) -> None:
        tag_bag = canonicalize_tag_bag(
            [
                RawTag(
                    source="format",
                    container="wav",
                    scope="format",
                    key="TITLE",
                    value="Policy Song",
                    index=0,
                ),
                RawTag(
                    source="format",
                    container="wav",
                    scope="format",
                    key="ARTIST",
                    value="Policy Artist",
                    index=0,
                ),
                RawTag(
                    source="format",
                    container="wav",
                    scope="format",
                    key="X_PRIVATE",
                    value="secret",
                    index=0,
                ),
            ],
        )

        metadata_args, embedded_keys, skipped_keys, warnings = build_ffmpeg_tag_export_args(
            tag_bag,
            "wav",
        )
        receipt = metadata_receipt_mapping(
            output_container_format_id="wav",
            embedded_keys=embedded_keys,
            skipped_keys=skipped_keys,
            warnings=warnings,
        )

        self.assertIn("INAM=Policy Song", metadata_args)
        self.assertIn("IART=Policy Artist", metadata_args)
        self.assertIn("title", {key.lower() for key in embedded_keys})
        self.assertIn("artist", {key.lower() for key in embedded_keys})
        self.assertIn("x_private", {key.lower() for key in skipped_keys})
        self.assertEqual(receipt["container_format"], "wav")
        self.assertIn("x_private", {key.lower() for key in receipt["skipped_keys"]})

    def test_lossless_transcodes_preserve_trace_keys_across_supported_formats(self) -> None:
        ffmpeg_cmd = resolve_ffmpeg_cmd()
        if ffmpeg_cmd is None:
            self.skipTest("ffmpeg not available")

        trace_bag = trace_tag_bag_from_metadata(
            {
                "mmo_version": "1.2.3",
                "scene_sha256": "a" * 64,
                "render_contract_version": "0.1.0",
                "downmix_policy_version": "0.1.0",
                "layout_id": "LAYOUT.2_0",
                "profile_id": "PROFILE.ASSIST",
                "export_profile_id": "PROFILE.ASSIST",
                "seed": "7",
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_wav = temp_path / "source.wav"
            with wave.open(str(source_wav), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(48000)
                handle.writeframes(b"\x00\x00" * 16)
            for output_format, suffix in (
                ("flac", ".flac"),
                ("wv", ".wv"),
                ("aiff", ".aiff"),
                ("alac", ".m4a"),
            ):
                target = temp_path / f"trace{suffix}"
                metadata_args, embedded_keys, skipped_keys, warnings = (
                    build_ffmpeg_tag_export_args(trace_bag, output_format)
                )
                self.assertEqual(skipped_keys, [])
                self.assertEqual(warnings, [])

                transcode_wav_to_format(
                    ffmpeg_cmd,
                    source_wav,
                    target,
                    output_format,
                    metadata_args=metadata_args,
                )
                metadata = read_metadata(target)
                normalized = metadata.get("tags", {}).get("normalized", {})
                for key, values in trace_bag.normalized.items():
                    self.assertEqual(normalized.get(key), values)
                self.assertEqual(sorted(embedded_keys), sorted(trace_bag.normalized.keys()))


if __name__ == "__main__":
    unittest.main()
