import unittest
from pathlib import Path

from mmo.core.registries.downmix_registry import DownmixRegistry, load_downmix_registry

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOWNMIX_PATH = _REPO_ROOT / "ontology" / "policies" / "downmix.yaml"


class TestDownmixRegistryLoad(unittest.TestCase):
    def test_load_success_deterministic(self) -> None:
        first = load_downmix_registry(_DOWNMIX_PATH)
        second = load_downmix_registry(_DOWNMIX_PATH)
        self.assertEqual(first.list_policy_ids(), second.list_policy_ids())

    def test_policy_ids_sorted(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        ids = reg.list_policy_ids()
        self.assertEqual(ids, sorted(ids))

    def test_known_policies_present(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        ids = reg.list_policy_ids()
        self.assertIn("POLICY.DOWNMIX.STANDARD_FOLDOWN_V0", ids)
        self.assertIn("POLICY.DOWNMIX.IMMERSIVE_FOLDOWN_V0", ids)

    def test_policy_count_positive(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        self.assertGreater(len(reg), 0)

    def test_meta_present(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        meta = reg.meta
        self.assertIsInstance(meta, dict)
        self.assertIn("downmix_registry_version", meta)


class TestDownmixRegistryUniqueness(unittest.TestCase):
    def test_policy_ids_unique(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        ids = reg.list_policy_ids()
        self.assertEqual(len(ids), len(set(ids)))


class TestDownmixRegistryGetPolicy(unittest.TestCase):
    def test_get_policy_success(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        policy = reg.get_policy("POLICY.DOWNMIX.STANDARD_FOLDOWN_V0")
        self.assertIsInstance(policy, dict)
        self.assertIn("label", policy)

    def test_get_policy_returns_copy(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        a = reg.get_policy("POLICY.DOWNMIX.STANDARD_FOLDOWN_V0")
        b = reg.get_policy("POLICY.DOWNMIX.STANDARD_FOLDOWN_V0")
        self.assertEqual(a, b)
        self.assertIsNot(a, b)

    def test_get_policy_unknown_error_deterministic(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        known_ids = reg.list_policy_ids()
        expected = (
            "Unknown policy_id: POLICY.DOWNMIX.NONEXISTENT. "
            f"Known policy_ids: {', '.join(known_ids)}"
        )

        with self.assertRaises(ValueError) as first:
            reg.get_policy("POLICY.DOWNMIX.NONEXISTENT")
        with self.assertRaises(ValueError) as second:
            reg.get_policy("POLICY.DOWNMIX.NONEXISTENT")

        self.assertEqual(str(first.exception), str(second.exception))
        self.assertEqual(str(first.exception), expected)

    def test_get_policy_empty_id_error(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        with self.assertRaises(ValueError) as ctx:
            reg.get_policy("")
        self.assertEqual(
            str(ctx.exception), "policy_id must be a non-empty string."
        )


class TestDownmixRegistryDefaultPolicy(unittest.TestCase):
    def test_default_policy_for_known_source(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        result = reg.default_policy_for_source("LAYOUT.5_1")
        self.assertEqual(result, "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0")

    def test_default_policy_for_immersive_source(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        result = reg.default_policy_for_source("LAYOUT.7_1_4")
        self.assertEqual(result, "POLICY.DOWNMIX.IMMERSIVE_FOLDOWN_V0")

    def test_default_policy_for_unknown_source(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        result = reg.default_policy_for_source("LAYOUT.NONEXISTENT")
        self.assertIsNone(result)


class TestDownmixRegistryResolve(unittest.TestCase):
    def test_resolve_direct_conversion(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        result = reg.resolve(None, "LAYOUT.5_1", "LAYOUT.2_0")
        self.assertEqual(result["source_layout_id"], "LAYOUT.5_1")
        self.assertEqual(result["target_layout_id"], "LAYOUT.2_0")
        self.assertIn("matrix_id", result)
        self.assertEqual(
            result["matrix_id"], "DMX.STD.5_1_TO_2_0.LO_RO_LFE_DROP"
        )

    def test_resolve_direct_with_explicit_policy(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        result = reg.resolve(
            "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0",
            "LAYOUT.5_1",
            "LAYOUT.2_0",
        )
        self.assertEqual(result["matrix_id"], "DMX.STD.5_1_TO_2_0.LO_RO_LFE_DROP")
        self.assertEqual(result["policy_id"], "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0")

    def test_resolve_composition_path(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        result = reg.resolve(None, "LAYOUT.5_1_4", "LAYOUT.2_0")
        self.assertEqual(result["source_layout_id"], "LAYOUT.5_1_4")
        self.assertEqual(result["target_layout_id"], "LAYOUT.2_0")
        self.assertIn("steps", result)
        self.assertIsInstance(result["steps"], list)
        self.assertGreater(len(result["steps"]), 0)

    def test_resolve_deterministic(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)
        first = reg.resolve(None, "LAYOUT.5_1", "LAYOUT.2_0")
        second = reg.resolve(None, "LAYOUT.5_1", "LAYOUT.2_0")
        self.assertEqual(first, second)

    def test_resolve_unknown_source_error_deterministic(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)

        with self.assertRaises(ValueError) as first:
            reg.resolve(None, "LAYOUT.NONEXISTENT", "LAYOUT.2_0")
        with self.assertRaises(ValueError) as second:
            reg.resolve(None, "LAYOUT.NONEXISTENT", "LAYOUT.2_0")

        self.assertEqual(str(first.exception), str(second.exception))
        self.assertIn("No conversion found", str(first.exception))
        self.assertIn("Known source layouts", str(first.exception))

    def test_resolve_unknown_target_error_deterministic(self) -> None:
        reg = load_downmix_registry(_DOWNMIX_PATH)

        with self.assertRaises(ValueError) as first:
            reg.resolve(None, "LAYOUT.5_1", "LAYOUT.NONEXISTENT")
        with self.assertRaises(ValueError) as second:
            reg.resolve(None, "LAYOUT.5_1", "LAYOUT.NONEXISTENT")

        self.assertEqual(str(first.exception), str(second.exception))

    def test_resolve_direct_takes_priority_over_composition(self) -> None:
        """When a direct conversion exists, it takes priority over composition."""
        reg = load_downmix_registry(_DOWNMIX_PATH)
        result = reg.resolve(None, "LAYOUT.7_1_4", "LAYOUT.2_0")
        # 7_1_4 -> 2_0 has both a direct conversion and composition path;
        # direct should win.
        self.assertIn("matrix_id", result)
        self.assertNotIn("steps", result)


class TestDownmixRegistryDeterministicOrdering(unittest.TestCase):
    def test_all_policies_deterministic(self) -> None:
        reg1 = load_downmix_registry(_DOWNMIX_PATH)
        reg2 = load_downmix_registry(_DOWNMIX_PATH)
        ids1 = reg1.list_policy_ids()
        ids2 = reg2.list_policy_ids()
        self.assertEqual(ids1, ids2)
        for pid in ids1:
            self.assertEqual(reg1.get_policy(pid), reg2.get_policy(pid))


if __name__ == "__main__":
    unittest.main()
