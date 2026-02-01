"""Scan a stems directory and emit a deterministic MMO report."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None

try:
    import jsonschema
except ImportError:  # pragma: no cover - environment issue
    jsonschema = None

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mmo import __version__ as engine_version  # noqa: E402
from mmo.core.session import build_session_from_stems_dir  # noqa: E402
from mmo.core.validators import validate_session  # noqa: E402
from mmo.dsp.decoders import detect_format_from_path  # noqa: E402
from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd  # noqa: E402
from mmo.dsp.backends.ffmpeg_decode import iter_ffmpeg_float64_samples  # noqa: E402
from mmo.dsp.meters import (  # noqa: E402
    compute_basic_stats_from_float64,
    compute_clip_sample_count_wav,
    compute_crest_factor_db_wav,
    compute_dc_offset_wav,
    compute_rms_dbfs_wav,
    compute_sample_peak_dbfs_wav,
)
from mmo.dsp.stereo import compute_stereo_correlation_wav  # noqa: E402


def upsert_measurement(stem: Dict[str, Any], evidence_id: str, value: Any, unit_id: str) -> None:
    measurements = stem.get("measurements")
    if not isinstance(measurements, list):
        measurements = []
        stem["measurements"] = measurements

    replaced = False
    for measurement in measurements:
        if not isinstance(measurement, dict):
            continue
        if measurement.get("evidence_id") == evidence_id:
            measurement["value"] = value
            measurement["unit_id"] = unit_id
            replaced = True
            break

    if not replaced:
        measurements.append(
            {
                "evidence_id": evidence_id,
                "value": value,
                "unit_id": unit_id,
            }
        )

    measurements.sort(key=lambda item: item.get("evidence_id", ""))


def _load_ontology_version(path: Path) -> str:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed; cannot load ontology version.")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    ontology = data.get("ontology", {}) if isinstance(data, dict) else {}
    version = ontology.get("ontology_version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"Missing ontology_version in {path}")
    return version


def _hash_from_stems(stems: List[Dict[str, Any]]) -> str:
    hashes = [stem.get("sha256", "") for stem in stems]
    joined = "\n".join(hashes)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _validate_schema(schema_path: Path, report: Dict[str, Any]) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is not installed; cannot validate report.")
    with schema_path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(report), key=lambda err: list(err.path))
    if errors:
        messages = "\n".join(f"- {err.message}" for err in errors)
        raise ValueError(f"Report schema validation failed:\n{messages}")


def _add_peak_metrics(session: Dict[str, Any], stems_dir: Path) -> None:
    stems = session.get("stems", [])
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        if "sample_rate_hz" not in stem or "bits_per_sample" not in stem:
            continue
        file_path = stem.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            continue
        stem_path = Path(file_path)
        if not stem_path.is_absolute():
            stem_path = stems_dir / stem_path
        if detect_format_from_path(stem_path) != "wav":
            continue
        try:
            peak_dbfs = compute_sample_peak_dbfs_wav(stem_path)
        except ValueError:
            continue
        metrics = stem.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
            stem["metrics"] = metrics
        metrics["peak_dbfs"] = peak_dbfs
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.SAMPLE_PEAK_DBFS",
            value=peak_dbfs,
            unit_id="UNIT.DBFS",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.PEAK_DBFS",
            value=peak_dbfs,
            unit_id="UNIT.DBFS",
        )


def _add_basic_meter_measurements(
    session: Dict[str, Any], stems_dir: Path
) -> bool:
    missing_ffmpeg = False
    ffmpeg_cmd = None
    stems = session.get("stems", [])
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        file_path = stem.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            continue
        stem_path = Path(file_path)
        if not stem_path.is_absolute():
            stem_path = stems_dir / stem_path
        format_id = detect_format_from_path(stem_path)
        if format_id == "wav":
            if "sample_rate_hz" not in stem or "bits_per_sample" not in stem:
                continue
        elif format_id in {"flac", "wavpack"}:
            if ffmpeg_cmd is None:
                ffmpeg_cmd = resolve_ffmpeg_cmd()
            if ffmpeg_cmd is None:
                missing_ffmpeg = True
                continue

            try:
                (
                    peak,
                    clip_count,
                    dc_offset,
                    rms_dbfs,
                    crest_factor_db,
                ) = compute_basic_stats_from_float64(
                    iter_ffmpeg_float64_samples(stem_path, ffmpeg_cmd)
                )
            except ValueError:
                continue

            if peak <= 0.0:
                peak_dbfs = float("-inf")
            else:
                peak_dbfs = 20.0 * math.log10(peak)

            upsert_measurement(
                stem,
                evidence_id="EVID.METER.SAMPLE_PEAK_DBFS",
                value=peak_dbfs,
                unit_id="UNIT.DBFS",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.METER.PEAK_DBFS",
                value=peak_dbfs,
                unit_id="UNIT.DBFS",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.METER.CLIP_SAMPLE_COUNT",
                value=clip_count,
                unit_id="UNIT.COUNT",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.QUALITY.CLIPPED_SAMPLES_COUNT",
                value=clip_count,
                unit_id="UNIT.COUNT",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.METER.DC_OFFSET",
                value=dc_offset,
                unit_id="UNIT.RATIO",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.QUALITY.DC_OFFSET_PERCENT",
                value=dc_offset * 100.0,
                unit_id="UNIT.PERCENT",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.METER.RMS_DBFS",
                value=rms_dbfs,
                unit_id="UNIT.DBFS",
            )
            upsert_measurement(
                stem,
                evidence_id="EVID.METER.CREST_FACTOR_DB",
                value=crest_factor_db,
                unit_id="UNIT.DB",
            )
            continue
        else:
            continue

        try:
            clip_count = compute_clip_sample_count_wav(stem_path)
            dc_offset = compute_dc_offset_wav(stem_path)
            rms_dbfs = compute_rms_dbfs_wav(stem_path)
            crest_factor_db = compute_crest_factor_db_wav(stem_path)
        except ValueError:
            continue

        upsert_measurement(
            stem,
            evidence_id="EVID.METER.CLIP_SAMPLE_COUNT",
            value=clip_count,
            unit_id="UNIT.COUNT",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.QUALITY.CLIPPED_SAMPLES_COUNT",
            value=clip_count,
            unit_id="UNIT.COUNT",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.DC_OFFSET",
            value=dc_offset,
            unit_id="UNIT.RATIO",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.QUALITY.DC_OFFSET_PERCENT",
            value=dc_offset * 100.0,
            unit_id="UNIT.PERCENT",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.RMS_DBFS",
            value=rms_dbfs,
            unit_id="UNIT.DBFS",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.CREST_FACTOR_DB",
            value=crest_factor_db,
            unit_id="UNIT.DB",
        )

        if stem.get("channel_count") == 2:
            try:
                correlation = compute_stereo_correlation_wav(stem_path)
            except ValueError:
                correlation = None
            if correlation is not None:
                upsert_measurement(
                    stem,
                    evidence_id="EVID.IMAGE.CORRELATION",
                    value=correlation,
                    unit_id="UNIT.CORRELATION",
                )
    return missing_ffmpeg


def _add_truth_meter_measurements(session: Dict[str, Any], stems_dir: Path) -> None:
    from mmo.dsp.meters_truth import (  # noqa: WPS433
        compute_lufs_integrated_wav,
        compute_lufs_shortterm_wav,
        compute_true_peak_dbtp_wav,
    )

    stems = session.get("stems", [])
    for stem in stems:
        if not isinstance(stem, dict):
            continue
        if "sample_rate_hz" not in stem or "bits_per_sample" not in stem:
            continue
        file_path = stem.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            continue
        stem_path = Path(file_path)
        if not stem_path.is_absolute():
            stem_path = stems_dir / stem_path
        if detect_format_from_path(stem_path) != "wav":
            continue

        try:
            truepeak_dbtp = compute_true_peak_dbtp_wav(stem_path)
            lufs_i = compute_lufs_integrated_wav(stem_path)
            lufs_s = compute_lufs_shortterm_wav(stem_path)
        except ValueError:
            continue

        upsert_measurement(
            stem,
            evidence_id="EVID.METER.TRUEPEAK_DBTP",
            value=truepeak_dbtp,
            unit_id="UNIT.DBTP",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.LUFS_I",
            value=lufs_i,
            unit_id="UNIT.LUFS",
        )
        upsert_measurement(
            stem,
            evidence_id="EVID.METER.LUFS_S",
            value=lufs_s,
            unit_id="UNIT.LUFS",
        )


def _has_optional_dep_issue(issues: List[Dict[str, Any]], dep_name: str) -> bool:
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        if issue.get("issue_id") != "ISSUE.VALIDATION.OPTIONAL_DEP_MISSING":
            continue
        evidence = issue.get("evidence", [])
        if not isinstance(evidence, list):
            continue
        for item in evidence:
            if not isinstance(item, dict):
                continue
            if (
                item.get("evidence_id")
                == "EVID.VALIDATION.MISSING_OPTIONAL_DEP"
                and item.get("value") == dep_name
            ):
                return True
    return False


def _add_optional_dep_issue(
    issues: List[Dict[str, Any]],
    dep_name: str,
    hint: str,
) -> None:
    if _has_optional_dep_issue(issues, dep_name):
        return
    issues.append(
        {
            "issue_id": "ISSUE.VALIDATION.OPTIONAL_DEP_MISSING",
            "severity": 30,
            "confidence": 1.0,
            "target": {"scope": "session"},
            "evidence": [
                {
                    "evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP",
                    "value": dep_name,
                },
                {
                    "evidence_id": "EVID.VALIDATION.MISSING_OPTIONAL_DEP_HINT",
                    "value": hint,
                },
            ],
            "message": f"Optional dependency '{dep_name}' is missing; skipping related meters.",
        }
    )


def build_report(
    stems_dir: Path,
    generated_at: str,
    *,
    strict: bool = False,
    include_peak: bool = False,
    meters: Optional[str] = None,
) -> Dict[str, Any]:
    session = build_session_from_stems_dir(stems_dir)
    stems = session.get("stems", [])
    if not stems:
        raise ValueError(
            "No audio stems found in the provided directory. "
            "Point scan_session at an actual stems folder containing .wav/.flac/.wv/.aiff/.mp3/etc. "
            "Note: fixtures/sessions contains YAML fixture definitions, not audio stems."
        )
    if include_peak:
        _add_peak_metrics(session, stems_dir)
    missing_ffmpeg = False
    if meters == "basic":
        missing_ffmpeg = _add_basic_meter_measurements(session, stems_dir)
    issues = validate_session(session, strict=strict)
    if missing_ffmpeg:
        _add_optional_dep_issue(
            issues,
            dep_name="ffmpeg",
            hint="Install FFmpeg or set MMO_FFMPEG_PATH=/path/to/ffmpeg",
        )
    if meters == "truth":
        try:
            import numpy  # noqa: F401
        except ImportError:
            _add_optional_dep_issue(
                issues,
                dep_name="numpy",
                hint="Install: pip install .[truth]",
            )
        else:
            _add_truth_meter_measurements(session, stems_dir)
    stem_hash = _hash_from_stems(session.get("stems", []))
    ontology_version = _load_ontology_version(ROOT_DIR / "ontology" / "ontology.yaml")
    return {
        "schema_version": "0.1.0",
        "report_id": stem_hash,
        "project_id": stem_hash,
        "generated_at": generated_at,
        "engine_version": engine_version,
        "ontology_version": ontology_version,
        "session": session,
        "issues": issues,
        "recommendations": [],
    }


def main() -> int:
    try:
        parser = argparse.ArgumentParser(description="Scan a stems directory into an MMO report.")
        parser.add_argument("stems_dir", help="Path to a directory of audio stems.")
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Treat lossy/unsupported formats as high-severity issues.",
        )
        parser.add_argument(
            "--peak",
            action="store_true",
            help="Compute WAV sample peak meter readings for stems.",
        )
        parser.add_argument(
            "--meters",
            choices=["basic", "truth"],
            default=None,
            help="Enable additional meter packs (basic or truth).",
        )
        parser.add_argument("--out", dest="out", default=None, help="Optional output JSON path.")
        parser.add_argument(
            "--schema",
            dest="schema",
            default=None,
            help="Optional JSON schema path for validation.",
        )
        parser.add_argument(
            "--generated-at",
            dest="generated_at",
            default="2000-01-01T00:00:00Z",
            help="Override generated_at timestamp (ISO 8601).",
        )
        args = parser.parse_args()

        report = build_report(
            Path(args.stems_dir),
            args.generated_at,
            strict=args.strict,
            include_peak=args.peak,
            meters=args.meters,
        )

        if args.schema:
            _validate_schema(Path(args.schema), report)

        output = json.dumps(report, indent=2)
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output + "\n", encoding="utf-8")
        else:
            print(output)

        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
