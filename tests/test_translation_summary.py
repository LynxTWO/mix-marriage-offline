import unittest

from mmo.core.translation_summary import build_translation_summary


class TestTranslationSummary(unittest.TestCase):
    def test_build_translation_summary_status_logic_and_ordering(self) -> None:
        profiles = {
            "TRANS.DEVICE.CAR": {
                "label": "Car",
                "score_warn_below": 70,
                "score_fail_below": 50,
            },
            "TRANS.DEVICE.PHONE": {
                "label": "Phone",
                "score_warn_below": 80,
                "score_fail_below": 60,
            },
            "TRANS.MONO.COLLAPSE": {
                "label": "Mono collapse",
                "score_warn_below": 70,
                "score_fail_below": 40,
            },
        }
        translation_results = [
            {
                "profile_id": "TRANS.MONO.COLLAPSE",
                "score": 39,
                "issues": [
                    {
                        "issue_id": "ISSUE.TRANSLATION.PROFILE_SCORE_LOW",
                        "severity": 70,
                        "confidence": 1.0,
                        "evidence": [],
                    }
                ],
            },
            {
                "profile_id": "TRANS.DEVICE.PHONE",
                "score": 62,
                "issues": [
                    {
                        "issue_id": "ISSUE.TRANSLATION.PROFILE_SCORE_LOW",
                        "severity": 55,
                        "confidence": 1.0,
                        "evidence": [],
                    }
                ],
            },
            {
                "profile_id": "TRANS.DEVICE.CAR",
                "score": 85,
            },
        ]

        payload = build_translation_summary(translation_results, profiles)
        self.assertEqual(
            [item.get("profile_id") for item in payload if isinstance(item, dict)],
            ["TRANS.DEVICE.CAR", "TRANS.DEVICE.PHONE", "TRANS.MONO.COLLAPSE"],
        )
        self.assertEqual(
            {
                item.get("profile_id"): item.get("status")
                for item in payload
                if isinstance(item, dict)
            },
            {
                "TRANS.DEVICE.CAR": "pass",
                "TRANS.DEVICE.PHONE": "warn",
                "TRANS.MONO.COLLAPSE": "fail",
            },
        )
        self.assertEqual(
            {
                item.get("profile_id"): item.get("label")
                for item in payload
                if isinstance(item, dict)
            },
            {
                "TRANS.DEVICE.CAR": "Car",
                "TRANS.DEVICE.PHONE": "Phone",
                "TRANS.MONO.COLLAPSE": "Mono collapse",
            },
        )

        by_profile = {
            item.get("profile_id"): item
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("profile_id"), str)
        }
        self.assertEqual(
            by_profile["TRANS.DEVICE.CAR"].get("short_reason"),
            "Score meets threshold.",
        )
        self.assertEqual(
            by_profile["TRANS.DEVICE.PHONE"].get("short_reason"),
            "ISSUE.TRANSLATION.PROFILE_SCORE_LOW: score=62 fail<60 warn<80.",
        )
        self.assertEqual(
            by_profile["TRANS.MONO.COLLAPSE"].get("short_reason"),
            "ISSUE.TRANSLATION.PROFILE_SCORE_LOW: score=39 fail<40 warn<70.",
        )

    def test_build_translation_summary_is_deterministic(self) -> None:
        profiles = {
            "TRANS.DEVICE.PHONE": {
                "label": "Phone",
                "score_warn_below": 70,
                "score_fail_below": 50,
            }
        }
        results = [{"profile_id": "TRANS.DEVICE.PHONE", "score": 70}]
        first = build_translation_summary(results, profiles)
        second = build_translation_summary(results, profiles)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
