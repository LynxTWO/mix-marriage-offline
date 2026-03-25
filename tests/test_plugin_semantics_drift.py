"""Guard against drift between Python plugin semantics constants and ontology YAML.

src/mmo/core/plugin_registry.py defines frozenset constants for valid plugin
semantics values (channel modes, link groups, latency types, etc.).  The
canonical source of truth for these values is ontology/plugin_semantics.yaml.

This test loads both and asserts they agree.  If either side adds or removes a
value without updating the other, CI fails with a precise diff.
"""

import unittest
from pathlib import Path

import yaml

from mmo.core.plugin_registry import (
    _VALID_CHANNEL_MODES,
    _VALID_LATENCY_TYPES,
    _VALID_LAYOUT_SAFETY,
    _VALID_LINK_GROUPS,
    _VALID_SCENE_SCOPES,
    _VALID_SEED_POLICIES,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SEMANTICS_PATH = REPO_ROOT / "ontology" / "plugin_semantics.yaml"

# Each entry maps: (YAML top-level key, Python frozenset)
_SEMANTICS_PAIRS: list[tuple[str, str, frozenset[str]]] = [
    ("channel_mode", "_VALID_CHANNEL_MODES", _VALID_CHANNEL_MODES),
    ("supported_link_groups", "_VALID_LINK_GROUPS", _VALID_LINK_GROUPS),
    ("latency", "_VALID_LATENCY_TYPES", _VALID_LATENCY_TYPES),
    ("deterministic_seed_policy", "_VALID_SEED_POLICIES", _VALID_SEED_POLICIES),
    ("scene_scope", "_VALID_SCENE_SCOPES", _VALID_SCENE_SCOPES),
    ("layout_safety", "_VALID_LAYOUT_SAFETY", _VALID_LAYOUT_SAFETY),
]


class TestPluginSemanticsDrift(unittest.TestCase):
    """Assert Python frozensets match ontology/plugin_semantics.yaml values."""

    @classmethod
    def setUpClass(cls) -> None:
        with SEMANTICS_PATH.open("r", encoding="utf-8") as fh:
            cls._yaml_data: dict = yaml.safe_load(fh)

    def test_all_semantics_fields_match_yaml(self) -> None:
        for yaml_key, python_name, python_set in _SEMANTICS_PAIRS:
            with self.subTest(yaml_key=yaml_key, python_name=python_name):
                section = self._yaml_data.get(yaml_key)
                self.assertIsInstance(
                    section,
                    dict,
                    f"ontology/plugin_semantics.yaml missing top-level key '{yaml_key}'",
                )
                yaml_values = frozenset(section.get("values", {}).keys())
                only_in_python = python_set - yaml_values
                only_in_yaml = yaml_values - python_set
                self.assertEqual(
                    only_in_python,
                    frozenset(),
                    f"{python_name} has values not in YAML '{yaml_key}': "
                    f"{sorted(only_in_python)}",
                )
                self.assertEqual(
                    only_in_yaml,
                    frozenset(),
                    f"YAML '{yaml_key}' has values not in {python_name}: "
                    f"{sorted(only_in_yaml)}",
                )


if __name__ == "__main__":
    unittest.main()
