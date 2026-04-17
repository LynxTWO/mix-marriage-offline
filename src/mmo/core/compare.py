from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmo.core.vibe_signals import derive_vibe_signals

COMPARE_REPORT_SCHEMA_VERSION = "0.1.0"
_TRANSLATION_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
_OUTPUT_FORMAT_ORDER = {
    "wav": 0,
    "flac": 1,
    "wv": 2,
    "aiff": 3,
    "alac": 4,
}
_DOWNMIX_QA_DELTA_EVIDENCE_IDS = {
    "lufs_delta": "EVID.DOWNMIX.QA.LUFS_DELTA",
    "true_peak_delta": "EVID.DOWNMIX.QA.TRUE_PEAK_DELTA",
    "corr_delta": "EVID.DOWNMIX.QA.CORR_DELTA",
}
_COMPARE_LOUDNESS_METHODS = (
    {
        "label": "render_qa mean integrated LUFS",
        "method_id": "COMPARE.LOUDNESS_MATCH.RENDER_QA.MEAN_INTEGRATED_LUFS",
        "metric_key": "integrated_lufs",
        "unit_id": "UNIT.LUFS",
    },
    {
        "label": "render_qa mean RMS dBFS",
        "method_id": "COMPARE.LOUDNESS_MATCH.RENDER_QA.MEAN_RMS_DBFS",
        "metric_key": "rms_dbfs",
        "unit_id": "UNIT.DBFS",
    },
)
_COMPARE_LOUDNESS_UNAVAILABLE_METHOD_ID = "COMPARE.LOUDNESS_MATCH.UNAVAILABLE"
_COMPARE_LOUDNESS_LARGE_DELTA_WARN_DB = 4.0


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON from {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object: {path}")
    return payload


def _compare_input_hint(path: Path) -> str:
    return (
        "Compare inputs must be either a workspace folder that already contains "
        f"`report.json`, or the `report.json` file itself. Received: {path}"
    )


def load_report_from_path_or_dir(path: Path | str) -> tuple[dict[str, Any], Path]:
    candidate = Path(path)
    if candidate.is_dir():
        # Caller passed a path that looks like a file (e.g. ends in .json) but is
        # actually a directory — give a clear message rather than a confusing
        # "could not find report.json inside report.json/".
        if candidate.suffix.lower() == ".json":
            raise ValueError(
                "MMO expected a `report.json` file but received a folder path instead. "
                f"{_compare_input_hint(candidate)}"
            )
        # Compare treats a workspace folder and its canonical report.json as the
        # same input so callers do not have to care which form they already have.
        report_path = candidate / "report.json"
        if not report_path.exists():
            raise ValueError(
                "MMO could not find `report.json` in that compare folder. "
                f"{_compare_input_hint(candidate)}"
            )
    else:
        report_path = candidate

    if not report_path.exists():
        raise ValueError(
            "MMO could not find that compare input on disk. "
            f"{_compare_input_hint(report_path)}"
        )
    if report_path.is_dir():
        raise ValueError(
            "MMO expected a `report.json` file but received a folder path instead. "
            f"{_compare_input_hint(report_path)}"
        )

    report = _load_json_object(report_path, label="Report")
    return report, report_path.resolve()


def default_label_for_compare_input(path: Path | str, *, report_path: Path) -> str:
    input_path = Path(path)
    if input_path.is_dir():
        label = input_path.resolve().name
    else:
        label = input_path.resolve().stem
        if label.lower() == "report":
            label = report_path.parent.name
    if label:
        return label
    fallback = report_path.parent.name or report_path.stem
    return fallback or "report"


def _report_profile_id(report: dict[str, Any]) -> str:
    run_config = _coerce_dict(report.get("run_config"))
    profile_id = _coerce_str(run_config.get("profile_id")).strip()
    if profile_id:
        return profile_id
    return _coerce_str(report.get("profile_id")).strip()


def _report_preset_id(report: dict[str, Any]) -> str:
    run_config = _coerce_dict(report.get("run_config"))
    preset_id = _coerce_str(run_config.get("preset_id")).strip()
    if preset_id:
        return preset_id
    return _coerce_str(report.get("preset_id")).strip()


def _report_meters(report: dict[str, Any]) -> str:
    run_config = _coerce_dict(report.get("run_config"))
    return _coerce_str(run_config.get("meters")).strip()


def _normalize_output_format(value: Any) -> str:
    normalized = _coerce_str(value).strip().lower()
    if not normalized:
        return ""
    return normalized


def _read_optional_json_object(path: Path) -> dict[str, Any]:
    # Compare uses side artifacts only when they are readable and shaped like a
    # JSON object. Missing or broken extras should degrade the comparison, not
    # block the whole report load.
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _manifest_output_formats(report_path: Path) -> set[str]:
    report_dir = report_path.parent
    formats: set[str] = set()
    for manifest_name in ("render_manifest.json", "apply_manifest.json"):
        manifest = _read_optional_json_object(report_dir / manifest_name)
        for renderer_manifest in _coerce_dict_list(manifest.get("renderer_manifests")):
            for output in _coerce_dict_list(renderer_manifest.get("outputs")):
                output_format = _normalize_output_format(output.get("format"))
                if output_format:
                    formats.add(output_format)
        for deliverable in _coerce_dict_list(manifest.get("deliverables")):
            for fmt in deliverable.get("formats", []):
                output_format = _normalize_output_format(fmt)
                if output_format:
                    formats.add(output_format)
    return formats


def _report_output_formats(report: dict[str, Any], *, report_path: Path) -> list[str]:
    run_config = _coerce_dict(report.get("run_config"))
    formats: set[str] = set()

    for section_name in ("render", "apply"):
        section = _coerce_dict(run_config.get(section_name))
        for item in section.get("output_formats", []):
            output_format = _normalize_output_format(item)
            if output_format:
                formats.add(output_format)

    for item in run_config.get("output_formats", []):
        output_format = _normalize_output_format(item)
        if output_format:
            formats.add(output_format)

    # Render/apply manifests capture what actually made it into side artifacts.
    # Compare keeps both sources so config drift and emit drift are visible.
    formats.update(_manifest_output_formats(report_path))
    return sorted(formats, key=lambda item: (_OUTPUT_FORMAT_ORDER.get(item, 999), item))


def _round_number(value: float | None, *, digits: int) -> float | None:
    if value is None:
        return None
    rounded = round(value, digits)
    if rounded == -0.0:
        return 0.0
    return rounded


def _compare_render_qa_path(report_path: Path) -> Path:
    return report_path.parent / "render_qa.json"


def _mean_render_qa_metric(render_qa: dict[str, Any], metric_key: str) -> float | None:
    values: list[float] = []
    for job in _coerce_dict_list(render_qa.get("jobs")):
        for output in _coerce_dict_list(job.get("outputs")):
            metrics = _coerce_dict(output.get("metrics"))
            value = _coerce_number(metrics.get(metric_key))
            if value is not None:
                values.append(value)
    if not values:
        return None
    return sum(values) / len(values)


def _build_loudness_match(report_path_a: Path, report_path_b: Path) -> dict[str, Any]:
    qa_path_a = _compare_render_qa_path(report_path_a)
    qa_path_b = _compare_render_qa_path(report_path_b)
    qa_a = _read_optional_json_object(qa_path_a)
    qa_b = _read_optional_json_object(qa_path_b)
    source_artifacts = {
        "a_render_qa_path": qa_path_a.resolve().as_posix(),
        "b_render_qa_path": qa_path_b.resolve().as_posix(),
    }

    for method in _COMPARE_LOUDNESS_METHODS:
        measurement_a = _mean_render_qa_metric(qa_a, method["metric_key"])
        measurement_b = _mean_render_qa_metric(qa_b, method["metric_key"])
        # Fair-listen only makes sense when both sides expose the same meter
        # family. Keep searching rather than guessing from partial evidence.
        if measurement_a is None or measurement_b is None:
            continue
        compensation_db = _round_number(measurement_a - measurement_b, digits=1)
        rounded_a = _round_number(measurement_a, digits=3)
        rounded_b = _round_number(measurement_b, digits=3)
        return {
            "status": "matched",
            "enabled_by_default": True,
            "evaluation_only": True,
            "compensated_side": "b",
            "method_id": method["method_id"],
            "measurement_unit_id": method["unit_id"],
            "measurement_a": rounded_a,
            "measurement_b": rounded_b,
            "compensation_db": compensation_db,
            "source_artifacts": source_artifacts,
            "details": (
                "Default fair-listen applies "
                f"{_format_signed(compensation_db, precision=1)} dB to B using "
                f"{method['label']} "
                f"(A={_format_number(rounded_a, precision=2)}, "
                f"B={_format_number(rounded_b, precision=2)})."
            ),
        }

    # Missing paired QA artifacts should stay visible in the compare output.
    # Hard-failing here would hide all the other comparison signals.
    return {
        "status": "unavailable",
        "enabled_by_default": False,
        "evaluation_only": True,
        "compensated_side": "b",
        "method_id": _COMPARE_LOUDNESS_UNAVAILABLE_METHOD_ID,
        "measurement_unit_id": "UNIT.NONE",
        "measurement_a": None,
        "measurement_b": None,
        "compensation_db": 0.0,
        "source_artifacts": source_artifacts,
        "details": (
            "Fair-listen compensation was unavailable because paired render_qa "
            "integrated LUFS or RMS metrics were not found for both sides."
        ),
    }


def _first_measurement_value(downmix_qa: dict[str, Any], *, evidence_id: str) -> float | None:
    measurements = downmix_qa.get("measurements")
    if not isinstance(measurements, list):
        return None
    for measurement in measurements:
        if not isinstance(measurement, dict):
            continue
        if measurement.get("evidence_id") != evidence_id:
            continue
        value = _coerce_number(measurement.get("value"))
        if value is not None:
            return value
    return None


def _downmix_qa_metrics(report: dict[str, Any]) -> dict[str, float | None] | None:
    downmix_qa = report.get("downmix_qa")
    if not isinstance(downmix_qa, dict):
        return None
    return {
        metric_key: _first_measurement_value(downmix_qa, evidence_id=evidence_id)
        for metric_key, evidence_id in _DOWNMIX_QA_DELTA_EVIDENCE_IDS.items()
    }


def _mix_complexity_metrics(report: dict[str, Any]) -> dict[str, float | None] | None:
    mix_complexity = report.get("mix_complexity")
    if not isinstance(mix_complexity, dict):
        return None

    masking_pairs_count = _coerce_number(mix_complexity.get("top_masking_pairs_count"))
    if masking_pairs_count is None:
        top_pairs = mix_complexity.get("top_masking_pairs")
        if isinstance(top_pairs, list):
            masking_pairs_count = float(len(_coerce_dict_list(top_pairs)))

    return {
        "density_mean": _coerce_number(mix_complexity.get("density_mean")),
        "density_peak": _coerce_number(mix_complexity.get("density_peak")),
        "masking_pairs_count": masking_pairs_count,
    }


def _extreme_count(report: dict[str, Any]) -> int:
    count = 0
    for recommendation in _coerce_dict_list(report.get("recommendations")):
        if recommendation.get("extreme") is True:
            count += 1
    return count


def _translation_risk(report: dict[str, Any]) -> str:
    vibe_signals = _coerce_dict(report.get("vibe_signals"))
    from_report = _coerce_str(vibe_signals.get("translation_risk")).strip().lower()
    if from_report in _TRANSLATION_RISK_ORDER:
        return from_report

    derived = _coerce_dict(derive_vibe_signals(report))
    from_derived = _coerce_str(derived.get("translation_risk")).strip().lower()
    if from_derived in _TRANSLATION_RISK_ORDER:
        return from_derived
    return ""


def _numeric_diff(value_a: float | None, value_b: float | None) -> dict[str, float | None]:
    delta: float | None = None
    if value_a is not None and value_b is not None:
        delta = value_b - value_a
    return {"a": value_a, "b": value_b, "delta": delta}


def _format_number(value: float | None, *, precision: int) -> str:
    if value is None:
        return "n/a"
    rendered = f"{value:.{precision}f}".rstrip("0").rstrip(".")
    if rendered == "-0":
        return "0"
    return rendered


def _format_signed(value: float | None, *, precision: int) -> str:
    if value is None:
        return "n/a"
    rendered = f"{value:+.{precision}f}".rstrip("0").rstrip(".")
    if rendered in {"+0", "-0"}:
        return "0"
    return rendered


def _has_change(value: float | None) -> bool:
    if value is None:
        return False
    return abs(value) > 1e-12


def _risk_shift(risk_a: str, risk_b: str) -> int:
    if risk_a not in _TRANSLATION_RISK_ORDER or risk_b not in _TRANSLATION_RISK_ORDER:
        return 0
    return _TRANSLATION_RISK_ORDER[risk_b] - _TRANSLATION_RISK_ORDER[risk_a]


def _format_list(values: list[str]) -> str:
    if not values:
        return "<none>"
    return ",".join(values)


def _compare_side_summary(
    *,
    label: str,
    report_path: Path,
    report: dict[str, Any],
) -> dict[str, str]:
    return {
        "label": label,
        "report_path": report_path.resolve().as_posix(),
        "preset_id": _report_preset_id(report),
        "profile_id": _report_profile_id(report),
    }


def _build_notes_and_warnings(
    diffs: dict[str, Any],
    *,
    loudness_match: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    warnings: list[str] = []
    loudness_notes: list[str] = []
    loudness_warnings: list[str] = []

    if isinstance(loudness_match, dict):
        loudness_status = _coerce_str(loudness_match.get("status")).strip().lower()
        loudness_details = _coerce_str(loudness_match.get("details")).strip()
        compensation_db = _coerce_number(loudness_match.get("compensation_db"))
        if loudness_status == "matched":
            if loudness_details:
                loudness_notes.append(loudness_details)
            if (
                compensation_db is not None
                and abs(compensation_db) >= _COMPARE_LOUDNESS_LARGE_DELTA_WARN_DB
            ):
                loudness_warnings.append(
                    "Fair-listen needed a large compensation on B "
                    f"({_format_signed(compensation_db, precision=1)} dB); "
                    "double-check both raw and matched playback before deciding."
                )
        elif loudness_details:
            loudness_warnings.append(loudness_details)

    profile_diff = _coerce_dict(diffs.get("profile_id"))
    profile_a = _coerce_str(profile_diff.get("a")).strip()
    profile_b = _coerce_str(profile_diff.get("b")).strip()
    if profile_a != profile_b:
        notes.append(f"Profile changed: {profile_a or '<none>'} -> {profile_b or '<none>'}.")

    preset_diff = _coerce_dict(diffs.get("preset_id"))
    preset_a = _coerce_str(preset_diff.get("a")).strip()
    preset_b = _coerce_str(preset_diff.get("b")).strip()
    if preset_a != preset_b:
        notes.append(f"Preset changed: {preset_a or '<none>'} -> {preset_b or '<none>'}.")

    meters_diff = _coerce_dict(diffs.get("meters"))
    meters_a = _coerce_str(meters_diff.get("a")).strip()
    meters_b = _coerce_str(meters_diff.get("b")).strip()
    if meters_a != meters_b:
        notes.append(f"Meters changed: {meters_a or '<none>'} -> {meters_b or '<none>'}.")

    output_formats_diff = _coerce_dict(diffs.get("output_formats"))
    output_formats_a = [
        _coerce_str(item)
        for item in output_formats_diff.get("a", [])
        if isinstance(item, str) and item.strip()
    ]
    output_formats_b = [
        _coerce_str(item)
        for item in output_formats_diff.get("b", [])
        if isinstance(item, str) and item.strip()
    ]
    if output_formats_a != output_formats_b:
        notes.append(
            "Output formats changed: "
            f"A={_format_list(output_formats_a)}; B={_format_list(output_formats_b)}."
        )

    metrics = _coerce_dict(diffs.get("metrics"))
    downmix_qa = metrics.get("downmix_qa")
    if isinstance(downmix_qa, dict):
        downmix_rows = [
            ("lufs_delta", "Downmix QA LUFS delta", 2),
            ("true_peak_delta", "Downmix QA true peak delta", 2),
            ("corr_delta", "Downmix QA correlation delta", 3),
        ]
        for key, label, precision in downmix_rows:
            value = _coerce_dict(downmix_qa.get(key))
            metric_delta = _coerce_number(value.get("delta"))
            if not _has_change(metric_delta):
                continue
            notes.append(
                f"{label} shifted by {_format_signed(metric_delta, precision=precision)} "
                f"(A={_format_number(_coerce_number(value.get('a')), precision=precision)}, "
                f"B={_format_number(_coerce_number(value.get('b')), precision=precision)})."
            )
    else:
        # Keep "could not compare" separate from a zero delta so follow-up
        # tooling can tell absence of evidence from an actual match.
        warnings.append(
            "Downmix QA metrics missing in one or both reports; LUFS/true peak/correlation "
            "deltas were not compared."
        )

    mix_complexity = metrics.get("mix_complexity")
    if isinstance(mix_complexity, dict):
        mix_rows = [
            ("density_mean", "Density mean", 2),
            ("density_peak", "Density peak", 2),
            ("masking_pairs_count", "Masking pairs count", 0),
        ]
        for key, label, precision in mix_rows:
            value = _coerce_dict(mix_complexity.get(key))
            metric_delta = _coerce_number(value.get("delta"))
            if not _has_change(metric_delta):
                continue
            notes.append(
                f"{label} shifted by {_format_signed(metric_delta, precision=precision)} "
                f"(A={_format_number(_coerce_number(value.get('a')), precision=precision)}, "
                f"B={_format_number(_coerce_number(value.get('b')), precision=precision)})."
            )
    else:
        warnings.append(
            "Mix complexity metrics missing in one or both reports; density and masking "
            "changes were not compared."
        )

    change_flags = _coerce_dict(metrics.get("change_flags"))
    extreme = _coerce_dict(change_flags.get("extreme_count"))
    extreme_delta = _coerce_number(extreme.get("delta"))
    extreme_a = _coerce_number(extreme.get("a"))
    extreme_b = _coerce_number(extreme.get("b"))
    if _has_change(extreme_delta):
        notes.append(
            "Extreme recommendation count changed by "
            f"{_format_signed(extreme_delta, precision=0)} "
            f"(A={_format_number(extreme_a, precision=0)}, "
            f"B={_format_number(extreme_b, precision=0)})."
        )
        if extreme_delta > 0:
            warnings.append(
                "B contains more extreme recommendations than A; re-check those moves at "
                "matched loudness before deciding."
            )

    translation = _coerce_dict(change_flags.get("translation_risk"))
    translation_a = _coerce_str(translation.get("a")).strip().lower()
    translation_b = _coerce_str(translation.get("b")).strip().lower()
    translation_shift = int(_coerce_number(translation.get("shift")) or 0)
    if translation_shift > 0:
        notes.append(
            f"Translation risk moved upward: {translation_a or 'unknown'} -> "
            f"{translation_b or 'unknown'}."
        )
        warnings.append(
            "Translation risk increased from A to B; verify on small speakers, headphones, "
            "and mono before choosing."
        )
    elif translation_shift < 0:
        notes.append(
            f"Translation risk moved downward: {translation_a or 'unknown'} -> "
            f"{translation_b or 'unknown'}."
        )
    elif translation_a and translation_b:
        notes.append(f"Translation risk stayed {translation_b}.")

    if not notes:
        notes.append("No tracked differences were detected between A and B.")
    return [*loudness_notes, *notes], [*loudness_warnings, *warnings]


def build_compare_report(
    report_a: dict[str, Any],
    report_b: dict[str, Any],
    *,
    label_a: str,
    label_b: str,
    report_path_a: Path,
    report_path_b: Path,
) -> dict[str, Any]:
    profile_id_a = _report_profile_id(report_a)
    profile_id_b = _report_profile_id(report_b)
    preset_id_a = _report_preset_id(report_a)
    preset_id_b = _report_preset_id(report_b)
    meters_a = _report_meters(report_a)
    meters_b = _report_meters(report_b)
    output_formats_a = _report_output_formats(report_a, report_path=report_path_a)
    output_formats_b = _report_output_formats(report_b, report_path=report_path_b)

    downmix_qa_a = _downmix_qa_metrics(report_a)
    downmix_qa_b = _downmix_qa_metrics(report_b)
    downmix_qa_diff: dict[str, dict[str, float | None]] | None = None
    if downmix_qa_a is not None and downmix_qa_b is not None:
        downmix_qa_diff = {
            key: _numeric_diff(downmix_qa_a.get(key), downmix_qa_b.get(key))
            for key in _DOWNMIX_QA_DELTA_EVIDENCE_IDS
        }

    mix_complexity_a = _mix_complexity_metrics(report_a)
    mix_complexity_b = _mix_complexity_metrics(report_b)
    mix_complexity_diff: dict[str, dict[str, float | None]] | None = None
    if mix_complexity_a is not None and mix_complexity_b is not None:
        mix_complexity_diff = {
            key: _numeric_diff(mix_complexity_a.get(key), mix_complexity_b.get(key))
            for key in ("density_mean", "density_peak", "masking_pairs_count")
        }

    extreme_count_a = _extreme_count(report_a)
    extreme_count_b = _extreme_count(report_b)
    translation_risk_a = _translation_risk(report_a)
    translation_risk_b = _translation_risk(report_b)
    translation_shift = _risk_shift(translation_risk_a, translation_risk_b)
    loudness_match = _build_loudness_match(report_path_a, report_path_b)

    payload: dict[str, Any] = {
        "schema_version": COMPARE_REPORT_SCHEMA_VERSION,
        "a": _compare_side_summary(
            label=label_a,
            report_path=report_path_a,
            report=report_a,
        ),
        "b": _compare_side_summary(
            label=label_b,
            report_path=report_path_b,
            report=report_b,
        ),
        "diffs": {
            "profile_id": {"a": profile_id_a, "b": profile_id_b},
            "preset_id": {"a": preset_id_a, "b": preset_id_b},
            "meters": {"a": meters_a, "b": meters_b},
            "output_formats": {"a": output_formats_a, "b": output_formats_b},
            "metrics": {
                "downmix_qa": downmix_qa_diff,
                "mix_complexity": mix_complexity_diff,
                "change_flags": {
                    "extreme_count": {
                        "a": float(extreme_count_a),
                        "b": float(extreme_count_b),
                        "delta": float(extreme_count_b - extreme_count_a),
                    },
                    "translation_risk": {
                        "a": translation_risk_a,
                        "b": translation_risk_b,
                        "shift": translation_shift,
                    },
                },
            },
        },
        "loudness_match": loudness_match,
        "notes": [],
        "warnings": [],
    }
    # Compare builds notes after the raw diffs so the prose can reflect
    # unavailable evidence without rewriting the machine-readable payload.
    notes, warnings = _build_notes_and_warnings(
        _coerce_dict(payload.get("diffs")),
        loudness_match=loudness_match,
    )
    payload["notes"] = notes
    payload["warnings"] = warnings
    return payload
