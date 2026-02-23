"""Contract validation tests for ontology/layouts.yaml and ontology/downmix.yaml.

Tests:
- layouts.yaml validates against schemas/layouts.schema.json
- downmix.yaml validates against schemas/downmix.schema.json
- Every layout entry has required canonical fields
- speaker_positions cover all channels in channel_order (when present)
- lfe_policy is consistent with has_lfe
- Downmix matrix dimensions are correct for key conversions
- layout_negotiation.py public API works end-to-end
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest import TestCase

import jsonschema
import yaml

from mmo.core.layout_negotiation import (
    get_channel_count,
    get_downmix_lfe_routing,
    get_downmix_similarity_policy,
    get_layout_channel_order,
    get_layout_info,
    get_layout_lfe_policy,
    get_layout_speaker_positions,
    get_lfe_channels,
    has_lfe,
    is_downmix_path_available,
    list_supported_layouts,
    load_downmix_contract,
    load_layouts_registry,
)

_TC = TestCase()
_REPO_ROOT = Path(__file__).resolve().parents[1]
_LAYOUTS_YAML = _REPO_ROOT / "ontology" / "layouts.yaml"
_DOWNMIX_YAML = _REPO_ROOT / "ontology" / "downmix.yaml"
_LAYOUTS_SCHEMA = _REPO_ROOT / "schemas" / "layouts.schema.json"
_DOWNMIX_SCHEMA = _REPO_ROOT / "schemas" / "downmix.schema.json"

# Minimum set of layouts that must be present
_REQUIRED_LAYOUTS = [
    "LAYOUT.1_0",
    "LAYOUT.2_0",
    "LAYOUT.2_1",
    "LAYOUT.3_0",
    "LAYOUT.4_0",
    "LAYOUT.4_1",
    "LAYOUT.5_0",
    "LAYOUT.5_1",
    "LAYOUT.7_0",
    "LAYOUT.7_1",
    "LAYOUT.5_1_2",
    "LAYOUT.5_1_4",
    "LAYOUT.7_1_2",
    "LAYOUT.7_1_4",
]

# Layouts that MUST have LFE
_LFE_LAYOUTS = {
    "LAYOUT.2_1",
    "LAYOUT.4_1",
    "LAYOUT.5_1",
    "LAYOUT.7_1",
    "LAYOUT.5_1_2",
    "LAYOUT.5_1_4",
    "LAYOUT.7_1_2",
    "LAYOUT.7_1_4",
}

# Layouts that must NOT have LFE
_NO_LFE_LAYOUTS = {
    "LAYOUT.1_0",
    "LAYOUT.2_0",
    "LAYOUT.3_0",
    "LAYOUT.4_0",
    "LAYOUT.5_0",
    "LAYOUT.7_0",
}

# Expected channel counts
_EXPECTED_CHANNEL_COUNTS: Dict[str, int] = {
    "LAYOUT.1_0": 1,
    "LAYOUT.2_0": 2,
    "LAYOUT.2_1": 3,
    "LAYOUT.3_0": 3,
    "LAYOUT.4_0": 4,
    "LAYOUT.4_1": 5,
    "LAYOUT.5_0": 5,
    "LAYOUT.5_1": 6,
    "LAYOUT.7_0": 7,
    "LAYOUT.7_1": 8,
    "LAYOUT.5_1_2": 8,
    "LAYOUT.5_1_4": 10,
    "LAYOUT.7_1_2": 10,
    "LAYOUT.7_1_4": 12,
}


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_layouts_yaml_validates_against_schema() -> None:
    schema = json.loads(_LAYOUTS_SCHEMA.read_text(encoding="utf-8"))
    payload = yaml.safe_load(_LAYOUTS_YAML.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        msgs = [f"  {'.'.join(str(p) for p in e.path) or '$'}: {e.message}" for e in errors]
        raise AssertionError("layouts.yaml schema validation failed:\n" + "\n".join(msgs))


def test_downmix_yaml_validates_against_schema() -> None:
    schema = json.loads(_DOWNMIX_SCHEMA.read_text(encoding="utf-8"))
    payload = yaml.safe_load(_DOWNMIX_YAML.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        msgs = [f"  {'.'.join(str(p) for p in e.path) or '$'}: {e.message}" for e in errors]
        raise AssertionError("downmix.yaml schema validation failed:\n" + "\n".join(msgs))


# ---------------------------------------------------------------------------
# Layouts registry contract tests
# ---------------------------------------------------------------------------


def test_all_required_layouts_present() -> None:
    layouts = load_layouts_registry(_LAYOUTS_YAML)
    missing = [lid for lid in _REQUIRED_LAYOUTS if lid not in layouts]
    assert not missing, f"Required layouts missing: {missing}"


def test_layouts_sorted_deterministically() -> None:
    layouts = load_layouts_registry(_LAYOUTS_YAML)
    ids = list(layouts.keys())
    assert ids == sorted(ids), "Layouts must be returned in sorted order"


def test_layout_channel_counts_correct() -> None:
    for layout_id, expected in _EXPECTED_CHANNEL_COUNTS.items():
        count = get_channel_count(layout_id, _LAYOUTS_YAML)
        assert count == expected, (
            f"{layout_id}: expected channel_count={expected}, got {count}"
        )


def test_channel_order_length_matches_channel_count() -> None:
    layouts = load_layouts_registry(_LAYOUTS_YAML)
    for layout_id, entry in layouts.items():
        channel_order = entry.get("channel_order")
        channel_count = entry.get("channel_count")
        if not isinstance(channel_order, list) or not isinstance(channel_count, int):
            continue
        assert len(channel_order) == channel_count, (
            f"{layout_id}: channel_order length {len(channel_order)} "
            f"!= channel_count {channel_count}"
        )


def test_channel_order_all_spk_ids() -> None:
    layouts = load_layouts_registry(_LAYOUTS_YAML)
    for layout_id, entry in layouts.items():
        channel_order = entry.get("channel_order", [])
        for ch in channel_order:
            assert isinstance(ch, str) and ch.startswith("SPK."), (
                f"{layout_id}: channel_order entry {ch!r} must start with 'SPK.'"
            )


def test_lfe_layouts_have_lfe_flag_set() -> None:
    for layout_id in _LFE_LAYOUTS:
        assert has_lfe(layout_id, _LAYOUTS_YAML), (
            f"{layout_id}: expected has_lfe=True"
        )
        lfe_chs = get_lfe_channels(layout_id, _LAYOUTS_YAML)
        assert lfe_chs, f"{layout_id}: expected non-empty lfe_channels"


def test_no_lfe_layouts_have_lfe_flag_false() -> None:
    for layout_id in _NO_LFE_LAYOUTS:
        assert not has_lfe(layout_id, _LAYOUTS_YAML), (
            f"{layout_id}: expected has_lfe=False"
        )
        lfe_chs = get_lfe_channels(layout_id, _LAYOUTS_YAML)
        assert lfe_chs == [], f"{layout_id}: expected empty lfe_channels, got {lfe_chs}"


def test_lfe_policy_present_for_all_required_layouts() -> None:
    for layout_id in _REQUIRED_LAYOUTS:
        policy = get_layout_lfe_policy(layout_id, _LAYOUTS_YAML)
        assert policy is not None, f"{layout_id}: missing lfe_policy"
        assert "excluded_from_program_loudness" in policy, (
            f"{layout_id}: lfe_policy missing excluded_from_program_loudness"
        )
        assert policy["excluded_from_program_loudness"] is True, (
            f"{layout_id}: LFE must always be excluded from program loudness (BS.1770)"
        )


def test_speaker_positions_cover_channel_order() -> None:
    layouts = load_layouts_registry(_LAYOUTS_YAML)
    for layout_id, entry in layouts.items():
        positions = entry.get("speaker_positions")
        if positions is None:
            continue  # optional key
        channel_order = entry.get("channel_order", [])
        pos_spk_ids = {p["spk_id"] for p in positions if isinstance(p, dict) and "spk_id" in p}
        for ch in channel_order:
            assert ch in pos_spk_ids, (
                f"{layout_id}: channel_order has {ch} but speaker_positions missing it"
            )


def test_speaker_positions_count_matches_channel_count() -> None:
    for layout_id in _REQUIRED_LAYOUTS:
        positions = get_layout_speaker_positions(layout_id, _LAYOUTS_YAML)
        if positions is None:
            continue
        count = get_channel_count(layout_id, _LAYOUTS_YAML)
        assert len(positions) == count, (
            f"{layout_id}: speaker_positions has {len(positions)} entries, "
            f"expected {count}"
        )


def test_speaker_positions_azimuth_bounds() -> None:
    for layout_id in _REQUIRED_LAYOUTS:
        positions = get_layout_speaker_positions(layout_id, _LAYOUTS_YAML)
        if positions is None:
            continue
        for pos in positions:
            az = pos["azimuth_deg"]
            el = pos["elevation_deg"]
            assert -180 <= az <= 180, (
                f"{layout_id}/{pos['spk_id']}: azimuth {az} out of [-180,180]"
            )
            assert -90 <= el <= 90, (
                f"{layout_id}/{pos['spk_id']}: elevation {el} out of [-90,90]"
            )


def test_stereo_speaker_positions_symmetric() -> None:
    positions = get_layout_speaker_positions("LAYOUT.2_0", _LAYOUTS_YAML)
    assert positions is not None
    pos_map = {p["spk_id"]: p for p in positions}
    l_az = pos_map["SPK.L"]["azimuth_deg"]
    r_az = pos_map["SPK.R"]["azimuth_deg"]
    # L should be positive (left) and R negative (right) per speakers.yaml convention
    assert l_az > 0, f"SPK.L azimuth should be positive (left), got {l_az}"
    assert r_az < 0, f"SPK.R azimuth should be negative (right), got {r_az}"
    assert abs(abs(l_az) - abs(r_az)) < 1e-9, "L/R azimuths must be symmetric"


def test_layout_negotiation_returns_none_for_unknown() -> None:
    assert get_layout_info("LAYOUT.DOES_NOT_EXIST", _LAYOUTS_YAML) is None
    assert get_channel_count("LAYOUT.DOES_NOT_EXIST", _LAYOUTS_YAML) is None
    assert get_layout_speaker_positions("LAYOUT.DOES_NOT_EXIST", _LAYOUTS_YAML) is None
    assert get_layout_lfe_policy("LAYOUT.DOES_NOT_EXIST", _LAYOUTS_YAML) is None
    assert get_lfe_channels("LAYOUT.DOES_NOT_EXIST", _LAYOUTS_YAML) == []
    assert not has_lfe("LAYOUT.DOES_NOT_EXIST", _LAYOUTS_YAML)


def test_list_supported_layouts_sorted() -> None:
    layouts = list_supported_layouts(_LAYOUTS_YAML)
    assert layouts == sorted(layouts)
    for lid in _REQUIRED_LAYOUTS:
        assert lid in layouts, f"Required layout {lid} not in list_supported_layouts()"


# ---------------------------------------------------------------------------
# Downmix contract tests
# ---------------------------------------------------------------------------


def test_downmix_contract_loads() -> None:
    data = load_downmix_contract(_DOWNMIX_YAML)
    assert "downmix" in data
    dm = data["downmix"]
    assert "_meta" in dm
    assert "lfe_routing" in dm
    assert "similarity_policy" in dm
    assert "supported_conversions" in dm
    assert "matrices" in dm


def test_downmix_lfe_routing_policy() -> None:
    routing = get_downmix_lfe_routing(_DOWNMIX_YAML)
    assert routing is not None
    assert routing.get("bs1770_lfe_weight") == 0.0, "LFE BS.1770 weight must be 0.0"
    assert routing.get("excluded_from_program_loudness") is True
    assert routing.get("default_treatment_in_downmix") == "drop"
    dual = routing.get("dual_lfe_policy", {})
    assert dual.get("x_2_is_dual_program") is False, (
        ".2 layouts must not be assumed to carry dual program content"
    )


def test_downmix_similarity_policy_has_required_fields() -> None:
    policy = get_downmix_similarity_policy(_DOWNMIX_YAML)
    assert policy is not None
    assert policy.get("required_minimum_target") == "LAYOUT.2_0", (
        "Minimum similarity gate must be to stereo"
    )
    assert "metrics" in policy
    assert "failure_policy" in policy


def test_downmix_conversions_reference_known_layouts() -> None:
    layouts = load_layouts_registry(_LAYOUTS_YAML)
    data = load_downmix_contract(_DOWNMIX_YAML)
    conversions = data["downmix"].get("supported_conversions", [])
    for conv in conversions:
        src = conv.get("source_layout_id", "")
        tgt = conv.get("target_layout_id", "")
        assert src in layouts, f"Conversion {conv.get('id')}: unknown source {src}"
        assert tgt in layouts, f"Conversion {conv.get('id')}: unknown target {tgt}"


def test_downmix_matrices_reference_known_layouts() -> None:
    layouts = load_layouts_registry(_LAYOUTS_YAML)
    data = load_downmix_contract(_DOWNMIX_YAML)
    matrices = data["downmix"].get("matrices", {})
    for matrix_id, matrix in matrices.items():
        src = matrix.get("source_layout_id", "")
        tgt = matrix.get("target_layout_id", "")
        assert src in layouts, f"Matrix {matrix_id}: unknown source layout {src}"
        assert tgt in layouts, f"Matrix {matrix_id}: unknown target layout {tgt}"


def test_downmix_matrix_coefficients_source_channels_known() -> None:
    layouts = load_layouts_registry(_LAYOUTS_YAML)
    data = load_downmix_contract(_DOWNMIX_YAML)
    matrices = data["downmix"].get("matrices", {})
    for matrix_id, matrix in matrices.items():
        src_id = matrix.get("source_layout_id", "")
        tgt_id = matrix.get("target_layout_id", "")
        src_layout = layouts.get(src_id, {})
        tgt_layout = layouts.get(tgt_id, {})
        src_chs = set(src_layout.get("channel_order", []))
        tgt_chs = set(tgt_layout.get("channel_order", []))
        coefficients = matrix.get("coefficients", {})
        for tgt_spk, src_map in coefficients.items():
            assert tgt_spk in tgt_chs, (
                f"Matrix {matrix_id}: target channel {tgt_spk} not in {tgt_id}.channel_order"
            )
            if isinstance(src_map, dict):
                for src_spk in src_map:
                    assert src_spk in src_chs, (
                        f"Matrix {matrix_id}: source channel {src_spk} not in {src_id}.channel_order"
                    )


def test_downmix_5_1_to_2_0_matrix_coefficients() -> None:
    data = load_downmix_contract(_DOWNMIX_YAML)
    matrices = data["downmix"].get("matrices", {})
    matrix = matrices.get("DMX.STD.5_1_TO_2_0.LO_RO_LFE_DROP")
    assert matrix is not None, "Expected matrix DMX.STD.5_1_TO_2_0.LO_RO_LFE_DROP"
    coefficients = matrix["coefficients"]

    # L row
    l_row = coefficients["SPK.L"]
    _TC.assertAlmostEqual(l_row["SPK.L"], 1.0, places=6)
    _TC.assertAlmostEqual(l_row["SPK.C"], 0.7071, places=4)
    _TC.assertAlmostEqual(l_row["SPK.LS"], 0.7071, places=4)
    assert "SPK.LFE" not in l_row, "LFE must not appear in drop matrix"

    # R row
    r_row = coefficients["SPK.R"]
    _TC.assertAlmostEqual(r_row["SPK.R"], 1.0, places=6)
    _TC.assertAlmostEqual(r_row["SPK.C"], 0.7071, places=4)
    _TC.assertAlmostEqual(r_row["SPK.RS"], 0.7071, places=4)
    assert "SPK.LFE" not in r_row, "LFE must not appear in drop matrix"


def test_downmix_7_1_4_to_2_0_matrix_references_all_channels() -> None:
    data = load_downmix_contract(_DOWNMIX_YAML)
    matrices = data["downmix"].get("matrices", {})
    matrix = matrices.get("DMX.IMM.7_1_4_TO_2_0.COMPOSED")
    assert matrix is not None, "Expected matrix DMX.IMM.7_1_4_TO_2_0.COMPOSED"
    assert matrix["lfe_treatment"] == "drop"
    coefficients = matrix["coefficients"]
    assert "SPK.L" in coefficients
    assert "SPK.R" in coefficients
    # Heights must appear in the composed matrix
    l_row = coefficients["SPK.L"]
    assert "SPK.TFL" in l_row, "Composed matrix must include TFL contribution"
    assert "SPK.TRL" in l_row, "Composed matrix must include TRL contribution"


# ---------------------------------------------------------------------------
# layout_negotiation module integration (uses default paths via ontology_dir())
# ---------------------------------------------------------------------------


def test_layout_info_5_1_via_default_paths() -> None:
    info = get_layout_info("LAYOUT.5_1")
    assert info is not None
    assert info["channel_count"] == 6
    assert info["has_lfe"] is True
    order = info["channel_order"]
    assert "SPK.C" in order
    assert "SPK.LFE" in order


def test_channel_order_5_1_via_default_paths() -> None:
    order = get_layout_channel_order("LAYOUT.5_1")
    assert order == ["SPK.L", "SPK.R", "SPK.C", "SPK.LFE", "SPK.LS", "SPK.RS"]


def test_speaker_positions_7_1_4_via_default_paths() -> None:
    positions = get_layout_speaker_positions("LAYOUT.7_1_4")
    assert positions is not None
    assert len(positions) == 12
    spk_ids = [p["spk_id"] for p in positions]
    assert "SPK.TFL" in spk_ids
    assert "SPK.TRR" in spk_ids


def test_lfe_routing_via_default_paths() -> None:
    routing = get_downmix_lfe_routing()
    assert routing is not None
    assert routing["bs1770_lfe_weight"] == 0.0
    assert routing["excluded_from_program_loudness"] is True


def test_similarity_policy_via_default_paths() -> None:
    policy = get_downmix_similarity_policy()
    assert policy is not None
    assert policy["required_minimum_target"] == "LAYOUT.2_0"


# ---------------------------------------------------------------------------
# Downmix round-trip tests (end-to-end via dsp.downmix + policy packs)
# ---------------------------------------------------------------------------


def test_downmix_path_5_1_to_2_0_available() -> None:
    assert is_downmix_path_available("LAYOUT.5_1", "LAYOUT.2_0")


def test_downmix_path_7_1_to_5_1_available() -> None:
    assert is_downmix_path_available("LAYOUT.7_1", "LAYOUT.5_1")


def test_downmix_path_7_1_4_to_2_0_available() -> None:
    assert is_downmix_path_available("LAYOUT.7_1_4", "LAYOUT.2_0")


def test_downmix_path_unavailable_for_unknown_layout() -> None:
    assert not is_downmix_path_available("LAYOUT.UNKNOWN_XYZ", "LAYOUT.2_0")


def test_downmix_matrix_5_1_to_2_0_round_trip() -> None:
    """Build the matrix via dsp.downmix and verify it matches the contract."""
    from mmo.dsp.downmix import build_matrix, load_downmix_registry, load_layouts, load_policy_pack

    layouts = load_layouts(_LAYOUTS_YAML)
    registry = load_downmix_registry(_REPO_ROOT / "ontology" / "policies" / "downmix.yaml")
    pack = load_policy_pack(registry, "POLICY.DOWNMIX.STANDARD_FOLDOWN_V0", _REPO_ROOT)
    matrix = build_matrix(layouts, pack, "DMX.STD.5_1_TO_2_0.LO_RO_LFE_DROP")

    assert matrix["source_layout_id"] == "LAYOUT.5_1"
    assert matrix["target_layout_id"] == "LAYOUT.2_0"
    assert len(matrix["coeffs"]) == 2       # 2 target channels
    assert len(matrix["coeffs"][0]) == 6    # 6 source channels

    src_idx = {spk: i for i, spk in enumerate(matrix["source_speakers"])}
    tgt_idx = {spk: i for i, spk in enumerate(matrix["target_speakers"])}

    l_row = matrix["coeffs"][tgt_idx["SPK.L"]]
    _TC.assertAlmostEqual(l_row[src_idx["SPK.L"]], 1.0, places=6)
    _TC.assertAlmostEqual(l_row[src_idx["SPK.LFE"]], 0.0, places=6)
    _TC.assertAlmostEqual(l_row[src_idx["SPK.C"]], 0.7071, places=4)


def test_downmix_matrix_7_1_4_to_2_0_composed_round_trip() -> None:
    """Composed 7.1.4->2.0 matrix must have correct dimensions."""
    from mmo.dsp.downmix import load_downmix_registry, load_layouts, resolve_conversion

    layouts = load_layouts(_LAYOUTS_YAML)
    registry = load_downmix_registry(_REPO_ROOT / "ontology" / "policies" / "downmix.yaml")
    matrix = resolve_conversion(
        layouts,
        registry,
        _REPO_ROOT,
        source_layout_id="LAYOUT.7_1_4",
        target_layout_id="LAYOUT.2_0",
    )

    assert len(matrix["coeffs"]) == 2       # 2 target channels
    assert len(matrix["coeffs"][0]) == 12   # 12 source channels (7.1.4)
    assert matrix["source_layout_id"] == "LAYOUT.7_1_4"
    assert matrix["target_layout_id"] == "LAYOUT.2_0"
