from __future__ import annotations

import unittest

from mmo.core.media_tags import RawTag, canonicalize_tag_bag, summarize_stem_source_tags, tag_bag_to_mapping


class TestMediaTags(unittest.TestCase):
    def test_canonicalize_tag_bag_sorts_and_keeps_duplicates(self) -> None:
        tag_bag = canonicalize_tag_bag(
            [
                RawTag(
                    source="stream",
                    container="wav",
                    scope="stream:1",
                    key="TITLE",
                    value="Song B",
                    index=1,
                ),
                RawTag(
                    source="format",
                    container="wav",
                    scope="format",
                    key="title",
                    value="Song A",
                    index=0,
                ),
                RawTag(
                    source="format",
                    container="wav",
                    scope="format",
                    key="ARTIST",
                    value="Artist X",
                    index=0,
                ),
            ],
            warnings=["warn-b", "warn-a", "warn-a"],
        )

        self.assertEqual(
            [
                (tag.source, tag.scope, tag.key, tag.value, tag.index)
                for tag in tag_bag.raw
            ],
            [
                ("format", "format", "ARTIST", "Artist X", 0),
                ("format", "format", "title", "Song A", 0),
                ("stream", "stream:1", "TITLE", "Song B", 1),
            ],
        )
        self.assertEqual(tag_bag.normalized["title"], ["Song A", "Song B"])
        self.assertEqual(tag_bag.normalized["artist"], ["Artist X"])
        self.assertEqual(list(tag_bag.warnings), ["warn-a", "warn-b"])

    def test_summarize_stem_source_tags_aggregates_summary_count_and_warnings(self) -> None:
        stem_tags_a = canonicalize_tag_bag(
            [
                RawTag(
                    source="format",
                    container="wav",
                    scope="info",
                    key="INAM",
                    value="Track Name",
                    index=0,
                ),
                RawTag(
                    source="format",
                    container="wav",
                    scope="info",
                    key="IART",
                    value="Artist Name",
                    index=0,
                ),
            ],
            warnings=["unknown chunk a"],
        )
        stem_tags_b = canonicalize_tag_bag(
            [
                RawTag(
                    source="format",
                    container="flac",
                    scope="format",
                    key="album",
                    value="Album Name",
                    index=0,
                ),
                RawTag(
                    source="stream",
                    container="flac",
                    scope="stream:0",
                    key="date",
                    value="2025",
                    index=0,
                ),
            ],
            warnings=["unknown chunk a", "unknown chunk b"],
        )

        summary = summarize_stem_source_tags(
            [
                {
                    "stem_id": "STEM.B",
                    "file_path": "b.wav",
                    "source_metadata": {"technical": {}, "tags": tag_bag_to_mapping(stem_tags_b)},
                },
                {
                    "stem_id": "STEM.A",
                    "file_path": "a.wav",
                    "source_metadata": {"technical": {}, "tags": tag_bag_to_mapping(stem_tags_a)},
                },
            ]
        )

        self.assertEqual(
            summary["normalized"],
            {
                "title": "Track Name",
                "artist": "Artist Name",
                "album": "Album Name",
                "date": "2025",
            },
        )
        self.assertEqual(summary["preserved_tag_count"], 4)
        self.assertEqual(summary["warnings"], ["unknown chunk a", "unknown chunk b"])


if __name__ == "__main__":
    unittest.main()
