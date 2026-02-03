import unittest

from plugins.detectors.phase_correlation_detector import PhaseCorrelationDetector
from plugins.resolvers.polarity_invert_resolver import PolarityInvertResolver


class TestPhaseCorrelationDetectorPairs(unittest.TestCase):
    def test_stereo_negative_correlation_emits_stereo_issue(self) -> None:
        detector = PhaseCorrelationDetector()
        session = {
            "stems": [
                {
                    "stem_id": "stem-stereo",
                    "file_path": "stereo.wav",
                    "channel_count": 2,
                    "measurements": [
                        {"evidence_id": "EVID.IMAGE.CORRELATION", "value": -0.5}
                    ],
                }
            ]
        }

        issues = detector.detect(session, {})
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["issue_id"], "ISSUE.IMAGING.NEGATIVE_CORRELATION")

    def test_multichannel_negative_pair_emits_pair_issue_only(self) -> None:
        detector = PhaseCorrelationDetector()
        session = {
            "stems": [
                {
                    "stem_id": "stem-surround",
                    "file_path": "surround.wav",
                    "channel_count": 6,
                    "measurements": [
                        {"evidence_id": "EVID.IMAGE.CORRELATION.FL_FR", "value": -0.5},
                        {"evidence_id": "EVID.IMAGE.CORRELATION.SL_SR", "value": 0.2},
                        {
                            "evidence_id": "EVID.IMAGE.CORRELATION_PAIRS_LOG",
                            "value": "{...}",
                        },
                    ],
                }
            ]
        }

        issues = detector.detect(session, {})
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["issue_id"], "ISSUE.IMAGING.NEGATIVE_CORRELATION_PAIR")
        evidence_ids = [entry["evidence_id"] for entry in issues[0].get("evidence", [])]
        self.assertNotIn("EVID.IMAGE.CORRELATION", evidence_ids)
        self.assertIn("EVID.TRACK.CHANNELS", evidence_ids)
        self.assertIn("EVID.IMAGE.CORRELATION.FL_FR", evidence_ids)
        self.assertIn("EVID.IMAGE.CORRELATION.SL_SR", evidence_ids)
        self.assertIn("EVID.IMAGE.CORRELATION_PAIRS_LOG", evidence_ids)

    def test_resolver_stereo_only(self) -> None:
        resolver = PolarityInvertResolver()
        session = {
            "stems": [
                {"stem_id": "stem-stereo", "channel_count": 2},
                {"stem_id": "stem-surround", "channel_count": 6},
            ]
        }
        issues = [
            {
                "issue_id": "ISSUE.IMAGING.NEGATIVE_CORRELATION",
                "target": {"scope": "stem", "stem_id": "stem-stereo"},
                "evidence": [
                    {"evidence_id": "EVID.IMAGE.CORRELATION", "value": -0.4}
                ],
            },
            {
                "issue_id": "ISSUE.IMAGING.NEGATIVE_CORRELATION",
                "target": {"scope": "stem", "stem_id": "stem-stereo"},
                "evidence": [],
            },
            {
                "issue_id": "ISSUE.IMAGING.NEGATIVE_CORRELATION_PAIR",
                "target": {"scope": "stem", "stem_id": "stem-surround"},
                "evidence": [
                    {"evidence_id": "EVID.IMAGE.CORRELATION.FL_FR", "value": -0.5}
                ],
            },
        ]

        recommendations = resolver.resolve(session, {}, issues)
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(
            recommendations[0]["issue_id"], "ISSUE.IMAGING.NEGATIVE_CORRELATION"
        )
        self.assertEqual(
            recommendations[0].get("target", {}).get("stem_id"), "stem-stereo"
        )


if __name__ == "__main__":
    unittest.main()
