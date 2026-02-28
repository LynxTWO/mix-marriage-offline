import tempfile
import unittest
from pathlib import Path

import yaml

from mmo.core.registries.render_targets_registry import load_render_targets_registry


class TestRenderTargetsRegistry(unittest.TestCase):
    def test_load_registry_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry_path = repo_root / "ontology" / "render_targets.yaml"

        first = load_render_targets_registry(registry_path)
        second = load_render_targets_registry(registry_path)

        self.assertEqual(first.to_payload(), second.to_payload())
        self.assertEqual(first.list_target_ids(), sorted(first.list_target_ids()))

    def test_find_targets_for_layout_is_sorted(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_render_targets_registry(repo_root / "ontology" / "render_targets.yaml")

        rows = registry.find_targets_for_layout("LAYOUT.5_1")
        target_ids = [
            row.get("target_id")
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("target_id"), str)
        ]
        self.assertEqual(target_ids, sorted(target_ids))
        self.assertEqual(target_ids, ["TARGET.SURROUND.5_1"])

    def test_binaural_target_present_and_maps_to_binaural_layout(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_render_targets_registry(repo_root / "ontology" / "render_targets.yaml")
        target = registry.get_target("TARGET.HEADPHONES.BINAURAL")
        self.assertEqual(target.get("layout_id"), "LAYOUT.BINAURAL")
        self.assertEqual(target.get("container"), "wav")

    def test_new_targets_present_and_mapped_to_expected_layouts(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_render_targets_registry(repo_root / "ontology" / "render_targets.yaml")
        self.assertEqual(registry.get_target("TARGET.STEREO.2_1").get("layout_id"), "LAYOUT.2_1")
        self.assertEqual(registry.get_target("TARGET.FRONT.3_0").get("layout_id"), "LAYOUT.3_0")
        self.assertEqual(registry.get_target("TARGET.FRONT.3_1").get("layout_id"), "LAYOUT.3_1")
        self.assertEqual(registry.get_target("TARGET.SURROUND.4_0").get("layout_id"), "LAYOUT.4_0")
        self.assertEqual(registry.get_target("TARGET.SURROUND.4_1").get("layout_id"), "LAYOUT.4_1")

    def test_find_stereo_target_variants_for_layout_is_sorted(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_render_targets_registry(repo_root / "ontology" / "render_targets.yaml")

        rows = registry.find_targets_for_layout("LAYOUT.2_0")
        target_ids = [
            row.get("target_id")
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("target_id"), str)
        ]
        self.assertEqual(
            target_ids,
            ["TARGET.STEREO.2_0", "TARGET.STEREO.2_0_ALT"],
        )

    def test_get_target_unknown_lists_known_ids_sorted(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_render_targets_registry(repo_root / "ontology" / "render_targets.yaml")

        with self.assertRaises(ValueError) as ctx:
            registry.get_target("TARGET.DOES.NOT.EXIST")
        message = str(ctx.exception)

        self.assertIn("Unknown target_id: TARGET.DOES.NOT.EXIST.", message)
        self.assertIn("TARGET.STEREO.2_0", message)
        self.assertIn("TARGET.SURROUND.5_1", message)
        self.assertLess(message.index("TARGET.STEREO.2_0"), message.index("TARGET.SURROUND.5_1"))

    def test_duplicate_target_ids_fail_deterministically(self) -> None:
        payload = {
            "schema_version": "0.1.0",
            "targets": [
                {
                    "target_id": "TARGET.STEREO.2_0",
                    "layout_id": "LAYOUT.2_0",
                    "container": "wav",
                    "channel_order_layout_id": "LAYOUT.2_0",
                    "filename_template": "renders/stereo_2_0/mix.{container}",
                },
                {
                    "target_id": "TARGET.STEREO.2_0",
                    "layout_id": "LAYOUT.2_0",
                    "container": "wav",
                    "channel_order_layout_id": "LAYOUT.2_0",
                    "filename_template": "renders/stereo_2_0_alt/mix.{container}",
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "render_targets.yaml"
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

            with self.assertRaises(ValueError) as ctx:
                load_render_targets_registry(path)
            self.assertEqual(
                str(ctx.exception),
                f"Render targets must be unique by target_id: {path}",
            )


if __name__ == "__main__":
    unittest.main()
