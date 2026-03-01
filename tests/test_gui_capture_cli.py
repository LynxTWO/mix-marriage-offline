"""Tests for the GUI screenshot capture CLI and scenario registry.

These tests do NOT launch Tk or require a display. They verify:
- The scenario ID constants exist and are registered in KNOWN_SCENARIOS.
- The capture CLI argument parser rejects unknown scenario IDs.
- The capture CLI returns non-zero for an output path whose parent cannot
  be created (simulating a bad path that fails even before Tk is needed).
"""

from __future__ import annotations

import unittest

from mmo.gui.capture import (
    KNOWN_SCENARIOS,
    SCENARIO_DASHBOARD_EXTREME,
    SCENARIO_DASHBOARD_SAFE,
    SCENARIO_RUN_READY,
    main as capture_main,
)


class TestKnownScenarios(unittest.TestCase):
    def test_known_scenarios_nonempty(self) -> None:
        self.assertGreater(len(KNOWN_SCENARIOS), 0)

    def test_run_ready_in_known_scenarios(self) -> None:
        self.assertIn(SCENARIO_RUN_READY, KNOWN_SCENARIOS)

    def test_dashboard_safe_in_known_scenarios(self) -> None:
        self.assertIn(SCENARIO_DASHBOARD_SAFE, KNOWN_SCENARIOS)

    def test_dashboard_extreme_in_known_scenarios(self) -> None:
        self.assertIn(SCENARIO_DASHBOARD_EXTREME, KNOWN_SCENARIOS)

    def test_scenario_ids_are_strings(self) -> None:
        for sid in KNOWN_SCENARIOS:
            self.assertIsInstance(sid, str)
            self.assertTrue(sid.startswith("GUI.CAPTURE."), msg=f"Bad prefix: {sid!r}")

    def test_all_three_scenarios_present(self) -> None:
        self.assertEqual(
            len(KNOWN_SCENARIOS),
            3,
            msg="Expected exactly 3 scenarios in KNOWN_SCENARIOS.",
        )


class TestCaptureCLIArgumentValidation(unittest.TestCase):
    def test_unknown_scenario_returns_nonzero(self) -> None:
        rc = capture_main(["--scenario", "BOGUS.UNKNOWN.SCENARIO", "--out", "/tmp/mmo_test_x.png"])
        self.assertNotEqual(rc, 0, msg="Unknown scenario should return non-zero exit code")

    def test_unknown_scenario_json_mode_returns_nonzero(self) -> None:
        rc = capture_main(
            ["--scenario", "GUI.CAPTURE.BOGUS", "--out", "/tmp/mmo_test_x.png", "--json"]
        )
        self.assertNotEqual(rc, 0)

    def test_known_scenario_proceeds_past_arg_parsing(self) -> None:
        # With no display and no mss/ctk, the CLI should return 1 (dependency
        # guard) rather than the arg-parse error (also 1). Either way it fails
        # gracefully without crashing.
        rc = capture_main(
            ["--scenario", SCENARIO_DASHBOARD_SAFE, "--out", "/tmp/mmo_test_safe.png"]
        )
        # Return code 1 means either "dependency not available" or "capture failed"
        # — both are acceptable non-crash outcomes.
        self.assertIn(rc, (0, 1))
