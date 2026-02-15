from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from mmo.resources import ontology_dir, presets_dir, schemas_dir


def _resolve_schema_path(schema_arg: str) -> Path:
    if schema_arg == "schemas/plugin.schema.json":
        return schemas_dir() / "plugin.schema.json"
    return Path(schema_arg)


def _validate_plugins(plugins_dir: Path, schema_path: Path) -> Dict[str, Any]:
    try:
        from mmo.tools.validate_plugins import validate_plugins
    except Exception:
        return {
            "ok": True,
            "issue_counts": {"error": 0, "warn": 0},
            "issues": [],
        }
    return validate_plugins(plugins_dir, schema_path)


def _load_report(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Report JSON must be an object.")
    return data


def _write_report(path: Path, report: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MMO detector/resolver pipeline.")
    parser.add_argument("--report", required=True, help="Path to input report JSON.")
    parser.add_argument("--plugins", default="plugins", help="Path to plugins directory.")
    parser.add_argument("--out", required=True, help="Path to output report JSON.")
    parser.add_argument(
        "--schema",
        default="schemas/plugin.schema.json",
        help="Path to the plugin manifest schema.",
    )
    parser.add_argument(
        "--profile",
        default="PROFILE.ASSIST",
        help="Authority profile ID for gate eligibility (default: PROFILE.ASSIST).",
    )
    args = parser.parse_args()

    plugins_dir = Path(args.plugins)
    schema_path = _resolve_schema_path(args.schema)

    validation = _validate_plugins(plugins_dir, schema_path)
    print(json.dumps(validation, indent=2))
    if validation["issue_counts"]["error"] > 0:
        return 1

    from mmo.core.gates import apply_gates_to_report
    from mmo.core.pipeline import load_plugins, run_detectors, run_resolvers
    from mmo.core.preset_recommendations import derive_preset_recommendations
    from mmo.core.routing import apply_routing_plan_to_report
    from mmo.core.vibe_signals import derive_vibe_signals

    report_path = Path(args.report)
    output_path = Path(args.out)
    report = _load_report(report_path)

    plugins = load_plugins(plugins_dir)
    run_detectors(report, plugins)
    run_resolvers(report, plugins)
    policies_dir = ontology_dir() / "policies"
    apply_gates_to_report(
        report,
        policy_path=policies_dir / "gates.yaml",
        profile_id=args.profile,
        profiles_path=policies_dir / "authority_profiles.yaml",
    )
    if isinstance(report.get("mix_complexity"), dict):
        report["vibe_signals"] = derive_vibe_signals(report)
        report["preset_recommendations"] = derive_preset_recommendations(
            report,
            presets_dir(),
        )
    apply_routing_plan_to_report(report, report.get("run_config"))

    _write_report(output_path, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
