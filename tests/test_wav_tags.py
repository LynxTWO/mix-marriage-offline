import struct
import tempfile
import unittest
from pathlib import Path

from mmo.dsp.io import read_wav_metadata


def _chunk(tag: bytes, data: bytes) -> bytes:
    padding = b"\x00" if len(data) % 2 == 1 else b""
    return tag + struct.pack("<I", len(data)) + data + padding


class TestWavTagParsing(unittest.TestCase):
    def test_read_wav_metadata_parses_info_bext_ixml_and_unknown_chunk_warning(self) -> None:
        fmt_payload = struct.pack("<HHIIHH", 1, 1, 8000, 16000, 2, 16)
        fmt_chunk = _chunk(b"fmt ", fmt_payload)
        data_chunk = _chunk(b"data", b"\x00\x00")

        list_info_payload = (
            b"INFO"
            + _chunk(b"INAM", b"My Song\x00")
            + _chunk(b"IART", b"The Artist\x00")
        )
        list_chunk = _chunk(b"LIST", list_info_payload)

        bext_payload = bytearray(610)
        bext_payload[0:5] = b"Desc\x00"
        bext_payload[256:261] = b"Orig\x00"
        bext_payload[320:330] = b"2026-02-28"
        bext_payload[330:338] = b"12:34:56"
        bext_payload[338:346] = struct.pack("<Q", 42)
        bext_payload[346:348] = struct.pack("<H", 1)
        bext_payload[602:607] = b"A=PCM"
        bext_chunk = _chunk(b"bext", bytes(bext_payload))

        ixml_chunk = _chunk(b"iXML", b"<BWFXML><PROJECT>MMO</PROJECT></BWFXML>\x00")
        unknown_chunk = _chunk(b"zzzz", b"\x01\x02")

        riff_payload = (
            b"WAVE"
            + fmt_chunk
            + data_chunk
            + list_chunk
            + bext_chunk
            + ixml_chunk
            + unknown_chunk
        )
        riff_bytes = b"RIFF" + struct.pack("<I", len(riff_payload)) + riff_payload

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = Path(handle.name)
            handle.write(riff_bytes)

        try:
            metadata = read_wav_metadata(path)
            tags = metadata.get("tags")
            self.assertIsInstance(tags, dict)
            if not isinstance(tags, dict):
                return

            normalized = tags.get("normalized")
            self.assertIsInstance(normalized, dict)
            if not isinstance(normalized, dict):
                return

            self.assertEqual(normalized.get("inam"), ["My Song"])
            self.assertEqual(normalized.get("iart"), ["The Artist"])
            self.assertEqual(normalized.get("description"), ["Desc"])
            self.assertEqual(normalized.get("originator"), ["Orig"])
            self.assertEqual(normalized.get("origination_date"), ["2026-02-28"])
            self.assertEqual(normalized.get("origination_time"), ["12:34:56"])
            self.assertEqual(normalized.get("time_reference"), ["42"])
            self.assertEqual(normalized.get("version"), ["1"])
            self.assertEqual(normalized.get("coding_history"), ["A=PCM"])
            self.assertEqual(
                normalized.get("xml"),
                ["<BWFXML><PROJECT>MMO</PROJECT></BWFXML>"],
            )

            warnings = tags.get("warnings")
            self.assertIn("Unknown WAV chunk 'zzzz' size=2", warnings)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
