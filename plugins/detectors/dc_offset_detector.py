from __future__ import annotations

from typing import Any, Dict, List, Optional

from mmo.plugins.interfaces import DetectorPlugin, Issue

DC_OFFSET_EVIDENCE_ID = "EVID.QUALITY.DC_OFFSET_PERCENT"
DC_OFFSET_THRESHOLD_PERCENT = 1.0


def _coerce_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _index_measurements(stem: Dict[str, Any]) -> Dict[str, Any]:
    measurements = stem.get("measurements")
    if not isinstance(measurements, list):
        return {}
    indexed: Dict[str, Any] = {}
    for measurement in measurements:
        if not isinstance(measurement, dict):
            continue
        evidence_id = measurement.get("evidence_id")
        if isinstance(evidence_id, str):
            indexed[evidence_id] = measurement.get("value")
    return indexed


def _stem_target(stem_id: Any) -> Dict[str, Any]:
    target: Dict[str, Any] = {"scope": "stem"}
    if isinstance(stem_id, str) and stem_id:
        target["stem_id"] = stem_id
    return target


class DcOffsetDetector(DetectorPlugin):
    plugin_id = "PLUGIN.DETECTOR.DC_OFFSET"

    def detect(self, session: Dict[str, Any], features: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        stems = session.get("stems", [])
        for stem in stems:
            if not isinstance(stem, dict):
                continue
            measurements = _index_measurements(stem)
            dc_offset = _coerce_number(measurements.get(DC_OFFSET_EVIDENCE_ID))
            if dc_offset is None:
                continue

            if abs(dc_offset) < DC_OFFSET_THRESHOLD_PERCENT:
                continue

            evidence: List[Dict[str, Any]] = [
                {
                    "evidence_id": DC_OFFSET_EVIDENCE_ID,
                    "value": dc_offset,
                    "unit_id": "UNIT.PERCENT",
                }
            ]
            file_path = stem.get("file_path")
            if isinstance(file_path, str) and file_path:
                evidence.insert(0, {"evidence_id": "EVID.FILE.PATH", "value": file_path})

            issues.append(
                {
                    "issue_id": "ISSUE.SAFETY.DC_OFFSET",
                    "severity": 40,
                    "confidence": 0.7,
                    "target": _stem_target(stem.get("stem_id")),
                    "evidence": evidence,
                }
            )

        return issues
