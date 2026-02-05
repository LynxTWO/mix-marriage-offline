from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict


def _load_validate_plugins_module() -> Any:
    tools_dir = Path(__file__).resolve().parent
    module_path = tools_dir / "validate_plugins.py"
    spec = importlib.util.spec_from_file_location("validate_plugins", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load validate_plugins module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    repo_root = Path(__file__).resolve().parents[1]
    plugins_dir = Path(args.plugins)
    schema_path = Path(args.schema)

    validate_module = _load_validate_plugins_module()
    validation = validate_module.validate_plugins(plugins_dir, schema_path)
    print(json.dumps(validation, indent=2))
    if validation["issue_counts"]["error"] > 0:
        return 1

    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from mmo.core.gates import apply_gates_to_report
    from mmo.core.pipeline import load_plugins, run_detectors, run_resolvers

    report_path = Path(args.report)
    output_path = Path(args.out)
    report = _load_report(report_path)

    plugins = load_plugins(plugins_dir)
    run_detectors(report, plugins)
    run_resolvers(report, plugins)
    apply_gates_to_report(
        report,
        policy_path=repo_root / "ontology" / "policies" / "gates.yaml",
        profile_id=args.profile,
        profiles_path=repo_root / "ontology" / "policies" / "authority_profiles.yaml",
    )

    _write_report(output_path, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
