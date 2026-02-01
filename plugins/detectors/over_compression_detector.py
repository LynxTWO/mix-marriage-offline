from __future__ import annotations

from typing import Any, Dict, List, Optional

from mmo.plugins.interfaces import DetectorPlugin, Issue

CREST_EVIDENCE_ID = "EVID.METER.CREST_FACTOR_DB"
RMS_EVIDENCE_ID = "EVID.METER.RMS_DBFS"

CREST_THRESHOLD_DB = 6.0
RMS_THRESHOLD_DBFS = -12.0


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


class OverCompressionDetector(DetectorPlugin):
    plugin_id = "PLUGIN.DETECTOR.OVER_COMPRESSION"

    def detect(self, session: Dict[str, Any], features: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        stems = session.get("stems", [])
        for stem in stems:
            if not isinstance(stem, dict):
                continue
            measurements = _index_measurements(stem)
            crest = _coerce_number(measurements.get(CREST_EVIDENCE_ID))
            rms = _coerce_number(measurements.get(RMS_EVIDENCE_ID))
            if crest is None or rms is None:
                continue
            if crest > CREST_THRESHOLD_DB or rms < RMS_THRESHOLD_DBFS:
                continue

            evidence: List[Dict[str, Any]] = [
                {
                    "evidence_id": CREST_EVIDENCE_ID,
                    "value": crest,
                    "unit_id": "UNIT.DB",
                },
                {
                    "evidence_id": RMS_EVIDENCE_ID,
                    "value": rms,
                    "unit_id": "UNIT.DBFS",
                },
            ]
            file_path = stem.get("file_path")
            if isinstance(file_path, str) and file_path:
                evidence.insert(0, {"evidence_id": "EVID.FILE.PATH", "value": file_path})

            issues.append(
                {
                    "issue_id": "ISSUE.DYNAMICS.OVER_COMPRESSION",
                    "severity": 35,
                    "confidence": 0.6,
                    "target": _stem_target(stem.get("stem_id")),
                    "evidence": evidence,
                }
            )

        return issues
