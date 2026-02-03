from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from mmo.dsp.channel_layout import (
    channel_positions_from_mask,
    lufs_weighting_order_and_mode,
    parse_ffmpeg_layout_to_positions,
)
from mmo.dsp.backends.ffprobe_meta import find_ffprobe


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
    codec_name = stem.get("codec_name")
    if isinstance(codec_name, str) and codec_name:
        evidence.append({"evidence_id": "EVID.FILE.CODEC", "value": codec_name})
    return evidence


def validate_session(
    session: Dict[str, Any], duration_tolerance_s: float = 1e-3, *, strict: bool = False
) -> List[Dict[str, Any]]:
    stems = session.get("stems", [])
    wav_exts = {".wav", ".wave"}
    lossy_exts = {".mp3", ".aac", ".ogg", ".opus"}
    unsupported_exts: set[str] = set()
    lossy_message = (
        "Lossy codecs remove audio detail and add artifacts (pre-echo/smearing, "
        "bandwidth loss). Processing like EQ/compression/saturation can amplify "
        "them. Re-export stems lossless (WAV/FLAC/WavPack) from the source session."
    )

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

    ffprobe_available = find_ffprobe() is not None

    for stem in stems:
        stem_id = stem.get("stem_id")
        target = {"scope": "stem", "stem_id": stem_id} if stem_id else {"scope": "session"}
        file_path = stem.get("file_path")
        ext = Path(file_path).suffix.lower() if file_path else ""

        if ext == ".m4a":
            codec = stem.get("codec_name")
            codec = codec.lower() if isinstance(codec, str) else ""
            if codec in {"aac", "mp4a"}:
                evidence = _evidence_file(stem)
                evidence.append(
                    {
                        "evidence_id": "EVID.VALIDATION.LOSSY_REASON",
                        "value": (
                            "AAC-in-M4A is lossy; codec artifacts can be amplified by "
                            "EQ/comp/saturation. Re-export stems losslessly "
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
                        "message": lossy_message,
                    }
                )
            else:
                issues.append(
                    {
                        "issue_id": "ISSUE.VALIDATION.UNSUPPORTED_AUDIO_FORMAT",
                        "severity": 90 if strict else 60,
                        "confidence": 1.0,
                        "target": target,
                        "evidence": _evidence_file(stem),
                        "message": (
                            "ALAC-in-M4A is lossless but not supported yet; export "
                            "as WAV (PCM) for now."
                            if codec == "alac"
                            else "M4A container detected but codec is unknown; export as WAV (PCM) for now."
                        ),
                    }
                )
        elif ext in lossy_exts:
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
                    "message": lossy_message,
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

        if ext in {".flac", ".wv", ".aif", ".aiff"}:
            channel_count_val = stem.get("channel_count")
            if channel_count_val is None:
                channel_count_val = stem.get("channels")
            required_values = [
                channel_count_val,
                stem.get("sample_rate_hz"),
                stem.get("duration_s"),
            ]
            if any(not isinstance(value, (int, float)) for value in required_values):
                evidence = _evidence_file(stem)
                if not ffprobe_available:
                    evidence.extend(
                        [
                            {
                                "evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP",
                                "value": "ffprobe",
                            },
                            {
                                "evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP_HINT",
                                "value": "Install FFmpeg (ffprobe) or set MMO_FFPROBE_PATH",
                            },
                        ]
                    )
                    issues.append(
                        {
                            "issue_id": "ISSUE.VALIDATION.OPTIONAL_DEP_MISSING",
                            "severity": 40 if not strict else 55,
                            "confidence": 1.0,
                            "target": target,
                            "evidence": evidence,
                            "message": "Missing ffprobe metadata for lossless stem; install FFmpeg to decode.",
                        }
                    )
                else:
                    issues.append(
                        {
                            "issue_id": "ISSUE.VALIDATION.DECODE_ERROR",
                            "severity": 90,
                            "confidence": 1.0,
                            "target": target,
                            "evidence": evidence,
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

        # --------------------------------------------
        # Channel layout ambiguity validator (warn-only)
        # --------------------------------------------
        channels_val = stem.get("channel_count")
        if channels_val is None:
            channels_val = stem.get("channels")

        try:
            channels = int(channels_val) if isinstance(channels_val, (int, float)) else None
        except (TypeError, ValueError):
            channels = None

        if channels is not None and channels >= 3:
            wav_mask = stem.get("wav_channel_mask")
            wav_mask_int = wav_mask if isinstance(wav_mask, int) else None
            layout = stem.get("channel_layout")
            layout_str = layout if isinstance(layout, str) and layout.strip() else None

            mask_positions, mask_detail = channel_positions_from_mask(wav_mask_int, channels)

            layout_positions = None
            layout_detail = None
            if layout_str is not None:
                layout_positions, layout_detail = parse_ffmpeg_layout_to_positions(
                    layout_str, channels
                )

            ambiguous_reasons: List[str] = []
            if mask_detail in ("mask_trimmed", "mask_underspecified"):
                ambiguous_reasons.append(mask_detail)
            if layout_detail in (
                "layout_trimmed",
                "layout_list_trimmed",
                "layout_list_underspecified",
            ):
                ambiguous_reasons.append(layout_detail)
            if layout_str == "6.1" and wav_mask_int is None:
                ambiguous_reasons.append("layout_61_ambiguous_without_mask")

            if mask_positions is not None and layout_positions is not None:
                if mask_positions != layout_positions:
                    ambiguous_reasons.append("mask_layout_conflict")

            if ambiguous_reasons:
                evidence = _evidence_file(stem)
                evidence.append(
                    {
                        "evidence_id": "EVID.TRACK.CHANNELS",
                        "value": channels,
                        "unit_id": "UNIT.COUNT",
                    }
                )
                if wav_mask_int is not None:
                    evidence.append(
                        {
                            "evidence_id": "EVID.FILE.WAV_CHANNEL_MASK",
                            "value": wav_mask_int,
                        }
                    )
                if layout_str is not None:
                    evidence.append(
                        {
                            "evidence_id": "EVID.FILE.CHANNEL_LAYOUT",
                            "value": layout_str,
                        }
                    )

                _, order_csv, mode_str = lufs_weighting_order_and_mode(
                    channels, wav_mask_int, layout_str
                )
                evidence.append(
                    {
                        "evidence_id": "EVID.METER.LUFS_WEIGHTING_MODE",
                        "value": mode_str,
                    }
                )
                evidence.append(
                    {
                        "evidence_id": "EVID.METER.LUFS_WEIGHTING_ORDER",
                        "value": order_csv,
                    }
                )

                evidence.append(
                    {
                        "evidence_id": "EVID.VALIDATION.CHANNEL_LAYOUT_REASON",
                        "value": (
                            "Channel layout ambiguity: "
                            + ", ".join(sorted(set(ambiguous_reasons)))
                        ),
                    }
                )

                issues.append(
                    {
                        "issue_id": "ISSUE.VALIDATION.CHANNEL_LAYOUT_AMBIGUOUS",
                        "severity": 40 if not strict else 55,
                        "confidence": 1.0
                        if (
                            "mask_layout_conflict" in ambiguous_reasons
                            or "mask_trimmed" in ambiguous_reasons
                            or "layout_trimmed" in ambiguous_reasons
                        )
                        else 0.8,
                        "target": target,
                        "evidence": evidence,
                        "message": (
                            "Channel metadata is ambiguous (mask/layout mismatch or "
                            "truncated/underspecified). Meters will fall back safely, "
                            "but results may be less reliable. Prefer stems with a "
                            "correct WAV channel mask or a precise ffprobe channel_layout."
                        ),
                    }
                )

    return issues
