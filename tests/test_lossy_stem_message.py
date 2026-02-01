import os
import tempfile
import unittest
from pathlib import Path

from mmo.core.session import build_session_from_stems_dir
from mmo.core.validators import validate_session


class TestLossyStemMessage(unittest.TestCase):
    def test_lossy_stem_message_is_educational(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stems_dir = Path(temp_dir) / "stems"
            stems_dir.mkdir(parents=True)
            mp3_path = stems_dir / "demo.mp3"
            mp3_path.write_bytes(b"")

            session = build_session_from_stems_dir(stems_dir)
            issues = validate_session(session)
            lossy_issues = [
                issue
                for issue in issues
                if isinstance(issue, dict)
                and issue.get("issue_id") == "ISSUE.VALIDATION.LOSSY_STEMS_DETECTED"
            ]

            self.assertTrue(lossy_issues)
            message = lossy_issues[0].get("message", "")
            message_lower = message.lower()
            self.assertIn("lossy", message_lower)
            self.assertTrue("re-export" in message_lower or "export" in message_lower)
            self.assertTrue("wav" in message_lower or "flac" in message_lower)


if __name__ == "__main__":
    unittest.main()
