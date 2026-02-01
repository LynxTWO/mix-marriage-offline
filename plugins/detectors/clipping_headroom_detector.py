from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from mmo.plugins.interfaces import DetectorPlugin, Issue

CLIP_EVIDENCE_IDS = [
    "EVID.METER.CLIP_SAMPLE_COUNT",
    "EVID.QUALITY.CLIPPED_SAMPLES_COUNT",
]
PEAK_EVIDENCE_IDS = [
    "EVID.METER.PEAK_DBFS",
    "EVID.METER.SAMPLE_PEAK_DBFS",
]


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


def _pick_peak_value(measurements: Dict[str, Any]) -> Tuple[Optional[str], Optional[float]]:
    for evidence_id in PEAK_EVIDENCE_IDS:
        value = _coerce_number(measurements.get(evidence_id))
        if value is not None:
            return evidence_id, value
    return None, None


def _collect_clip_values(measurements: Dict[str, Any]) -> List[Tuple[str, float]]:
    values: List[Tuple[str, float]] = []
    for evidence_id in CLIP_EVIDENCE_IDS:
        value = _coerce_number(measurements.get(evidence_id))
        if value is not None:
            values.append((evidence_id, value))
    return values


def _build_evidence(
    *,
    file_path: Optional[str],
    clip_entry: Optional[Tuple[str, float]],
    peak_entry: Optional[Tuple[str, float]],
) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    if file_path:
        evidence.append({"evidence_id": "EVID.FILE.PATH", "value": file_path})
    if clip_entry:
        evidence.append(
            {
                "evidence_id": clip_entry[0],
                "value": clip_entry[1],
                "unit_id": "UNIT.COUNT",
            }
        )
    if peak_entry:
        evidence.append(
            {
                "evidence_id": peak_entry[0],
                "value": peak_entry[1],
                "unit_id": "UNIT.DBFS",
            }
        )
    return evidence


class ClippingHeadroomDetector(DetectorPlugin):
    plugin_id = "PLUGIN.DETECTOR.CLIPPING_HEADROOM"

    def detect(self, session: Dict[str, Any], features: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        stems = session.get("stems", [])
        for stem in stems:
            if not isinstance(stem, dict):
                continue
            measurements = _index_measurements(stem)
            clip_values = _collect_clip_values(measurements)
            clip_hit = any(value > 0 for _, value in clip_values)

            peak_evidence_id, peak_value = _pick_peak_value(measurements)
            peak_entry = (
                (peak_evidence_id, peak_value)
                if peak_evidence_id is not None and peak_value is not None
                else None
            )

            file_path = stem.get("file_path") if isinstance(stem.get("file_path"), str) else None
            stem_id = stem.get("stem_id")
            target: Dict[str, Any] = {"scope": "stem"}
            if stem_id is not None:
                target["stem_id"] = stem_id

            clip_entry: Optional[Tuple[str, float]] = None
            if clip_values:
                if clip_hit:
                    for entry in clip_values:
                        if entry[1] > 0:
                            clip_entry = entry
                            break
                else:
                    clip_entry = clip_values[0]

            if clip_hit:
                evidence = _build_evidence(
                    file_path=file_path,
                    clip_entry=clip_entry,
                    peak_entry=peak_entry,
                )
                issues.append(
                    {
                        "issue_id": "ISSUE.SAFETY.CLIPPING_SAMPLES",
                        "severity": 90,
                        "confidence": 0.95,
                        "target": target,
                        "evidence": evidence,
                    }
                )
                continue

            if clip_entry and peak_entry and peak_value > -1.0:
                evidence = _build_evidence(
                    file_path=file_path,
                    clip_entry=clip_entry,
                    peak_entry=peak_entry,
                )
                issues.append(
                    {
                        "issue_id": "ISSUE.SAFETY.INSUFFICIENT_HEADROOM",
                        "severity": 60,
                        "confidence": 0.85,
                        "target": target,
                        "evidence": evidence,
                    }
                )

        return issues
