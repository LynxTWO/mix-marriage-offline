import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from mmo.cli import main


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _minimal_report_payload() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "report_id": "REPORT.CLI.TARGETS.RECOMMEND",
    }


def _minimal_scene_payload(*, beds: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "scene_id": "SCENE.CLI.TARGETS.RECOMMEND",
        "beds": beds,
    }


class TestCliTargetsRecommend(unittest.TestCase):
    def _run_main(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(args)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def _assert_deterministic_success(self, args: list[str]) -> tuple[str, str]:
        first_exit, first_stdout, first_stderr = self._run_main(args)
        second_exit, second_stdout, second_stderr = self._run_main(args)
        self.assertEqual(first_exit, 0, msg=first_stderr)
        self.assertEqual(second_exit, 0, msg=second_stderr)
        self.assertEqual(first_stdout, second_stdout)
        self.assertEqual(first_stderr, second_stderr)
        return first_stdout, first_stderr

    def test_targets_recommend_baseline_stereo_is_rank_1(self) -> None:
        exit_code, stdout, stderr = self._run_main(
            ["targets", "recommend", "--format", "json"]
        )
        self.assertEqual(exit_code, 0, msg=stderr)
        self.assertEqual(stderr, "")

        payload = json.loads(stdout)
        self.assertIsInstance(payload, list)
        self.assertTrue(payload)
        first = payload[0]
        self.assertEqual(first.get("target_id"), "TARGET.STEREO.2_0")
        self.assertEqual(first.get("rank"), 1)
        self.assertEqual(first.get("reasons"), ["Baseline stereo reality check."])

    def test_targets_recommend_uses_routing_plan_layout_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            out_dir = temp_path / "run_out"
            report_path = out_dir / "report.json"
            report_payload = _minimal_report_payload()
            report_payload["routing_plan"] = {"target_layout_id": "LAYOUT.5_1"}
            _write_json(report_path, report_payload)

            exit_code, stdout, stderr = self._run_main(
                [
                    "targets",
                    "recommend",
                    "--report",
                    str(out_dir),
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(exit_code, 0, msg=stderr)
            self.assertEqual(stderr, "")

            payload = json.loads(stdout)
            first = payload[0]
            self.assertEqual(first.get("target_id"), "TARGET.STEREO.2_0")
            self.assertEqual(first.get("rank"), 1)

            by_target = {
                row.get("target_id"): row for row in payload if isinstance(row, dict)
            }
            surround = by_target.get("TARGET.SURROUND.5_1")
            self.assertIsInstance(surround, dict)
            if isinstance(surround, dict):
                self.assertIn("Routing plan targets LAYOUT.5_1", surround.get("reasons", []))

    def test_targets_recommend_scene_diffuse_thresholds_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            scene_path = temp_path / "scene.json"
            _write_json(
                scene_path,
                _minimal_scene_payload(
                    beds=[
                        {
                            "bed_id": "BED.BETA.FIELD",
                            "intent": {"diffuse": 0.90},
                        },
                        {
                            "bed_id": "BED.ALPHA.FIELD",
                            "intent": {"diffuse": 0.80},
                        },
                    ]
                ),
            )

            stdout, stderr = self._assert_deterministic_success(
                [
                    "targets",
                    "recommend",
                    "--scene",
                    str(scene_path),
                    "--format",
                    "json",
                ]
            )
            self.assertEqual(stderr, "")

            payload = json.loads(stdout)
            target_ids = [
                row.get("target_id")
                for row in payload
                if isinstance(row, dict) and isinstance(row.get("target_id"), str)
            ]
            self.assertEqual(
                target_ids,
                ["TARGET.STEREO.2_0", "TARGET.SURROUND.5_1", "TARGET.SURROUND.7_1"],
            )

            by_target = {
                row.get("target_id"): row for row in payload if isinstance(row, dict)
            }
            surround_5_1 = by_target.get("TARGET.SURROUND.5_1")
            surround_7_1 = by_target.get("TARGET.SURROUND.7_1")
            self.assertIsInstance(surround_5_1, dict)
            self.assertIsInstance(surround_7_1, dict)
            if isinstance(surround_5_1, dict):
                reasons_5_1 = surround_5_1.get("reasons", [])
                self.assertIsInstance(reasons_5_1, list)
                self.assertEqual(reasons_5_1, sorted(reasons_5_1))
                self.assertTrue(any("BED.ALPHA.FIELD" in reason for reason in reasons_5_1))
                self.assertTrue(any("BED.BETA.FIELD" in reason for reason in reasons_5_1))
                self.assertTrue(any("0.80" in reason for reason in reasons_5_1))
                self.assertTrue(any("0.90" in reason for reason in reasons_5_1))
                self.assertTrue(any("0.75" in reason for reason in reasons_5_1))
            if isinstance(surround_7_1, dict):
                reasons_7_1 = surround_7_1.get("reasons", [])
                self.assertEqual(reasons_7_1, sorted(reasons_7_1))
                self.assertTrue(any("BED.BETA.FIELD" in reason for reason in reasons_7_1))
                self.assertTrue(any("0.90" in reason for reason in reasons_7_1))
                self.assertTrue(any("0.85" in reason for reason in reasons_7_1))

    def test_targets_recommend_text_stdout_stderr_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            out_dir = temp_path / "run_out"
            report_path = out_dir / "report.json"
            scene_path = out_dir / "scene.json"

            report_payload = _minimal_report_payload()
            report_payload["routing_plan"] = {"target_layout_id": "LAYOUT.5_1"}
            _write_json(report_path, report_payload)
            _write_json(
                scene_path,
                _minimal_scene_payload(
                    beds=[{"bed_id": "BED.FIELD.001", "intent": {"diffuse": 0.90}}]
                ),
            )

            stdout, stderr = self._assert_deterministic_success(
                [
                    "targets",
                    "recommend",
                    "--report",
                    str(out_dir),
                    "--max",
                    "3",
                    "--format",
                    "text",
                ]
            )
            self.assertEqual(stderr, "")
            self.assertIn("Recommended targets:", stdout)
            self.assertIn("TARGET.STEREO.2_0", stdout)


if __name__ == "__main__":
    unittest.main()
