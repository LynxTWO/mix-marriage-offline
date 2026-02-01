"""Scan a stems directory and emit a deterministic MMO report."""

from __future__ import annotations

import argparse
import hashlib
import json
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
from mmo.dsp.meters import compute_sample_peak_dbfs_wav  # noqa: E402


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


def build_report(
    stems_dir: Path,
    generated_at: str,
    *,
    strict: bool = False,
    include_peak: bool = False,
) -> Dict[str, Any]:
    session = build_session_from_stems_dir(stems_dir)
    if include_peak:
        _add_peak_metrics(session, stems_dir)
    issues = validate_session(session, strict=strict)
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


if __name__ == "__main__":
    raise SystemExit(main())
