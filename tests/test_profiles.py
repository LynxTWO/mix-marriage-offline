"""Tests for src/mmo/core/profiles.py and ontology/profiles.yaml (DoD 4.7).

Covers:
- Schema validation: profiles.yaml validates against profile.schema.json.
- Determinism: same inputs always produce identical outputs.
- load_profiles / list_profiles: sorted keys, required fields present.
- get_profile: known ID returns dict; unknown ID raises ValueError.
- apply_to_gates: profile gate_overrides are merged into options.
- validate_against_scene: confidence and correlation issues are detected.
- Preflight integration: evaluate_preflight respects user_profile overrides.
- CLI subcommands: mmo profile list / show / apply.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

import jsonschema
import yaml

from mmo.core.profiles import (
    apply_to_gates,
    get_profile,
    list_profiles,
    load_profiles,
    validate_against_scene,
)
from mmo.core.preflight import evaluate_preflight

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"
_ONTOLOGY_DIR = _REPO_ROOT / "ontology"
_PROFILES_PATH = _ONTOLOGY_DIR / "profiles.yaml"
_PROFILE_SCHEMA_PATH = _SCHEMAS_DIR / "profile.schema.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _python_cmd() -> str:
    return os.fspath(os.getenv("PYTHON", "") or sys.executable)


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    return env


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestProfileSchemaValidation(unittest.TestCase):
    def test_profiles_yaml_validates_against_schema(self) -> None:
        schema = json.loads(_PROFILE_SCHEMA_PATH.read_text(encoding="utf-8"))
        payload = yaml.safe_load(_PROFILES_PATH.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [], msg="\n".join(str(e) for e in errors[:5]))


# ---------------------------------------------------------------------------
# load_profiles / list_profiles
# ---------------------------------------------------------------------------

class TestLoadProfiles(unittest.TestCase):
    def test_load_profiles_returns_sorted_dict(self) -> None:
        profiles = load_profiles(_PROFILES_PATH)
        self.assertIsInstance(profiles, dict)
        keys = list(profiles.keys())
        self.assertEqual(keys, sorted(keys))

    def test_load_profiles_deterministic(self) -> None:
        first = load_profiles(_PROFILES_PATH)
        second = load_profiles(_PROFILES_PATH)
        self.assertEqual(first, second)

    def test_load_profiles_contains_expected_ids(self) -> None:
        profiles = load_profiles(_PROFILES_PATH)
        expected = [
            "PROFILE.USER.BROADCAST",
            "PROFILE.USER.CLUB",
            "PROFILE.USER.CONSERVATIVE",
        ]
        for pid in expected:
            self.assertIn(pid, profiles, msg=f"Missing profile: {pid}")

    def test_each_profile_has_required_fields(self) -> None:
        profiles = load_profiles(_PROFILES_PATH)
        required_fields = {"label", "description", "style_intent", "gate_overrides", "param_bounds", "safety_notes"}
        for pid, profile in profiles.items():
            for field in required_fields:
                self.assertIn(field, profile, msg=f"{pid} missing field: {field}")

    def test_list_profiles_is_sorted_and_deterministic(self) -> None:
        rows = list_profiles(_PROFILES_PATH)
        self.assertIsInstance(rows, list)
        ids = [r["profile_id"] for r in rows]
        self.assertEqual(ids, sorted(ids))

        second = list_profiles(_PROFILES_PATH)
        self.assertEqual(rows, second)

    def test_list_profiles_summary_fields_present(self) -> None:
        rows = list_profiles(_PROFILES_PATH)
        for row in rows:
            self.assertIn("profile_id", row)
            self.assertIn("label", row)
            self.assertIn("description", row)
            self.assertIn("style_intent", row)
            self.assertIsInstance(row["style_intent"], list)


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------

class TestGetProfile(unittest.TestCase):
    def test_get_profile_known_id(self) -> None:
        profile = get_profile("PROFILE.USER.CONSERVATIVE", _PROFILES_PATH)
        self.assertEqual(profile["profile_id"], "PROFILE.USER.CONSERVATIVE")
        self.assertIn("gate_overrides", profile)

    def test_get_profile_unknown_id_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            get_profile("PROFILE.USER.NONEXISTENT", _PROFILES_PATH)
        self.assertIn("PROFILE.USER.NONEXISTENT", str(ctx.exception))

    def test_get_profile_empty_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            get_profile("", _PROFILES_PATH)

    def test_get_profile_deterministic(self) -> None:
        first = get_profile("PROFILE.USER.BROADCAST", _PROFILES_PATH)
        second = get_profile("PROFILE.USER.BROADCAST", _PROFILES_PATH)
        self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# apply_to_gates
# ---------------------------------------------------------------------------

class TestApplyToGates(unittest.TestCase):
    def _conservative(self) -> Dict[str, Any]:
        return get_profile("PROFILE.USER.CONSERVATIVE", _PROFILES_PATH)

    def test_apply_to_gates_merges_overrides(self) -> None:
        profile = self._conservative()
        options = apply_to_gates(profile, {})
        overrides = profile["gate_overrides"]
        for key, value in overrides.items():
            self.assertIn(key, options)
            self.assertEqual(options[key], value)

    def test_apply_to_gates_profile_wins_over_caller_options(self) -> None:
        profile = self._conservative()
        # Conservative has lfe_boost_warn_db: 1.5 — caller sets a looser 5.0
        caller_options = {"lfe_boost_warn_db": 5.0}
        result = apply_to_gates(profile, caller_options)
        self.assertEqual(result["lfe_boost_warn_db"], 1.5)

    def test_apply_to_gates_does_not_mutate_input(self) -> None:
        profile = self._conservative()
        original_options = {"lfe_boost_warn_db": 99.0}
        input_copy = dict(original_options)
        apply_to_gates(profile, original_options)
        self.assertEqual(original_options, input_copy)

    def test_apply_to_gates_returns_new_dict(self) -> None:
        profile = self._conservative()
        options = {"x": 1}
        result = apply_to_gates(profile, options)
        self.assertIsNot(result, options)

    def test_apply_to_gates_deterministic(self) -> None:
        profile = get_profile("PROFILE.USER.CLUB", _PROFILES_PATH)
        first = apply_to_gates(profile, {})
        second = apply_to_gates(profile, {})
        self.assertEqual(first, second)

    def test_conservative_tighter_than_broadcast(self) -> None:
        conservative = get_profile("PROFILE.USER.CONSERVATIVE", _PROFILES_PATH)
        broadcast = get_profile("PROFILE.USER.BROADCAST", _PROFILES_PATH)
        cons_opts = apply_to_gates(conservative, {})
        broad_opts = apply_to_gates(broadcast, {})
        # Conservative should have tighter LFE warn than broadcast
        self.assertLessEqual(
            cons_opts.get("lfe_boost_warn_db", 99),
            broad_opts.get("lfe_boost_warn_db", 0),
        )
        # Conservative should have tighter confidence thresholds
        self.assertGreaterEqual(
            cons_opts.get("confidence_warn_below", 0),
            broad_opts.get("confidence_warn_below", 0),
        )

    def test_club_looser_lfe_than_broadcast(self) -> None:
        club = get_profile("PROFILE.USER.CLUB", _PROFILES_PATH)
        broadcast = get_profile("PROFILE.USER.BROADCAST", _PROFILES_PATH)
        club_opts = apply_to_gates(club, {})
        broad_opts = apply_to_gates(broadcast, {})
        self.assertGreaterEqual(
            club_opts.get("lfe_boost_warn_db", 0),
            broad_opts.get("lfe_boost_warn_db", 0),
        )


# ---------------------------------------------------------------------------
# validate_against_scene
# ---------------------------------------------------------------------------

class TestValidateAgainstScene(unittest.TestCase):
    def _conservative(self) -> Dict[str, Any]:
        return get_profile("PROFILE.USER.CONSERVATIVE", _PROFILES_PATH)

    def test_no_issues_for_clean_scene(self) -> None:
        profile = self._conservative()
        scene: Dict[str, Any] = {"metadata": {"confidence": 0.95, "correlation": 0.7}}
        issues = validate_against_scene(profile, scene)
        self.assertEqual(issues, [])

    def test_confidence_error_detected(self) -> None:
        profile = self._conservative()
        # Conservative has confidence_error_below: 0.35 — use 0.1 to trigger error
        scene: Dict[str, Any] = {"metadata": {"confidence": 0.1}}
        issues = validate_against_scene(profile, scene)
        severities = [iss["severity"] for iss in issues]
        self.assertIn("error", severities)
        codes = [iss["code"] for iss in issues]
        self.assertIn("PROFILE.SCENE_CONFIDENCE_TOO_LOW", codes)

    def test_confidence_warn_detected(self) -> None:
        profile = self._conservative()
        # Conservative has confidence_warn_below: 0.7, error_below: 0.35
        # Use 0.5 to trigger warn but not error
        scene: Dict[str, Any] = {"metadata": {"confidence": 0.5}}
        issues = validate_against_scene(profile, scene)
        severities = [iss["severity"] for iss in issues]
        self.assertIn("warn", severities)
        self.assertNotIn("error", severities)

    def test_correlation_error_detected(self) -> None:
        profile = self._conservative()
        # Conservative has correlation_error_lte: -0.4 — use -0.8 to trigger
        scene: Dict[str, Any] = {"metadata": {"correlation": -0.8}}
        issues = validate_against_scene(profile, scene)
        codes = [iss["code"] for iss in issues]
        self.assertIn("PROFILE.SCENE_CORRELATION_HIGH_RISK", codes)

    def test_correlation_warn_detected(self) -> None:
        profile = self._conservative()
        # Conservative has correlation_warn_lte: -0.1, error_lte: -0.4
        # Use -0.2 to trigger warn
        scene: Dict[str, Any] = {"metadata": {"correlation": -0.2}}
        issues = validate_against_scene(profile, scene)
        codes = [iss["code"] for iss in issues]
        self.assertIn("PROFILE.SCENE_CORRELATION_RISK", codes)
        severities = {iss["severity"] for iss in issues if iss["code"] == "PROFILE.SCENE_CORRELATION_RISK"}
        self.assertIn("warn", severities)

    def test_empty_scene_no_issues(self) -> None:
        profile = self._conservative()
        issues = validate_against_scene(profile, {})
        self.assertEqual(issues, [])

    def test_issues_sorted_error_before_warn(self) -> None:
        profile = self._conservative()
        # Trigger both a confidence error and a correlation warn
        scene: Dict[str, Any] = {"metadata": {"confidence": 0.1, "correlation": -0.2}}
        issues = validate_against_scene(profile, scene)
        if len(issues) >= 2:
            severity_order = {"error": 0, "warn": 1, "info": 2}
            for i in range(len(issues) - 1):
                self.assertLessEqual(
                    severity_order.get(issues[i]["severity"], 2),
                    severity_order.get(issues[i + 1]["severity"], 2),
                )

    def test_validate_deterministic(self) -> None:
        profile = self._conservative()
        scene: Dict[str, Any] = {"metadata": {"confidence": 0.5, "correlation": -0.3}}
        first = validate_against_scene(profile, scene)
        second = validate_against_scene(profile, scene)
        self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# Preflight integration
# ---------------------------------------------------------------------------

class TestPreflightIntegration(unittest.TestCase):
    def _make_scene_with_confidence(self, overall: float) -> Dict[str, Any]:
        return {"metadata": {"confidence": overall}}

    def test_evaluate_preflight_with_conservative_profile_tighter_confidence(self) -> None:
        """Conservative profile should block on higher confidence threshold than default."""
        conservative = get_profile("PROFILE.USER.CONSERVATIVE", _PROFILES_PATH)
        # Conservative error threshold is 0.35; default is 0.2.
        # Use conf=0.25 — passes default, fails conservative.
        scene = self._make_scene_with_confidence(0.25)
        receipt_default = evaluate_preflight({}, scene, "stereo", {})
        receipt_conservative = evaluate_preflight({}, scene, "stereo", {}, user_profile=conservative)

        # Default passes (0.25 > default error_below=0.2), conservative blocks (0.25 < 0.35)
        self.assertNotEqual(
            receipt_default.get("final_decision"),
            receipt_conservative.get("final_decision"),
            msg="Conservative profile should tighten confidence check relative to default",
        )

    def test_evaluate_preflight_user_profile_id_stored_in_receipt(self) -> None:
        profile = get_profile("PROFILE.USER.BROADCAST", _PROFILES_PATH)
        scene: Dict[str, Any] = {}
        receipt = evaluate_preflight({}, scene, "stereo", {}, user_profile=profile)
        self.assertEqual(receipt.get("user_profile_id"), "PROFILE.USER.BROADCAST")

    def test_evaluate_preflight_no_user_profile_no_user_profile_id_in_receipt(self) -> None:
        scene: Dict[str, Any] = {}
        receipt = evaluate_preflight({}, scene, "stereo", {})
        self.assertNotIn("user_profile_id", receipt)

    def test_evaluate_preflight_with_profile_deterministic(self) -> None:
        profile = get_profile("PROFILE.USER.CLUB", _PROFILES_PATH)
        scene: Dict[str, Any] = {"metadata": {"confidence": 0.8}}
        first = evaluate_preflight({}, scene, "stereo", {}, user_profile=profile)
        second = evaluate_preflight({}, scene, "stereo", {}, user_profile=profile)
        self.assertEqual(first, second)

    def test_evaluate_preflight_club_more_lenient_lfe(self) -> None:
        """Club profile allows higher LFE boost before warning."""
        club = get_profile("PROFILE.USER.CLUB", _PROFILES_PATH)
        conservative = get_profile("PROFILE.USER.CONSERVATIVE", _PROFILES_PATH)
        club_opts = apply_to_gates(club, {})
        cons_opts = apply_to_gates(conservative, {})
        # Club should have higher lfe_boost_warn_db than conservative
        self.assertGreater(
            club_opts.get("lfe_boost_warn_db", 0),
            cons_opts.get("lfe_boost_warn_db", 0),
        )


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------

class TestProfileCLI(unittest.TestCase):
    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        cmd = [_python_cmd(), "-m", "mmo"] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
            env=_env(),
        )

    def test_profile_list_text(self) -> None:
        result = self._run(["profile", "list"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("PROFILE.USER.CONSERVATIVE", result.stdout)
        self.assertIn("PROFILE.USER.BROADCAST", result.stdout)
        self.assertIn("PROFILE.USER.CLUB", result.stdout)

    def test_profile_list_json(self) -> None:
        result = self._run(["profile", "list", "--format", "json"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        rows = json.loads(result.stdout)
        self.assertIsInstance(rows, list)
        ids = [r["profile_id"] for r in rows]
        self.assertEqual(ids, sorted(ids))

    def test_profile_list_json_deterministic(self) -> None:
        first = self._run(["profile", "list", "--format", "json"]).stdout
        second = self._run(["profile", "list", "--format", "json"]).stdout
        self.assertEqual(first, second)

    def test_profile_show_known_id_text(self) -> None:
        result = self._run(["profile", "show", "PROFILE.USER.CONSERVATIVE"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("PROFILE.USER.CONSERVATIVE", result.stdout)
        self.assertIn("Conservative", result.stdout)

    def test_profile_show_known_id_json(self) -> None:
        result = self._run(["profile", "show", "PROFILE.USER.BROADCAST", "--format", "json"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload.get("profile_id"), "PROFILE.USER.BROADCAST")
        self.assertIn("gate_overrides", payload)
        self.assertIn("param_bounds", payload)

    def test_profile_show_unknown_id_exits_1(self) -> None:
        result = self._run(["profile", "show", "PROFILE.USER.DOESNOTEXIST"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("PROFILE.USER.DOESNOTEXIST", result.stderr)

    def test_profile_apply_no_scene_json(self) -> None:
        result = self._run(["profile", "apply", "PROFILE.USER.CLUB"])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload.get("profile_id"), "PROFILE.USER.CLUB")
        self.assertIn("gate_options", payload)
        self.assertIsInstance(payload["gate_options"], dict)
        self.assertIn("lfe_boost_warn_db", payload["gate_options"])
        self.assertEqual(payload["scene_issues"], [])

    def test_profile_apply_with_scene_detects_confidence_issue(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            scene_data = {"metadata": {"confidence": 0.1, "correlation": 0.0}}
            json.dump(scene_data, tmp)
            tmp_path = tmp.name
        try:
            result = self._run([
                "profile", "apply", "PROFILE.USER.CONSERVATIVE",
                "--scene", tmp_path,
            ])
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(result.stdout)
            issues = payload.get("scene_issues", [])
            self.assertGreater(len(issues), 0, msg="Expected scene issues for low confidence")
            codes = [iss.get("code") for iss in issues]
            self.assertIn("PROFILE.SCENE_CONFIDENCE_TOO_LOW", codes)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_profile_apply_unknown_id_exits_1(self) -> None:
        result = self._run(["profile", "apply", "PROFILE.USER.GHOST"])
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
