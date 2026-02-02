import unittest


class TestValidationChannelLayoutAmbiguous(unittest.TestCase):
    def test_conflict_mask_vs_layout_warns(self) -> None:
        from mmo.core.validators import validate_session

        session = {
            "stems": [
                {
                    "stem_id": "s1",
                    "file_path": "dummy.wav",
                    "channel_count": 6,
                    "wav_channel_mask": 0x00000001
                    | 0x00000002
                    | 0x00000004
                    | 0x00000008
                    | 0x00000010
                    | 0x00000020,
                    "channel_layout": "5.1(side)",
                }
            ]
        }

        issues = validate_session(session)
        issue_ids = {item.get("issue_id") for item in issues if isinstance(item, dict)}
        self.assertIn("ISSUE.VALIDATION.CHANNEL_LAYOUT_AMBIGUOUS", issue_ids)

    def test_layout_61_without_mask_warns(self) -> None:
        from mmo.core.validators import validate_session

        session = {
            "stems": [
                {
                    "stem_id": "s1",
                    "file_path": "dummy.flac",
                    "channel_count": 7,
                    "channel_layout": "6.1",
                }
            ]
        }
        issues = validate_session(session)
        issue_ids = {item.get("issue_id") for item in issues if isinstance(item, dict)}
        self.assertIn("ISSUE.VALIDATION.CHANNEL_LAYOUT_AMBIGUOUS", issue_ids)

    def test_layout_underspecified_warns(self) -> None:
        from mmo.core.validators import validate_session

        session = {
            "stems": [
                {
                    "stem_id": "s1",
                    "file_path": "dummy.flac",
                    "channel_count": 8,
                    "channel_layout": "5.1",
                }
            ]
        }
        issues = validate_session(session)
        issue_ids = {item.get("issue_id") for item in issues if isinstance(item, dict)}
        self.assertIn("ISSUE.VALIDATION.CHANNEL_LAYOUT_AMBIGUOUS", issue_ids)


if __name__ == "__main__":
    unittest.main()
