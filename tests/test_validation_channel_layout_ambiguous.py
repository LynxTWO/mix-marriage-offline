import unittest


class TestValidationChannelLayoutAmbiguous(unittest.TestCase):
    def _assert_has_mode_evidence(self, issues) -> None:
        for issue in issues:
            if issue.get("issue_id") != "ISSUE.VALIDATION.CHANNEL_LAYOUT_AMBIGUOUS":
                continue
            evidence = issue.get("evidence", [])
            evidence_ids = {
                item.get("evidence_id")
                for item in evidence
                if isinstance(item, dict)
            }
            self.assertIn("EVID.METER.LUFS_WEIGHTING_MODE", evidence_ids)
            self.assertIn("EVID.METER.LUFS_WEIGHTING_ORDER", evidence_ids)
            return
        self.fail("Channel layout ambiguous issue missing from issues list.")

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
        self._assert_has_mode_evidence(issues)

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
        self._assert_has_mode_evidence(issues)

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
        self._assert_has_mode_evidence(issues)


if __name__ == "__main__":
    unittest.main()
