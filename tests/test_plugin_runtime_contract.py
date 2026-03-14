from __future__ import annotations

import struct
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

from mmo.core.render_run_audio import (
    RenderRunRefusalError,
    _render_wav_with_plugin_chain,
)
from mmo.dsp.buffer import AudioBufferF64
from mmo.dsp.plugins.base import PluginContext
from mmo.dsp.plugins import registry as dsp_plugin_registry


def _write_stereo_wav(path: Path, *, sample_rate_hz: int = 48000) -> None:
    frames = [
        (1000, -1000),
        (500, -500),
        (-250, 250),
        (125, -125),
    ]
    packed = b"".join(struct.pack("<hh", left, right) for left, right in frames)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(packed)


class TestRenderRunTypedBoundary(unittest.TestCase):
    def test_render_runner_passes_typed_audio_buffer_to_plugin(self) -> None:
        class BoundaryProbePlugin:
            plugin_id = "typed_boundary_probe"

            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def process_stereo(
                self,
                audio_buffer: AudioBufferF64,
                sample_rate: int,
                params: dict[str, object],
                ctx: PluginContext,
                process_ctx: object | None = None,
            ) -> AudioBufferF64:
                del params
                self.calls.append(
                    {
                        "buffer_type": type(audio_buffer).__name__,
                        "channel_order": audio_buffer.channel_order,
                        "sample_rate_hz": audio_buffer.sample_rate_hz,
                        "sample_rate_arg": sample_rate,
                        "process_ctx_channel_order": getattr(process_ctx, "channel_order", ()),
                    }
                )
                ctx.evidence_collector.set(
                    stage_what="plugin stage applied",
                    stage_why="Boundary probe observed typed audio buffer input.",
                    metrics=[{"name": "stage_index", "value": ctx.stage_index}],
                )
                return audio_buffer

        plugin = BoundaryProbePlugin()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "source.wav"
            output_path = temp_root / "rendered.wav"
            _write_stereo_wav(source_path)

            with mock.patch.dict(
                dsp_plugin_registry._PLUGIN_REGISTRY,
                {plugin.plugin_id: plugin},
                clear=False,
            ):
                step_events = _render_wav_with_plugin_chain(
                    source_path=source_path,
                    output_path=output_path,
                    sample_rate_hz=48000,
                    bit_depth=16,
                    plugin_chain=[{"plugin_id": plugin.plugin_id, "params": {}}],
                    ffmpeg_cmd_for_decode=None,
                    max_theoretical_quality=False,
                    force_float64_default=False,
                )
                self.assertTrue(output_path.exists())

        self.assertEqual(len(step_events), 3)
        self.assertEqual(len(plugin.calls), 1)
        self.assertEqual(plugin.calls[0]["buffer_type"], "AudioBufferF64")
        self.assertEqual(plugin.calls[0]["channel_order"], ("SPK.L", "SPK.R"))
        self.assertEqual(plugin.calls[0]["sample_rate_hz"], 48000)
        self.assertEqual(plugin.calls[0]["sample_rate_arg"], 48000)
        self.assertEqual(plugin.calls[0]["process_ctx_channel_order"], ("SPK.L", "SPK.R"))

    def test_render_runner_rejects_wall_clock_purity_violation(self) -> None:
        class BadTimePlugin:
            plugin_id = "bad_time_plugin"

            def process_stereo(
                self,
                audio_buffer: AudioBufferF64,
                sample_rate: int,
                params: dict[str, object],
                ctx: PluginContext,
                process_ctx: object | None = None,
            ) -> AudioBufferF64:
                del sample_rate, params, ctx, process_ctx
                time.time()
                return audio_buffer

        plugin = BadTimePlugin()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "source.wav"
            output_path = temp_root / "rendered.wav"
            _write_stereo_wav(source_path)

            with mock.patch.dict(
                dsp_plugin_registry._PLUGIN_REGISTRY,
                {plugin.plugin_id: plugin},
                clear=False,
            ):
                with self.assertRaises(RenderRunRefusalError) as exc:
                    _render_wav_with_plugin_chain(
                        source_path=source_path,
                        output_path=output_path,
                        sample_rate_hz=48000,
                        bit_depth=16,
                        plugin_chain=[{"plugin_id": plugin.plugin_id, "params": {}}],
                        ffmpeg_cmd_for_decode=None,
                        max_theoretical_quality=False,
                        force_float64_default=False,
                    )

        self.assertIn("violated determinism purity contract", str(exc.exception))
        self.assertIn("wall-clock", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
