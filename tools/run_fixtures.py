"""Run session-validation fixtures from fixtures/sessions/*.yaml."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mmo.core.validators import validate_session  # noqa: E402


def load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed; cannot parse YAML fixtures.")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Fixture is not a mapping: {path}")
    return data


def discover_fixtures(fixtures_dir: Path) -> List[Path]:
    return sorted(fixtures_dir.glob("*.yaml"))


def _issue_ids(issues: Iterable[Dict[str, Any]]) -> List[str]:
    return sorted({issue.get("issue_id") for issue in issues if issue.get("issue_id")})


def _build_stem(stem_input: Dict[str, Any]) -> Dict[str, Any]:
    stem: Dict[str, Any] = {}
    filename = stem_input.get("filename")
    if not isinstance(filename, str) or not filename:
        raise ValueError("Stem filename missing or invalid.")
    stem["file_path"] = filename

    channel_count = stem_input.get("channels")
    if channel_count is not None:
        stem["channel_count"] = channel_count
        stem["channels"] = channel_count

    for key in ("sample_rate_hz", "duration_s", "bits_per_sample"):
        value = stem_input.get(key)
        if value is not None:
            stem[key] = value

    for key in ("codec_name", "channel_layout", "wav_channel_mask"):
        value = stem_input.get(key)
        if value is not None:
            stem[key] = value

    return stem


def build_session(fixture: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, bool]:
    inputs = fixture.get("inputs") or {}
    stems_input = inputs.get("stems")
    if not isinstance(stems_input, list) or not stems_input:
        raise ValueError("inputs.stems must be a non-empty list.")

    stems = [_build_stem(stem) for stem in stems_input if isinstance(stem, dict)]
    if len(stems) != len(stems_input):
        raise ValueError("Each stem must be a mapping.")

    strict = bool(inputs.get("strict", False))
    force_missing_ffprobe = bool(inputs.get("force_missing_ffprobe", False))
    session = {"stems": stems}
    return session, strict, force_missing_ffprobe


def evaluate_fixture(
    fixture_path: Path, fixture: Dict[str, Any]
) -> Tuple[List[str], List[str]]:
    if fixture.get("fixture_type") != "session_validation":
        raise ValueError(f"{fixture_path}: fixture_type must be session_validation")

    expected_issue_ids = fixture.get("expected_issue_ids")
    if expected_issue_ids is None:
        expected_issue_ids = []
    if not isinstance(expected_issue_ids, list):
        raise ValueError(f"{fixture_path}: expected_issue_ids must be a list")
    expected_issue_ids = sorted({str(issue_id) for issue_id in expected_issue_ids})

    session, strict, force_missing_ffprobe = build_session(fixture)

    previous_ffprobe = os.environ.get("MMO_FFPROBE_PATH")
    if force_missing_ffprobe:
        os.environ["MMO_FFPROBE_PATH"] = os.fspath(Path("__missing_ffprobe__"))

    try:
        issues = validate_session(session, strict=strict)
    finally:
        if force_missing_ffprobe:
            if previous_ffprobe is None:
                os.environ.pop("MMO_FFPROBE_PATH", None)
            else:
                os.environ["MMO_FFPROBE_PATH"] = previous_ffprobe

    actual_issue_ids = _issue_ids(issues)
    return expected_issue_ids, actual_issue_ids


def run_fixture(fixture_path: Path, fixture: Dict[str, Any]) -> bool:
    try:
        expected_issue_ids, actual_issue_ids = evaluate_fixture(fixture_path, fixture)
    except Exception as exc:
        print(f"FAIL {fixture_path}: {exc}", file=sys.stderr)
        return False

    if actual_issue_ids != expected_issue_ids:
        expected_set = set(expected_issue_ids)
        actual_set = set(actual_issue_ids)
        missing = sorted(expected_set - actual_set)
        extra = sorted(actual_set - expected_set)
        details = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"extra={extra}")
        detail_str = " ".join(details)
        print(f"FAIL {fixture_path}: {detail_str}", file=sys.stderr)
        return False

    print(f"PASS {fixture_path}")
    return True


def run_fixtures(fixtures_dir: Path) -> int:
    fixture_files = discover_fixtures(fixtures_dir)
    if not fixture_files:
        print(f"No fixtures found in {fixtures_dir}", file=sys.stderr)
        return 1

    failures = 0
    for fixture_path in fixture_files:
        try:
            fixture = load_yaml(fixture_path)
        except Exception as exc:
            print(f"FAIL {fixture_path}: failed to load fixture: {exc}", file=sys.stderr)
            failures += 1
            continue

        if not run_fixture(fixture_path, fixture):
            failures += 1

    if failures:
        print(f"Fixture failures: {failures}", file=sys.stderr)
        return 1
    print("All session fixtures passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run session-validation fixtures from fixtures/sessions."
    )
    parser.add_argument(
        "fixtures_dir",
        nargs="?",
        default="fixtures/sessions",
        help="Directory containing session validation fixtures.",
    )
    args = parser.parse_args()
    return run_fixtures(Path(args.fixtures_dir))


if __name__ == "__main__":
    raise SystemExit(main())
