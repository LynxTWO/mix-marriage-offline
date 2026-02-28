from __future__ import annotations

import math
from pathlib import Path
from unittest import TestCase

from mmo.dsp.downmix import (
    apply_matrix_to_audio,
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


def test_resolve_conversion_dual_lfe_stereo_paths_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    layouts = load_layouts(repo_root / "ontology" / "layouts.yaml")
    registry = load_downmix_registry(repo_root / "ontology" / "policies" / "downmix.yaml")

    matrix_52 = resolve_conversion(
        layouts,
        registry,
        repo_root,
        source_layout_id="LAYOUT.5_2",
        target_layout_id="LAYOUT.2_0",
    )
    assert matrix_52["matrix_id"] == "DMX.STD.5_2_TO_2_0.LO_RO_LFE_DROP"

    matrix_72 = resolve_conversion(
        layouts,
        registry,
        repo_root,
        source_layout_id="LAYOUT.7_2",
        target_layout_id="LAYOUT.2_0",
    )
    assert matrix_72["matrix_id"] == "DMX.STD.7_2_TO_2_0.LO_RO_COMPOSED"


def _rms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return (sum(float(value) ** 2 for value in samples) / float(len(samples))) ** 0.5


def test_apply_matrix_honors_source_pre_filters_for_lfe() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    layouts = load_layouts(repo_root / "ontology" / "layouts.yaml")
    registry = load_downmix_registry(repo_root / "ontology" / "policies" / "downmix.yaml")
    pack = load_policy_pack(
        registry, "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0", repo_root
    )
    matrix = build_matrix(layouts, pack, "DMX.STD.5_1_TO_2_0.LO_RO_LFE_MIX")

    source_speakers = matrix["source_speakers"]
    lfe_index = source_speakers.index("SPK.LFE")
    source_channels = len(source_speakers)
    frames = 4096
    sample_rate_hz = 48000
    source_interleaved: list[float] = []
    for frame in range(frames):
        lfe = 0.8 * math.sin(2.0 * math.pi * 240.0 * frame / sample_rate_hz)
        for channel_index in range(source_channels):
            source_interleaved.append(lfe if channel_index == lfe_index else 0.0)

    unfiltered = apply_matrix_to_audio(
        matrix["coeffs"],
        source_interleaved,
        source_channels,
        target_channels=2,
    )
    filtered = apply_matrix_to_audio(
        matrix["coeffs"],
        source_interleaved,
        source_channels,
        target_channels=2,
        source_pre_filters=matrix.get("source_pre_filters"),
        source_speakers=source_speakers,
        sample_rate_hz=sample_rate_hz,
    )
    _TC.assertLess(_rms(filtered), _rms(unfiltered) * 0.7)


def test_source_pre_filters_are_deterministic() -> None:
    coeffs = [[1.0], [1.0]]
    source = [0.25] * 1024
    kwargs = {
        "source_pre_filters": {
            "SPK.LFE": [{"type": "highpass", "freq_hz": 120, "slope_db_per_oct": 24}]
        },
        "source_speakers": ["SPK.LFE"],
        "sample_rate_hz": 48000,
    }
    first = apply_matrix_to_audio(
        coeffs,
        source,
        source_channels=1,
        target_channels=2,
        **kwargs,
    )
    second = apply_matrix_to_audio(
        coeffs,
        source,
        source_channels=1,
        target_channels=2,
        **kwargs,
    )
    _TC.assertEqual(first, second)
