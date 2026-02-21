"""Deterministic in-memory registry for plugin-chain DSP implementations."""

from __future__ import annotations

from mmo.dsp.plugins.base import StereoPlugin
from mmo.dsp.plugins.gain_v0 import GainV0Plugin
from mmo.dsp.plugins.multiband_compressor_v0 import MultibandCompressorV0Plugin
from mmo.dsp.plugins.multiband_dynamic_auto_v0 import MultibandDynamicAutoV0Plugin
from mmo.dsp.plugins.multiband_expander_v0 import MultibandExpanderV0Plugin
from mmo.dsp.plugins.simple_compressor_v0 import SimpleCompressorV0Plugin
from mmo.dsp.plugins.tilt_eq_v0 import TiltEqV0Plugin

_PLUGIN_REGISTRY: dict[str, StereoPlugin] = {
    "gain_v0": GainV0Plugin(),
    "tilt_eq_v0": TiltEqV0Plugin(),
    "simple_compressor_v0": SimpleCompressorV0Plugin(),
    "multiband_compressor_v0": MultibandCompressorV0Plugin(),
    "multiband_expander_v0": MultibandExpanderV0Plugin(),
    "multiband_dynamic_auto_v0": MultibandDynamicAutoV0Plugin(),
}


def get_stereo_plugin(plugin_id: str) -> StereoPlugin | None:
    """Return plugin implementation by normalized plugin id."""

    return _PLUGIN_REGISTRY.get(plugin_id.strip().lower())


def stereo_plugin_ids() -> tuple[str, ...]:
    """Return deterministic plugin id ordering."""

    return tuple(_PLUGIN_REGISTRY.keys())

