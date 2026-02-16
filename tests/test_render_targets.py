import json
import unittest
from pathlib import Path
from unittest import mock

import jsonschema
import yaml

from mmo.core.render_targets import (
    get_render_target,
    list_render_targets,
    load_render_targets,
    resolve_render_target_id,
)


class TestRenderTargetsRegistry(unittest.TestCase):
    def test_render_targets_yaml_validates_against_schema(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        schema_path = repo_root / "schemas" / "render_targets.schema.json"
        registry_path = repo_root / "ontology" / "render_targets.yaml"

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [])

    def test_load_render_targets_is_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        targets_path = repo_root / "ontology" / "render_targets.yaml"

        first = load_render_targets(targets_path)
        second = load_render_targets(targets_path)
        self.assertEqual(first, second)
        self.assertEqual(first.get("schema_version"), "0.1.0")

        targets = first.get("targets")
        self.assertIsInstance(targets, list)
        if not isinstance(targets, list):
            return
        for target in targets:
            if not isinstance(target, dict):
                continue
            self.assertIn("target_id", target)
            self.assertIn("layout_id", target)
            self.assertIn("container", target)
            self.assertIn("channel_order", target)
            self.assertIn("filename_template", target)

    def test_list_and_get_render_targets_are_deterministic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        targets_path = repo_root / "ontology" / "render_targets.yaml"

        first = list_render_targets(targets_path)
        second = list_render_targets(targets_path)
        self.assertEqual(first, second)

        target_ids = [
            item.get("target_id")
            for item in first
            if isinstance(item, dict) and isinstance(item.get("target_id"), str)
        ]
        self.assertEqual(target_ids, sorted(target_ids))
        self.assertIn("TARGET.STEREO.2_0", target_ids)

        stereo = get_render_target("TARGET.STEREO.2_0", targets_path)
        self.assertIsInstance(stereo, dict)
        if isinstance(stereo, dict):
            self.assertEqual(stereo.get("layout_id"), "LAYOUT.2_0")

    def test_resolve_render_target_id_accepts_casefold_exact_id(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        targets_path = repo_root / "ontology" / "render_targets.yaml"
        self.assertEqual(
            resolve_render_target_id(" target.stereo.2_0 ", targets_path),
            "TARGET.STEREO.2_0",
        )

    def test_resolve_render_target_id_reports_unknown_with_sorted_available_targets(self) -> None:
        with mock.patch(
            "mmo.core.render_targets.load_render_targets_registry",
        ) as mocked_loader:
            registry = mock.Mock()
            registry.list_target_ids.return_value = [
                "TARGET.STEREO.2_0",
                "TARGET.SURROUND.5_1",
            ]
            mocked_loader.return_value = registry
            with self.assertRaises(ValueError) as ctx:
                resolve_render_target_id("nope")
        self.assertEqual(
            str(ctx.exception),
            (
                "Unknown render target token: nope. Available targets: "
                "TARGET.STEREO.2_0, TARGET.SURROUND.5_1"
            ),
        )


if __name__ == "__main__":
    unittest.main()
