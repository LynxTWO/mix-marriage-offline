from __future__ import annotations

import unittest
from unittest import mock

from mmo.core.target_tokens import resolve_target_token


class _FakeLayoutRegistry:
    def __init__(self, rows: dict[str, dict[str, object]]) -> None:
        self._rows = dict(rows)

    def list_layout_ids(self) -> list[str]:
        return sorted(self._rows.keys())

    def get_layout(self, layout_id: str) -> dict[str, object]:
        row = self._rows.get(layout_id)
        if row is None:
            raise ValueError(f"Unknown layout_id: {layout_id}")
        return dict(row)


class _FakeRenderTargetsRegistry:
    def __init__(
        self,
        *,
        targets: dict[str, dict[str, object]],
        by_layout: dict[str, list[str]],
    ) -> None:
        self._targets = {
            target_id: dict(payload)
            for target_id, payload in targets.items()
        }
        self._by_layout = {
            layout_id: list(sorted(target_ids))
            for layout_id, target_ids in by_layout.items()
        }

    def get_target(self, target_id: str) -> dict[str, object]:
        row = self._targets.get(target_id)
        if row is None:
            raise ValueError(f"Unknown target_id: {target_id}")
        return dict(row)

    def find_targets_for_layout(self, layout_id: str) -> list[dict[str, object]]:
        return [
            {"target_id": target_id}
            for target_id in self._by_layout.get(layout_id, [])
        ]


class TestTargetTokenResolver(unittest.TestCase):
    def test_target_id_resolves_to_layout(self) -> None:
        resolved = resolve_target_token("TARGET.SURROUND.5_1")
        self.assertEqual(resolved.target_id, "TARGET.SURROUND.5_1")
        self.assertEqual(resolved.layout_id, "LAYOUT.5_1")
        self.assertEqual(resolved.source, "target_id")

    def test_layout_id_resolves_to_layout(self) -> None:
        resolved = resolve_target_token("LAYOUT.5_1")
        self.assertEqual(resolved.target_id, "TARGET.SURROUND.5_1")
        self.assertEqual(resolved.layout_id, "LAYOUT.5_1")
        self.assertEqual(resolved.source, "layout_id")

    def test_shorthands_resolve_deterministically(self) -> None:
        stereo = resolve_target_token("stereo")
        self.assertEqual(stereo.target_id, "TARGET.STEREO.2_0")
        self.assertEqual(stereo.layout_id, "LAYOUT.2_0")
        self.assertEqual(stereo.source, "shorthand")

        immersive = resolve_target_token("7.1.4")
        self.assertEqual(immersive.target_id, "TARGET.IMMERSIVE.7_1_4")
        self.assertEqual(immersive.layout_id, "LAYOUT.7_1_4")
        self.assertEqual(immersive.source, "shorthand")

    def test_binaural_shorthand_is_gated_until_layout_exists(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_target_token("binaural")
        self.assertIn("LAYOUT.BINAURAL is not defined", str(ctx.exception))

    def test_alias_matching_supports_target_and_layout_aliases(self) -> None:
        target_alias = resolve_target_token("Stereo (streaming)")
        self.assertEqual(target_alias.target_id, "TARGET.STEREO.2_0")
        self.assertEqual(target_alias.layout_id, "LAYOUT.2_0")
        self.assertEqual(target_alias.source, "alias")

        layout_alias = resolve_target_token("surround51")
        self.assertEqual(layout_alias.layout_id, "LAYOUT.5_1")
        self.assertEqual(layout_alias.target_id, "TARGET.SURROUND.5_1")
        self.assertEqual(layout_alias.source, "alias")

    def test_ambiguity_lists_sorted_candidates(self) -> None:
        fake_layout_registry = _FakeLayoutRegistry(
            {
                "LAYOUT.B": {"label": "Beta", "aliases": ["shared"]},
                "LAYOUT.A": {"label": "Alpha", "aliases": ["shared"]},
            }
        )
        fake_target_registry = _FakeRenderTargetsRegistry(
            targets={},
            by_layout={},
        )

        with mock.patch(
            "mmo.core.target_tokens.load_layout_registry",
            return_value=fake_layout_registry,
        ), mock.patch(
            "mmo.core.target_tokens.load_render_targets_registry",
            return_value=fake_target_registry,
        ), mock.patch(
            "mmo.core.target_tokens.resolve_render_target_id",
            side_effect=ValueError("Unknown render target token: shared."),
        ):
            with self.assertRaises(ValueError) as ctx:
                resolve_target_token("shared")

        self.assertEqual(
            str(ctx.exception),
            "Ambiguous target token: shared. Candidates: LAYOUT.A, LAYOUT.B",
        )


if __name__ == "__main__":
    unittest.main()
