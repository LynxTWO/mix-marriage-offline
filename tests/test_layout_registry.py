import unittest
from pathlib import Path

from mmo.core.registries.layout_registry import LayoutRegistry, load_layout_registry

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAYOUTS_PATH = _REPO_ROOT / "ontology" / "layouts.yaml"


class TestLayoutRegistryLoad(unittest.TestCase):
    def test_load_success_deterministic(self) -> None:
        first = load_layout_registry(_LAYOUTS_PATH)
        second = load_layout_registry(_LAYOUTS_PATH)
        self.assertEqual(first.list_layout_ids(), second.list_layout_ids())

    def test_layout_ids_sorted(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        ids = reg.list_layout_ids()
        self.assertEqual(ids, sorted(ids))

    def test_known_layouts_present(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        ids = reg.list_layout_ids()
        self.assertIn("LAYOUT.1_0", ids)
        self.assertIn("LAYOUT.2_0", ids)
        self.assertIn("LAYOUT.5_1", ids)
        self.assertIn("LAYOUT.7_1_4", ids)

    def test_layout_count_positive(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        self.assertGreater(len(reg), 0)

    def test_meta_present(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        meta = reg.meta
        self.assertIsInstance(meta, dict)
        self.assertIn("layouts_version", meta)


class TestLayoutRegistryUniqueness(unittest.TestCase):
    def test_layout_ids_unique(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        ids = reg.list_layout_ids()
        self.assertEqual(len(ids), len(set(ids)))

    def test_channel_order_no_duplicates_per_layout(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        for layout_id in reg.list_layout_ids():
            layout = reg.get_layout(layout_id)
            channel_order = layout["channel_order"]
            self.assertEqual(
                len(channel_order),
                len(set(channel_order)),
                f"{layout_id} has duplicate channels in channel_order",
            )


class TestLayoutRegistryGetLayout(unittest.TestCase):
    def test_get_layout_returns_channel_order(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        layout = reg.get_layout("LAYOUT.5_1")
        self.assertIsInstance(layout["channel_order"], list)
        self.assertEqual(layout["channel_count"], 6)

    def test_get_layout_returns_copy(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        a = reg.get_layout("LAYOUT.5_1")
        b = reg.get_layout("LAYOUT.5_1")
        self.assertEqual(a, b)
        self.assertIsNot(a, b)

    def test_get_layout_contains(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        self.assertIn("LAYOUT.5_1", reg)
        self.assertNotIn("LAYOUT.NONEXISTENT", reg)

    def test_get_layout_unknown_error_deterministic(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        known_ids = reg.list_layout_ids()
        expected = (
            "Unknown layout_id: LAYOUT.NONEXISTENT. "
            f"Known layout_ids: {', '.join(known_ids)}"
        )

        with self.assertRaises(ValueError) as first:
            reg.get_layout("LAYOUT.NONEXISTENT")
        with self.assertRaises(ValueError) as second:
            reg.get_layout("LAYOUT.NONEXISTENT")

        self.assertEqual(str(first.exception), str(second.exception))
        self.assertEqual(str(first.exception), expected)

    def test_get_layout_empty_id_error(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        with self.assertRaises(ValueError) as ctx:
            reg.get_layout("")
        self.assertEqual(
            str(ctx.exception), "layout_id must be a non-empty string."
        )

    def test_get_layout_whitespace_id_error(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        with self.assertRaises(ValueError) as ctx:
            reg.get_layout("   ")
        self.assertEqual(
            str(ctx.exception), "layout_id must be a non-empty string."
        )


class TestLayoutRegistryDeterministicOrdering(unittest.TestCase):
    def test_all_layouts_deterministic(self) -> None:
        reg = load_layout_registry(_LAYOUTS_PATH)
        first_ids = reg.list_layout_ids()
        first_layouts = [reg.get_layout(lid) for lid in first_ids]

        reg2 = load_layout_registry(_LAYOUTS_PATH)
        second_ids = reg2.list_layout_ids()
        second_layouts = [reg2.get_layout(lid) for lid in second_ids]

        self.assertEqual(first_ids, second_ids)
        self.assertEqual(first_layouts, second_layouts)


if __name__ == "__main__":
    unittest.main()
