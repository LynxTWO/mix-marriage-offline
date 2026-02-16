import unittest
from pathlib import Path

from mmo.core.registries.gates_registry import GatesRegistry, load_gates_registry

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GATES_PATH = _REPO_ROOT / "ontology" / "policies" / "gates.yaml"


class TestGatesRegistryLoad(unittest.TestCase):
    def test_load_success_deterministic(self) -> None:
        first = load_gates_registry(_GATES_PATH)
        second = load_gates_registry(_GATES_PATH)
        self.assertEqual(first.get_policy_ids(), second.get_policy_ids())
        self.assertEqual(first.get_gate_ids(), second.get_gate_ids())

    def test_policy_ids_sorted(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        ids = reg.get_policy_ids()
        self.assertEqual(ids, sorted(ids))

    def test_known_policy_present(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        ids = reg.get_policy_ids()
        self.assertIn("POLICY.GATES.CORE_V0", ids)

    def test_gate_ids_sorted(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        ids = reg.get_gate_ids()
        self.assertEqual(ids, sorted(ids))

    def test_known_gates_present(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        ids = reg.get_gate_ids()
        self.assertIn("GATE.NO_CLIP", ids)
        self.assertIn("GATE.REQUIRES_APPROVAL", ids)

    def test_gate_count_positive(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        self.assertGreater(len(reg), 0)

    def test_meta_present(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        meta = reg.meta
        self.assertIsInstance(meta, dict)
        self.assertIn("gates_version", meta)


class TestGatesRegistryUniqueness(unittest.TestCase):
    def test_policy_ids_unique(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        ids = reg.get_policy_ids()
        self.assertEqual(len(ids), len(set(ids)))

    def test_gate_ids_unique(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        ids = reg.get_gate_ids()
        self.assertEqual(len(ids), len(set(ids)))


class TestGatesRegistryGetPolicy(unittest.TestCase):
    def test_get_policy_success(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        policy = reg.get_policy("POLICY.GATES.CORE_V0")
        self.assertIsInstance(policy, dict)
        self.assertEqual(policy["policy_id"], "POLICY.GATES.CORE_V0")
        self.assertIn("gates", policy)
        self.assertIsInstance(policy["gates"], dict)
        self.assertIn("GATE.NO_CLIP", policy["gates"])

    def test_get_policy_returns_copy(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        a = reg.get_policy("POLICY.GATES.CORE_V0")
        b = reg.get_policy("POLICY.GATES.CORE_V0")
        self.assertEqual(a, b)
        self.assertIsNot(a, b)

    def test_get_policy_unknown_error_deterministic(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        known_ids = reg.get_policy_ids()
        expected = (
            "Unknown policy_id: POLICY.GATES.NONEXISTENT. "
            f"Known policy_ids: {', '.join(known_ids)}"
        )

        with self.assertRaises(ValueError) as first:
            reg.get_policy("POLICY.GATES.NONEXISTENT")
        with self.assertRaises(ValueError) as second:
            reg.get_policy("POLICY.GATES.NONEXISTENT")

        self.assertEqual(str(first.exception), str(second.exception))
        self.assertEqual(str(first.exception), expected)

    def test_get_policy_empty_id_error(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        with self.assertRaises(ValueError) as ctx:
            reg.get_policy("")
        self.assertEqual(
            str(ctx.exception), "policy_id must be a non-empty string."
        )


class TestGatesRegistryGetGate(unittest.TestCase):
    def test_get_gate_success(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        gate = reg.get_gate("GATE.NO_CLIP")
        self.assertIsInstance(gate, dict)
        self.assertIn("label", gate)
        self.assertIn("kind", gate)

    def test_get_gate_returns_copy(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        a = reg.get_gate("GATE.NO_CLIP")
        b = reg.get_gate("GATE.NO_CLIP")
        self.assertEqual(a, b)
        self.assertIsNot(a, b)

    def test_get_gate_unknown_error_deterministic(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        known_ids = reg.get_gate_ids()
        expected = (
            "Unknown gate_id: GATE.NONEXISTENT. "
            f"Known gate_ids: {', '.join(known_ids)}"
        )

        with self.assertRaises(ValueError) as first:
            reg.get_gate("GATE.NONEXISTENT")
        with self.assertRaises(ValueError) as second:
            reg.get_gate("GATE.NONEXISTENT")

        self.assertEqual(str(first.exception), str(second.exception))
        self.assertEqual(str(first.exception), expected)

    def test_get_gate_empty_id_error(self) -> None:
        reg = load_gates_registry(_GATES_PATH)
        with self.assertRaises(ValueError) as ctx:
            reg.get_gate("")
        self.assertEqual(
            str(ctx.exception), "gate_id must be a non-empty string."
        )


class TestGatesRegistryDeterministicOrdering(unittest.TestCase):
    def test_all_gates_deterministic(self) -> None:
        reg1 = load_gates_registry(_GATES_PATH)
        reg2 = load_gates_registry(_GATES_PATH)
        ids1 = reg1.get_gate_ids()
        ids2 = reg2.get_gate_ids()
        self.assertEqual(ids1, ids2)
        for gid in ids1:
            self.assertEqual(reg1.get_gate(gid), reg2.get_gate(gid))


if __name__ == "__main__":
    unittest.main()
