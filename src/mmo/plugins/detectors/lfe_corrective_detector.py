from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping

from mmo.core.lfe_corrective import stem_has_explicit_lfe
from mmo.plugins.interfaces import DetectorPlugin, Issue

_OUT_OF_BAND_THRESHOLD_DB = -40.0
_INFRASONIC_THRESHOLD_DB = -50.0
_MAINS_RATIO_EXCESS_DB = 6.0


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _measurement_index(stem: Mapping[str, Any]) -> dict[str, Any]:
    measurements = stem.get("measurements")
    if not isinstance(measurements, list):
        return {}
    indexed: dict[str, Any] = {}
    for measurement in measurements:
        if not isinstance(measurement, Mapping):
            continue
        evidence_id = _coerce_str(measurement.get("evidence_id")).strip()
        if not evidence_id:
            continue
        indexed[evidence_id] = measurement.get("value")
    return indexed


def _channel_rows(measurements: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_rows = measurements.get("EVID.LFE.CHANNEL_ROWS")
    if isinstance(raw_rows, str) and raw_rows.strip():
        try:
            raw_rows = json.loads(raw_rows)
        except ValueError:
            return []
    if not isinstance(raw_rows, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if isinstance(row, Mapping):
            rows.append(dict(row))
    rows.sort(key=lambda row: int(_coerce_float(row.get("channel_index")) or 0))
    return rows


def _row_max_metric(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [_coerce_float(row.get(field)) for row in rows]
    finite = [value for value in values if value is not None]
    if not finite:
        return None
    return max(finite)


def _target(stem_id: str) -> dict[str, Any]:
    return {
        "scope": "stem",
        "stem_id": stem_id,
        "speaker_id": "SPK.LFE",
    }


def _base_evidence(
    *,
    stem: Mapping[str, Any],
    measurements: Mapping[str, Any],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    file_path = _coerce_str(stem.get("file_path")).strip()
    if file_path:
        evidence.append({"evidence_id": "EVID.FILE.PATH", "value": file_path})
    evidence.append(
        {
            "evidence_id": "EVID.SURROUND.SPEAKER_ID",
            "value": "SPK.LFE",
            "unit_id": "UNIT.NONE",
        }
    )
    channel_rows = measurements.get("EVID.LFE.CHANNEL_ROWS")
    if channel_rows is not None:
        evidence.append(
            {
                "evidence_id": "EVID.LFE.CHANNEL_ROWS",
                "value": channel_rows,
            }
        )
    return evidence


class LfeCorrectiveDetector(DetectorPlugin):
    plugin_id = "PLUGIN.DETECTOR.LFE_CORRECTIVE"

    def detect(self, session: Dict[str, Any], features: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        stems = session.get("stems")
        if not isinstance(stems, list):
            return issues

        for stem in stems:
            if not isinstance(stem, Mapping):
                continue
            stem_id = _coerce_str(stem.get("stem_id")).strip()
            if not stem_id:
                continue
            measurements = _measurement_index(stem)
            channel_rows = _channel_rows(measurements)
            # This detector stays on the explicit-LFE audit lane. It does not
            # invent a corrective path for stems that neither declare LFE
            # routing nor carry LFE audit evidence.
            if (
                not stem_has_explicit_lfe(stem)
                and not any(key.startswith("EVID.LFE.") for key in measurements)
            ):
                continue

            # Carry the measured artifact context through every issue so later
            # approval and render receipts still point back to the audited
            # stem, file path, and channel-row evidence.
            base_evidence = _base_evidence(stem=stem, measurements=measurements)
            # One explicit LFE stem can trip more than one threshold. The
            # detector reports each threshold crossing, but it does not choose
            # which corrective action, if any, is acceptable.

            out_of_band_db = _row_max_metric(channel_rows, "out_of_band_energy_db")
            if out_of_band_db is not None and out_of_band_db > _OUT_OF_BAND_THRESHOLD_DB:
                issues.append(
                    {
                        "issue_id": "ISSUE.LFE.OUT_OF_BAND_HIGH",
                        "severity": 60,
                        "confidence": 0.9,
                        "message": (
                            "LFE carries significant out-of-band energy above the "
                            "intended subwoofer band."
                        ),
                        "target": _target(stem_id),
                        "evidence": base_evidence
                        + [
                            {
                                "evidence_id": "EVID.LFE.OUT_OF_BAND_DB",
                                "value": round(out_of_band_db, 4),
                                "unit_id": "UNIT.DB",
                            }
                        ],
                    }
                )

            infrasonic_db = _row_max_metric(channel_rows, "infrasonic_energy_db")
            if infrasonic_db is not None and infrasonic_db > _INFRASONIC_THRESHOLD_DB:
                issues.append(
                    {
                        "issue_id": "ISSUE.LFE.INFRASONIC_RUMBLE",
                        "severity": 55,
                        "confidence": 0.85,
                        "message": (
                            "LFE carries infrasonic rumble below the intended "
                            "playback floor."
                        ),
                        "target": _target(stem_id),
                        "evidence": base_evidence
                        + [
                            {
                                "evidence_id": "EVID.LFE.INFRASONIC_DB",
                                "value": round(infrasonic_db, 4),
                                "unit_id": "UNIT.DB",
                            }
                        ],
                    }
                )

            mains_ratio_db = _row_max_metric(channel_rows, "lfe_to_mains_ratio_db")
            if mains_ratio_db is not None and mains_ratio_db > _MAINS_RATIO_EXCESS_DB:
                issues.append(
                    {
                        "issue_id": "ISSUE.LFE.MAINS_RATIO_EXCESS",
                        "severity": 58,
                        "confidence": 0.82,
                        "message": (
                            "LFE carries an excessive share of the low-band energy "
                            "relative to the mains."
                        ),
                        "target": _target(stem_id),
                        "evidence": base_evidence
                        + [
                            {
                                "evidence_id": "EVID.LFE.MAINS_RATIO_DB",
                                "value": round(mains_ratio_db, 4),
                                "unit_id": "UNIT.DB",
                            }
                        ],
                    }
                )

        return issues
