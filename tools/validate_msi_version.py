"""Validate Windows MSI version mapping against the public app version.

MSI bundles only support numeric version identifiers (major.minor.patch.build,
each component 0–65535).  For SemVer prerelease versions like ``1.0.0-rc.1``
the repo maps to a 4-part numeric form:

    1.0.0-rc.N  →  1.0.0.N   (4th component = RC number)
    1.0.0       →  1.0.0.0   (stable release, build component = 0)

This script reads both values from ``tauri.conf.json`` and verifies they agree.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


TAURI_CONF_REL = Path("gui/desktop-tauri/src-tauri/tauri.conf.json")


def _expected_msi_version(semver: str) -> str | None:
    """Derive the expected MSI 4-part version from a SemVer string.

    Returns *None* if the SemVer string has a prerelease tag that is not
    a recognised ``rc.N`` pattern.
    """
    match = re.fullmatch(
        r"(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
        r"(?:-rc\.(?P<rc>\d+))?",
        semver,
    )
    if match is None:
        return None
    rc = match.group("rc")
    build = int(rc) if rc is not None else 0
    return f"{match.group('major')}.{match.group('minor')}.{match.group('patch')}.{build}"


def validate_msi_version(*, repo_root: Path) -> dict[str, Any]:
    """Return a JSON-serialisable result dict with ``ok`` and details."""
    errors: list[str] = []

    tauri_conf_path = repo_root / TAURI_CONF_REL
    if not tauri_conf_path.is_file():
        errors.append(f"Tauri config not found: {TAURI_CONF_REL}")
        return {"ok": False, "errors": errors}

    try:
        conf = json.loads(tauri_conf_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"Failed to read {TAURI_CONF_REL}: {exc}")
        return {"ok": False, "errors": errors}

    app_version: str | None = conf.get("version")
    if not isinstance(app_version, str) or not app_version:
        errors.append(
            f"Missing or non-string top-level 'version' in {TAURI_CONF_REL}."
        )
        return {"ok": False, "errors": errors}

    wix_version: str | None = (
        conf.get("bundle", {}).get("windows", {}).get("wix", {}).get("version")
    )
    if not isinstance(wix_version, str) or not wix_version:
        errors.append(
            f"Missing or non-string 'bundle.windows.wix.version' in {TAURI_CONF_REL}."
        )
        return {"ok": False, "errors": errors}

    expected = _expected_msi_version(app_version)
    if expected is None:
        errors.append(
            f"Cannot derive MSI version from app version '{app_version}': "
            "only stable (X.Y.Z) and rc (X.Y.Z-rc.N) patterns are supported."
        )
        return {
            "ok": False,
            "app_version": app_version,
            "msi_version": wix_version,
            "errors": errors,
        }

    if wix_version != expected:
        errors.append(
            f"MSI version mismatch: app version '{app_version}' expects "
            f"MSI version '{expected}', but found '{wix_version}'."
        )

    ok = not errors
    result: dict[str, Any] = {
        "ok": ok,
        "app_version": app_version,
        "msi_version": wix_version,
        "expected_msi_version": expected,
    }
    if errors:
        result["errors"] = errors
    return result


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Validate Windows MSI version mapping against public app version.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(repo_root),
        help="Repository root containing gui/desktop-tauri/.",
    )
    args = parser.parse_args()

    result = validate_msi_version(repo_root=Path(args.repo_root))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
