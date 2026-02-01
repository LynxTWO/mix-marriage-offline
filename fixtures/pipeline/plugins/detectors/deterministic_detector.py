from __future__ import annotations

from typing import Any, Dict, List


class DeterministicDetector:
    plugin_id = "PLUGIN.DETECTOR.FIXTURE_DETERMINISTIC"

    def detect(self, session: Dict[str, Any], features: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {
                "issue_id": "ISSUE.FIXTURE.DETERMINISTIC",
                "severity": 10,
                "confidence": 1.0,
                "message": "Fixture detector emitted deterministic issue.",
                "target": {"scope": "session"},
                "evidence": [
                    {"evidence_id": "EVID.FIXTURE.DETERMINISTIC", "value": "ok"}
                ],
            }
        ]
