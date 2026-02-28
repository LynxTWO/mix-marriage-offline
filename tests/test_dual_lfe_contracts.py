"""Dual-LFE contract tests for x.2 layout support."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from mmo.core.layout_negotiation import (
    get_channel_count,
    get_channel_order,
    get_layout_lfe_policy,
    get_program_loudness_channels,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMAS_DIR = _REPO_ROOT / "schemas"

_DUAL_LFE_LAYOUTS: dict[str, int] = {
    "LAYOUT.5_2": 7,
    "LAYOUT.7_2": 9,
    "LAYOUT.7_2_4": 13,
}

_DUAL_LFE_VARIANTS: dict[str, tuple[str, ...]] = {
    "LAYOUT.5_2": ("SMPTE", "FILM", "LOGIC_PRO"),
    "LAYOUT.7_2": ("SMPTE", "FILM", "LOGIC_PRO", "VST3"),
    "LAYOUT.7_2_4": ("SMPTE", "FILM", "VST3"),
}


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def test_dual_lfe_layouts_exist_with_expected_channel_counts() -> None:
    for layout_id, expected_channels in _DUAL_LFE_LAYOUTS.items():
        assert get_channel_count(layout_id) == expected_channels


def test_dual_lfe_ordering_variants_exist_and_are_deterministic() -> None:
    for layout_id, standards in _DUAL_LFE_VARIANTS.items():
        smpte = get_channel_order(layout_id, "SMPTE")
        assert smpte is not None
        assert len(smpte) == _DUAL_LFE_LAYOUTS[layout_id]
        assert smpte.count("SPK.LFE") == 1
        assert smpte.count("SPK.LFE2") == 1

        for standard in standards:
            first = get_channel_order(layout_id, standard)
            second = get_channel_order(layout_id, standard)
            assert first is not None
            assert first == second
            assert set(first) == set(smpte)


def test_dual_lfe_channels_are_excluded_from_program_loudness_inputs() -> None:
    for layout_id, expected_channels in _DUAL_LFE_LAYOUTS.items():
        policy = get_layout_lfe_policy(layout_id)
        assert policy is not None
        assert policy.get("has_lfe") is True
        assert policy.get("lfe_channels") == ["SPK.LFE", "SPK.LFE2"]
        assert policy.get("excluded_from_program_loudness") is True

        loudness_inputs = get_program_loudness_channels(layout_id)
        assert len(loudness_inputs) == expected_channels - 2
        assert "SPK.LFE" not in loudness_inputs
        assert "SPK.LFE2" not in loudness_inputs


def test_layouts_schema_accepts_dual_lfe_policy_channels() -> None:
    schema = _load_schema("layouts.schema.json")
    payload = {
        "layouts": {
            "LAYOUT.TEST_5_2": {
                "label": "Test 5.2",
                "channel_count": 7,
                "channel_order": [
                    "SPK.L",
                    "SPK.R",
                    "SPK.C",
                    "SPK.LFE",
                    "SPK.LFE2",
                    "SPK.LS",
                    "SPK.RS",
                ],
                "has_lfe": True,
                "lfe_policy": {
                    "has_lfe": True,
                    "lfe_channels": ["SPK.LFE", "SPK.LFE2"],
                    "excluded_from_program_loudness": True,
                    "default_downmix_treatment": "drop",
                },
            }
        }
    }
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_render_targets_schema_accepts_dual_lfe_channel_order() -> None:
    schema = _load_schema("render_targets.schema.json")
    payload = {
        "schema_version": "0.1.0",
        "targets": [
            {
                "target_id": "TARGET.TEST.7_2_4",
                "layout_id": "LAYOUT.7_2_4",
                "container": "wav",
                "channel_order": [
                    "SPK.L",
                    "SPK.R",
                    "SPK.C",
                    "SPK.LFE",
                    "SPK.LFE2",
                    "SPK.LS",
                    "SPK.RS",
                    "SPK.LRS",
                    "SPK.RRS",
                    "SPK.TFL",
                    "SPK.TFR",
                    "SPK.TRL",
                    "SPK.TRR",
                ],
                "filename_template": "{target_id}.{container}",
            }
        ],
    }
    jsonschema.Draft202012Validator(schema).validate(payload)
