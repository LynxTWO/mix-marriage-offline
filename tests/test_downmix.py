from __future__ import annotations

from pathlib import Path
from unittest import TestCase

from mmo.dsp.downmix import (
    build_matrix,
    load_downmix_registry,
    load_layouts,
    load_policy_pack,
    resolve_conversion,
)

_TC = TestCase()

def test_build_matrix_5_1_to_2_0_lfe_drop() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    layouts = load_layouts(repo_root / "ontology" / "layouts.yaml")
    registry = load_downmix_registry(repo_root / "ontology" / "policies" / "downmix.yaml")
    pack = load_policy_pack(
        registry, "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0", repo_root
    )
    matrix = build_matrix(layouts, pack, "DMX.STD.5_1_TO_2_0.LO_RO_LFE_DROP")

    assert len(matrix["coeffs"]) == 2
    assert len(matrix["coeffs"][0]) == 6

    source_index = {spk: idx for idx, spk in enumerate(matrix["source_speakers"])}
    target_index = {spk: idx for idx, spk in enumerate(matrix["target_speakers"])}

    left_row = matrix["coeffs"][target_index["SPK.L"]]
    right_row = matrix["coeffs"][target_index["SPK.R"]]

    _TC.assertAlmostEqual(left_row[source_index["SPK.L"]], 1.0, places=6)
    _TC.assertAlmostEqual(left_row[source_index["SPK.LFE"]], 0.0, places=6)
    _TC.assertAlmostEqual(left_row[source_index["SPK.C"]], 0.7071, places=4)
    _TC.assertAlmostEqual(left_row[source_index["SPK.LS"]], 0.7071, places=4)

    _TC.assertAlmostEqual(right_row[source_index["SPK.R"]], 1.0, places=6)
    _TC.assertAlmostEqual(right_row[source_index["SPK.C"]], 0.7071, places=4)
    _TC.assertAlmostEqual(right_row[source_index["SPK.RS"]], 0.7071, places=4)


def test_resolve_conversion_direct_exists() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    layouts = load_layouts(repo_root / "ontology" / "layouts.yaml")
    registry = load_downmix_registry(repo_root / "ontology" / "policies" / "downmix.yaml")

    matrix = resolve_conversion(
        layouts,
        registry,
        repo_root,
        source_layout_id="LAYOUT.5_1",
        target_layout_id="LAYOUT.2_0",
    )

    assert matrix["matrix_id"] == "DMX.STD.5_1_TO_2_0.LO_RO_LFE_DROP"


def test_compose_path_for_7_1_4_to_2_0() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    layouts = load_layouts(repo_root / "ontology" / "layouts.yaml")
    registry = load_downmix_registry(repo_root / "ontology" / "policies" / "downmix.yaml")

    matrix = resolve_conversion(
        layouts,
        registry,
        repo_root,
        source_layout_id="LAYOUT.7_1_4",
        target_layout_id="LAYOUT.2_0",
    )

    assert "steps" in matrix
    assert len(matrix["coeffs"]) == 2
    assert len(matrix["coeffs"][0]) == 12
