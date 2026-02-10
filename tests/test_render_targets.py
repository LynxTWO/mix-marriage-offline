import json
import unittest
from pathlib import Path

import jsonschema
import yaml

from mmo.core.render_targets import (
    get_render_target,
    list_render_targets,
    load_render_targets,
)
from mmo.core.speaker_positions import get_layout_positions
from mmo.dsp.downmix import load_layouts


def _geometry_rows(positions: object) -> list[tuple[int, float, float]]:
    if not isinstance(positions, list):
        return []

    rows: list[tuple[int, float, float]] = []
    for position in positions:
        if not isinstance(position, dict):
            continue
        ch = position.get("ch")
        azimuth_deg = position.get("azimuth_deg")
        elevation_deg = position.get("elevation_deg")
        if (
            isinstance(ch, bool)
            or not isinstance(ch, int)
            or isinstance(azimuth_deg, bool)
            or not isinstance(azimuth_deg, (int, float))
            or isinstance(elevation_deg, bool)
            or not isinstance(elevation_deg, (int, float))
        ):
            continue
        rows.append((ch, float(azimuth_deg), float(elevation_deg)))
    return rows


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

    def test_load_render_targets_layout_ids_exist_in_layouts_yaml(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_render_targets(repo_root / "ontology" / "render_targets.yaml")
        self.assertEqual(registry.get("schema_version"), "0.1.0")

        layouts = load_layouts(repo_root / "ontology" / "layouts.yaml")
        targets = registry.get("targets")
        self.assertIsInstance(targets, list)
        if not isinstance(targets, list):
            return
        for target in targets:
            if not isinstance(target, dict):
                continue
            layout_id = target.get("layout_id")
            if isinstance(layout_id, str):
                self.assertIn(layout_id, layouts)

    def test_load_render_targets_resolves_speaker_positions_refs(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        registry = load_render_targets(repo_root / "ontology" / "render_targets.yaml")
        targets = registry.get("targets")
        self.assertIsInstance(targets, list)
        if not isinstance(targets, list):
            return

        speaker_positions_path = repo_root / "ontology" / "speaker_positions.yaml"
        for target in targets:
            if not isinstance(target, dict):
                continue
            layout_id = target.get("layout_id")
            if not isinstance(layout_id, str):
                continue

            resolved_positions = _geometry_rows(target.get("speaker_positions"))
            canonical_positions = _geometry_rows(
                get_layout_positions(layout_id, speaker_positions_path)
            )
            self.assertEqual(resolved_positions, canonical_positions)
            self.assertEqual(
                [ch for ch, _, _ in resolved_positions],
                sorted(ch for ch, _, _ in resolved_positions),
            )
            self.assertNotIn("speaker_positions_ref", target)

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


if __name__ == "__main__":
    unittest.main()
