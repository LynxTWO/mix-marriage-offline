"""Deterministic in-memory registry for plugin-chain DSP implementations."""

from __future__ import annotations

from mmo.dsp.plugins.base import MultichannelPlugin, StereoPlugin
from mmo.dsp.plugins.gain_v0 import GainV0Plugin
from mmo.dsp.plugins.multiband_compressor_v0 import MultibandCompressorV0Plugin
from mmo.dsp.plugins.multiband_dynamic_auto_v0 import MultibandDynamicAutoV0Plugin
from mmo.dsp.plugins.multiband_expander_v0 import MultibandExpanderV0Plugin
from mmo.dsp.plugins.simple_compressor_v0 import SimpleCompressorV0Plugin
from mmo.dsp.plugins.tilt_eq_v0 import TiltEqV0Plugin
from mmo.plugins.subjective.eq_safety_v0 import EqSafetyV0Plugin
from mmo.plugins.subjective.early_reflections_v0 import EarlyReflectionsV0Plugin
from mmo.plugins.subjective.height_air_v0 import HeightAirV0Plugin
from mmo.plugins.subjective.reverb_safety_v0 import ReverbSafetyV0Plugin
from mmo.plugins.subjective.stereo_widener_v0 import StereoWidenerV0Plugin

_PLUGIN_REGISTRY: dict[str, StereoPlugin] = {
    "gain_v0": GainV0Plugin(),
    "tilt_eq_v0": TiltEqV0Plugin(),
    "simple_compressor_v0": SimpleCompressorV0Plugin(),
    "multiband_compressor_v0": MultibandCompressorV0Plugin(),
    "multiband_expander_v0": MultibandExpanderV0Plugin(),
    "multiband_dynamic_auto_v0": MultibandDynamicAutoV0Plugin(),
}

_MULTICHANNEL_PLUGIN_REGISTRY: dict[str, MultichannelPlugin] = {
    "height_air_v0": HeightAirV0Plugin(),
    "stereo_widener_v0": StereoWidenerV0Plugin(),
    "early_reflections_v0": EarlyReflectionsV0Plugin(),
    "eq_safety_v0": EqSafetyV0Plugin(),
    "reverb_safety_v0": ReverbSafetyV0Plugin(),
}


def get_stereo_plugin(plugin_id: str) -> StereoPlugin | None:
    """Return stereo plugin implementation by normalized plugin id."""

    return _PLUGIN_REGISTRY.get(plugin_id.strip().lower())


def stereo_plugin_ids() -> tuple[str, ...]:
    """Return deterministic stereo plugin id ordering."""

    return tuple(_PLUGIN_REGISTRY.keys())


def get_multichannel_plugin(plugin_id: str) -> MultichannelPlugin | None:
    """Return multichannel plugin implementation by normalized plugin id."""

    return _MULTICHANNEL_PLUGIN_REGISTRY.get(plugin_id.strip().lower())


def multichannel_plugin_ids() -> tuple[str, ...]:
    """Return deterministic multichannel plugin id ordering."""

    return tuple(_MULTICHANNEL_PLUGIN_REGISTRY.keys())
