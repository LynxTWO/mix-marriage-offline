"""Run session-validation fixtures by generating tiny WAV stems."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mmo.core.session import build_session_from_stems_dir  # noqa: E402
from mmo.core.validators import validate_session  # noqa: E402


def _load_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is not installed; cannot parse YAML fixtures.")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _write_wav(
    path: Path,
    *,
    sample_rate_hz: int,
    channels: int,
    bits_per_sample: int,
    duration_s: float,
    samples: List[int] | None = None,
) -> None:
    if bits_per_sample % 8 != 0:
        raise ValueError(f"bits_per_sample must be divisible by 8: {bits_per_sample}")
    sample_width = bits_per_sample // 8
    if sample_width < 1 or sample_width > 4:
        raise ValueError(f"Unsupported bits_per_sample: {bits_per_sample}")
    if sample_rate_hz <= 0 or channels <= 0 or duration_s <= 0:
        raise ValueError("sample_rate_hz, channels, and duration_s must be positive")

    if samples is not None:
        if bits_per_sample not in (16, 24):
            raise ValueError(f"Unsupported bits_per_sample for samples: {bits_per_sample}")
        if any(not isinstance(sample, int) for sample in samples):
            raise ValueError("samples must be integers")
        if len(samples) % channels != 0:
            raise ValueError("samples length must be divisible by channels")
        max_value = (1 << (bits_per_sample - 1)) - 1
        min_value = -(1 << (bits_per_sample - 1))
        frames = bytearray()
        for sample in samples:
            if sample < min_value or sample > max_value:
                raise ValueError(f"Sample out of range: {sample}")
            frames.extend(int(sample).to_bytes(sample_width, "little", signed=True))
        data = bytes(frames)
    else:
        frame_count = int(sample_rate_hz * duration_s)
        data = b"\x00" * (frame_count * channels * sample_width)

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(data)


def _write_corrupt(path: Path, *, byte_count: int = 6) -> None:
    if byte_count <= 0:
        raise ValueError("byte_count must be positive")
    path.write_bytes(b"BADWAV"[:byte_count])


def _issue_ids(issues: List[Dict[str, Any]]) -> List[str]:
    ids = sorted({issue.get("issue_id") for issue in issues if issue.get("issue_id")})
    return ids


def _run_fixture(
    fixture_path: Path,
    fixture: Dict[str, Any],
    *,
    force_missing_ffprobe: bool = False,
) -> bool:
    if fixture.get("fixture_type") != "session_validation":
        print(f"{fixture_path}: fixture_type must be session_validation", file=sys.stderr)
        return False

    inputs = fixture.get("inputs", {})
    stems = inputs.get("stems")
    if not isinstance(stems, list) or not stems:
        print(f"{fixture_path}: inputs.stems must be a non-empty list", file=sys.stderr)
        return False

    expected_issue_ids = fixture.get("expected_issue_ids")
    if expected_issue_ids is None:
        expected_issue_ids = []
    if not isinstance(expected_issue_ids, list):
        print(f"{fixture_path}: expected_issue_ids must be a list", file=sys.stderr)
        return False
    expected_issue_ids = sorted({str(issue_id) for issue_id in expected_issue_ids})

    force_missing = bool(inputs.get("force_missing_ffprobe") or force_missing_ffprobe)
    previous_ffprobe = os.environ.get("MMO_FFPROBE_PATH")
    if force_missing:
        os.environ["MMO_FFPROBE_PATH"] = os.fspath(Path("__missing_ffprobe__"))

    with tempfile.TemporaryDirectory(prefix="mmo_session_fixture_") as tmp_dir:
        stems_dir = Path(tmp_dir) / "stems"
        stems_dir.mkdir(parents=True, exist_ok=True)

        for stem in stems:
            if not isinstance(stem, dict):
                print(f"{fixture_path}: each stem must be a map", file=sys.stderr)
                return False
            filename = stem.get("filename")
            if not isinstance(filename, str) or not filename:
                print(f"{fixture_path}: stem filename missing", file=sys.stderr)
                return False
            stem_path = stems_dir / filename
            if stem.get("corrupt"):
                byte_count = stem.get("byte_count", 6)
                _write_corrupt(stem_path, byte_count=int(byte_count))
                continue

            sample_rate_hz = stem.get("sample_rate_hz")
            channels = stem.get("channels")
            bits_per_sample = stem.get("bits_per_sample")
            duration_s = stem.get("duration_s")
            if not all(
                isinstance(value, (int, float))
                for value in (sample_rate_hz, channels, bits_per_sample, duration_s)
            ):
                print(
                    f"{fixture_path}: stem {filename} missing required audio fields",
                    file=sys.stderr,
                )
                return False
            _write_wav(
                stem_path,
                sample_rate_hz=int(sample_rate_hz),
                channels=int(channels),
                bits_per_sample=int(bits_per_sample),
                duration_s=float(duration_s),
                samples=stem.get("samples"),
            )

        try:
            session = build_session_from_stems_dir(stems_dir)
            issues = validate_session(session)
        except Exception:
            issues = [{"issue_id": "ISSUE.VALIDATION.DECODE_ERROR"}]
        finally:
            if force_missing:
                if previous_ffprobe is None:
                    os.environ.pop("MMO_FFPROBE_PATH", None)
                else:
                    os.environ["MMO_FFPROBE_PATH"] = previous_ffprobe

    actual_issue_ids = _issue_ids(issues)
    if actual_issue_ids != expected_issue_ids:
        print(
            f"{fixture_path}: expected {expected_issue_ids}, got {actual_issue_ids}",
            file=sys.stderr,
        )
        return False
    print(f"{fixture_path}: OK")
    return True


def run_fixtures(fixtures_dir: Path, *, force_missing_ffprobe: bool = False) -> int:
    fixture_files = sorted(fixtures_dir.glob("*.yaml"))
    if not fixture_files:
        print(f"No fixtures found in {fixtures_dir}", file=sys.stderr)
        return 1

    failures = 0
    for fixture_path in fixture_files:
        try:
            fixture = _load_yaml(fixture_path)
        except Exception as exc:
            print(f"{fixture_path}: failed to load fixture: {exc}", file=sys.stderr)
            failures += 1
            continue

        if not isinstance(fixture, dict):
            print(f"{fixture_path}: fixture must be a map", file=sys.stderr)
            failures += 1
            continue

        if not _run_fixture(
            fixture_path, fixture, force_missing_ffprobe=force_missing_ffprobe
        ):
            failures += 1

    if failures:
        print(f"Fixture failures: {failures}", file=sys.stderr)
        return 1
    print("All session fixtures passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run session-validation fixtures.")
    parser.add_argument(
        "fixtures_dir",
        nargs="?",
        default=None,
        help="Directory containing session validation fixtures.",
    )
    parser.add_argument(
        "--fixtures",
        dest="fixtures",
        default=None,
        help=(
            "Optional explicit path to the fixtures directory. "
            "If provided, this overrides the positional fixtures_dir."
        ),
    )
    parser.add_argument(
        "--force-missing-ffprobe",
        action="store_true",
        help="Force MMO_FFPROBE_PATH to an invalid path for all fixtures.",
    )
    args = parser.parse_args()

    fixtures_value = args.fixtures or args.fixtures_dir or "fixtures/sessions"
    fixtures_dir = Path(fixtures_value)
    return run_fixtures(
        fixtures_dir, force_missing_ffprobe=bool(args.force_missing_ffprobe)
    )


if __name__ == "__main__":
    raise SystemExit(main())
