"""Conservative subjective plugin pack — layout-aware multichannel DSP.

Plugins
-------
height_air_v0      : Air-band high-shelf polish for height channels only.
stereo_widener_v0  : M/S stereo width adjustment on FL/FR pair.
early_reflections_v0: Deterministic early-reflection comb delays on surrounds.
eq_safety_v0       : Conservative subtractive EQ with RMS/headroom safety gates.
reverb_safety_v0   : Conservative ambience tail with RMS/headroom safety gates.
binaural_preview_v0: Conservative headphone virtualization preview renderer.

All plugins implement the ``MultichannelPlugin`` protocol from
``mmo.dsp.plugins.base``.  They use ``LayoutContext`` for all channel routing
so they work correctly across SMPTE, FILM, LOGIC_PRO, VST3, and AAF ordering.
"""
