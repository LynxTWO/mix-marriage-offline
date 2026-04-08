from __future__ import annotations

import unittest

from mmo.core.render_plan import build_render_plan

# Minimal single-target render_targets dict
_STEREO_TARGET = {
    "targets": [{"target_id": "TARGET.STEREO.2_0", "layout_id": "LAYOUT.2_0"}]
}
_51_TARGET = {
    "targets": [{"target_id": "TARGET.SURROUND.5_1", "layout_id": "LAYOUT.5_1"}]
}


def _plan(
    scene=None,
    render_targets=None,
    *,
    routing_plan_path=None,
    output_formats=None,
    contexts=None,
    policies=None,
):
    return build_render_plan(
        scene if scene is not None else {},
        render_targets if render_targets is not None else _STEREO_TARGET,
        routing_plan_path=routing_plan_path,
        output_formats=output_formats if output_formats is not None else ["wav"],
        contexts=contexts if contexts is not None else ["render"],
        policies=policies,
    )


class TestRenderPlanChaos(unittest.TestCase):
    # ------------------------------------------------------------------
    # Bad inputs that must raise
    # ------------------------------------------------------------------

    def test_non_dict_scene_raises(self) -> None:
        with self.assertRaises(ValueError) as exc:
            build_render_plan(
                "not a dict",
                _STEREO_TARGET,
                routing_plan_path=None,
                output_formats=["wav"],
                contexts=["render"],
                policies=None,
            )
        self.assertIn("scene", str(exc.exception).lower())

    def test_non_dict_render_targets_raises(self) -> None:
        with self.assertRaises(ValueError) as exc:
            build_render_plan(
                {},
                ["not", "a", "dict"],
                routing_plan_path=None,
                output_formats=["wav"],
                contexts=["render"],
                policies=None,
            )
        self.assertIn("render_targets", str(exc.exception).lower())

    def test_empty_targets_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            _plan(render_targets={"targets": []})

    def test_target_missing_layout_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            _plan(render_targets={"targets": [{"target_id": "TARGET.STEREO.2_0"}]})

    def test_target_missing_target_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            _plan(render_targets={"targets": [{"layout_id": "LAYOUT.2_0"}]})

    # ------------------------------------------------------------------
    # Output format normalization
    # ------------------------------------------------------------------

    def test_unknown_output_formats_fall_back_to_wav(self) -> None:
        plan = _plan(output_formats=["mp5", "xyzzy", "notaformat"])
        for job in plan["jobs"]:
            self.assertEqual(job["output_formats"], ["wav"])

    def test_duplicate_output_formats_deduplicated(self) -> None:
        plan = _plan(output_formats=["wav", "wav", "wav"])
        for job in plan["jobs"]:
            self.assertEqual(job["output_formats"].count("wav"), 1)

    def test_empty_output_formats_defaults_to_wav(self) -> None:
        plan = _plan(output_formats=[])
        for job in plan["jobs"]:
            self.assertEqual(job["output_formats"], ["wav"])

    # ------------------------------------------------------------------
    # Context normalization
    # ------------------------------------------------------------------

    def test_invalid_contexts_fall_back_to_render(self) -> None:
        plan = _plan(contexts=["nuke_everything", "yolo"])
        for job in plan["jobs"]:
            self.assertEqual(job["contexts"], ["render"])

    def test_empty_contexts_defaults_to_render(self) -> None:
        plan = _plan(contexts=[])
        for job in plan["jobs"]:
            self.assertEqual(job["contexts"], ["render"])

    # ------------------------------------------------------------------
    # Routing plan path behaviour
    # ------------------------------------------------------------------

    def test_routing_plan_path_defaulted_when_source_differs_from_target(self) -> None:
        # Source layout (5.1) differs from target (stereo) → routing needed.
        # render_plan reads source_layout_id from scene["source"]["layout_id"]
        # or scene["metadata"]["source_layout_id"].
        scene = {"source": {"layout_id": "LAYOUT.5_1"}}
        plan = _plan(scene=scene, render_targets=_STEREO_TARGET, routing_plan_path=None)
        job = plan["jobs"][0]
        self.assertIn("routing_plan_path", job)
        self.assertEqual(job["routing_plan_path"], "routing_plan.json")

    def test_no_routing_plan_when_source_matches_target(self) -> None:
        # Source layout (2.0) equals target (stereo) → no routing needed.
        scene = {"source": {"layout_id": "LAYOUT.2_0"}}
        plan = _plan(scene=scene, render_targets=_STEREO_TARGET, routing_plan_path=None)
        job = plan["jobs"][0]
        self.assertNotIn("routing_plan_path", job)

    def test_source_layout_also_read_from_metadata(self) -> None:
        # Alternative location: scene["metadata"]["source_layout_id"]
        scene = {"metadata": {"source_layout_id": "LAYOUT.5_1"}}
        plan = _plan(scene=scene, render_targets=_STEREO_TARGET, routing_plan_path=None)
        job = plan["jobs"][0]
        self.assertIn("routing_plan_path", job)

    def test_explicit_routing_plan_path_used_when_provided(self) -> None:
        plan = _plan(routing_plan_path="custom/my_routing.json")
        for job in plan["jobs"]:
            self.assertEqual(job["routing_plan_path"], "custom/my_routing.json")

    # ------------------------------------------------------------------
    # Plan ID stability and differentiation
    # ------------------------------------------------------------------

    def test_plan_id_stable_for_identical_inputs(self) -> None:
        plan_a = _plan()
        plan_b = _plan()
        self.assertEqual(plan_a["plan_id"], plan_b["plan_id"])

    def test_plan_id_differs_when_target_changes(self) -> None:
        plan_stereo = _plan(render_targets=_STEREO_TARGET)
        plan_51 = _plan(render_targets=_51_TARGET)
        self.assertNotEqual(plan_stereo["plan_id"], plan_51["plan_id"])

    def test_targets_list_in_plan_is_sorted(self) -> None:
        multi = {
            "targets": [
                {"target_id": "TARGET.SURROUND.5_1", "layout_id": "LAYOUT.5_1"},
                {"target_id": "TARGET.STEREO.2_0", "layout_id": "LAYOUT.2_0"},
            ]
        }
        plan = _plan(render_targets=multi)
        self.assertEqual(
            plan["targets"],
            sorted(plan["targets"]),
        )

    # ------------------------------------------------------------------
    # Job structure
    # ------------------------------------------------------------------

    def test_single_target_produces_one_job(self) -> None:
        plan = _plan()
        self.assertEqual(len(plan["jobs"]), 1)

    def test_two_targets_produce_two_jobs(self) -> None:
        multi = {
            "targets": [
                {"target_id": "TARGET.STEREO.2_0", "layout_id": "LAYOUT.2_0"},
                {"target_id": "TARGET.SURROUND.5_1", "layout_id": "LAYOUT.5_1"},
            ]
        }
        plan = _plan(render_targets=multi)
        self.assertEqual(len(plan["jobs"]), 2)

    def test_job_ids_are_sequential_and_zero_padded(self) -> None:
        multi = {
            "targets": [
                {"target_id": "TARGET.STEREO.2_0", "layout_id": "LAYOUT.2_0"},
                {"target_id": "TARGET.SURROUND.5_1", "layout_id": "LAYOUT.5_1"},
            ]
        }
        plan = _plan(render_targets=multi)
        job_ids = [job["job_id"] for job in plan["jobs"]]
        self.assertIn("JOB.001", job_ids)
        self.assertIn("JOB.002", job_ids)

    def test_policies_propagated_when_provided(self) -> None:
        plan = _plan(policies={"gates_policy_id": "POLICY.GATES.STRICT"})
        self.assertEqual(plan["policies"].get("gates_policy_id"), "POLICY.GATES.STRICT")

    def test_empty_scene_does_not_crash(self) -> None:
        plan = _plan(scene={})
        self.assertEqual(len(plan["jobs"]), 1)


if __name__ == "__main__":
    unittest.main()
