from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


def _mode_with_max_tiebreak(values: List[int]) -> Optional[int]:
    if not values:
        return None
    counts = Counter(values)
    max_count = max(counts.values())
    candidates = [value for value, count in counts.items() if count == max_count]
    return max(candidates)


def _evidence_file(stem: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    file_path = stem.get("file_path")
    ext = ""
    if file_path:
        evidence.append({"evidence_id": "EVID.FILE.PATH", "value": file_path})
        suffix = Path(file_path).suffix.lower()
        if suffix:
            ext = suffix
            evidence.append({"evidence_id": "EVID.FILE.EXT", "value": suffix})
            evidence.append(
                {"evidence_id": "EVID.FILE.FORMAT", "value": suffix.lstrip(".")}
            )
    sha256 = stem.get("sha256")
    if sha256:
        evidence.append({"evidence_id": "EVID.FILE.HASH.SHA256", "value": sha256})
    return evidence


def validate_session(
    session: Dict[str, Any], duration_tolerance_s: float = 1e-3, *, strict: bool = False
) -> List[Dict[str, Any]]:
    stems = session.get("stems", [])
    wav_exts = {".wav", ".wave"}
    lossy_exts = {".mp3", ".aac", ".ogg", ".opus"}
    unsupported_exts = {".flac", ".wv", ".aiff", ".aif", ".m4a"}

    sample_rates = [
        int(stem["sample_rate_hz"])
        for stem in stems
        if isinstance(stem.get("sample_rate_hz"), (int, float))
    ]
    bit_depths = [
        int(stem.get("bits_per_sample") or stem.get("bit_depth"))
        for stem in stems
        if isinstance(stem.get("bits_per_sample") or stem.get("bit_depth"), (int, float))
    ]
    durations = [
        float(stem["duration_s"])
        for stem in stems
        if isinstance(stem.get("duration_s"), (int, float))
    ]

    expected_sample_rate = _mode_with_max_tiebreak(sample_rates)
    expected_bit_depth = _mode_with_max_tiebreak(bit_depths)
    expected_duration = max(durations) if durations else None

    issues: List[Dict[str, Any]] = []

    for stem in stems:
        stem_id = stem.get("stem_id")
        target = {"scope": "stem", "stem_id": stem_id} if stem_id else {"scope": "session"}
        file_path = stem.get("file_path")
        ext = Path(file_path).suffix.lower() if file_path else ""

        if ext in lossy_exts:
            evidence = _evidence_file(stem)
            evidence.append(
                {
                    "evidence_id": "EVID.VALIDATION.LOSSY_REASON",
                    "value": (
                        "Lossy codecs discard audio detail; EQ/comp/saturation can "
                        "amplify codec artifacts. Re-export stems losslessly "
                        "(WAV/FLAC/WavPack), aligned and same length."
                    ),
                }
            )
            issues.append(
                {
                    "issue_id": "ISSUE.VALIDATION.LOSSY_STEMS_DETECTED",
                    "severity": 90 if strict else 60,
                    "confidence": 1.0,
                    "target": target,
                    "evidence": evidence,
                }
            )

        if ext in unsupported_exts:
            issues.append(
                {
                    "issue_id": "ISSUE.VALIDATION.UNSUPPORTED_AUDIO_FORMAT",
                    "severity": 90 if strict else 60,
                    "confidence": 1.0,
                    "target": target,
                    "evidence": _evidence_file(stem),
                    "message": "Format detected but not supported yet; export as WAV (PCM) for now.",
                }
            )

        if ext in wav_exts:
            required_values = [
                stem.get("channel_count"),
                stem.get("sample_rate_hz"),
                stem.get("duration_s"),
                stem.get("bits_per_sample") or stem.get("bit_depth"),
            ]
            if any(not isinstance(value, (int, float)) for value in required_values):
                issues.append(
                    {
                        "issue_id": "ISSUE.VALIDATION.DECODE_ERROR",
                        "severity": 90,
                        "confidence": 1.0,
                        "target": target,
                        "evidence": _evidence_file(stem),
                    }
                )

        if expected_sample_rate is not None:
            stem_sample_rate = stem.get("sample_rate_hz")
            if isinstance(stem_sample_rate, (int, float)) and int(stem_sample_rate) != expected_sample_rate:
                evidence = [
                    {
                        "evidence_id": "EVID.SESSION.SAMPLE_RATE_HZ",
                        "value": expected_sample_rate,
                        "unit_id": "UNIT.HZ",
                    }
                ]
                evidence.extend(_evidence_file(stem))
                issues.append(
                    {
                        "issue_id": "ISSUE.VALIDATION.SAMPLE_RATE_MISMATCH",
                        "severity": 90,
                        "confidence": 1.0,
                        "target": target,
                        "evidence": evidence,
                    }
                )

        if expected_bit_depth is not None:
            stem_bit_depth = stem.get("bits_per_sample") or stem.get("bit_depth")
            if isinstance(stem_bit_depth, (int, float)) and int(stem_bit_depth) != expected_bit_depth:
                evidence = [
                    {
                        "evidence_id": "EVID.SESSION.BIT_DEPTH",
                        "value": expected_bit_depth,
                        "unit_id": "UNIT.BIT",
                    }
                ]
                evidence.extend(_evidence_file(stem))
                issues.append(
                    {
                        "issue_id": "ISSUE.VALIDATION.BIT_DEPTH_MISMATCH",
                        "severity": 50,
                        "confidence": 1.0,
                        "target": target,
                        "evidence": evidence,
                    }
                )

        if expected_duration is not None:
            stem_duration = stem.get("duration_s")
            if isinstance(stem_duration, (int, float)) and abs(float(stem_duration) - expected_duration) > duration_tolerance_s:
                evidence = [
                    {
                        "evidence_id": "EVID.SESSION.DURATION_S",
                        "value": expected_duration,
                        "unit_id": "UNIT.S",
                    }
                ]
                evidence.extend(_evidence_file(stem))
                issues.append(
                    {
                        "issue_id": "ISSUE.VALIDATION.DURATION_MISMATCH",
                        "severity": 90,
                        "confidence": 1.0,
                        "target": target,
                        "evidence": evidence,
                    }
                )

    return issues
