"""Base types and shared helpers for plugin-chain DSP modules.

Why every plugin must carry a SpeakerLayout
--------------------------------------------
Two channel-ordering worlds collide in daily studio work:

  SMPTE / ITU-R (WAV, FLAC, WavPack, Atmos bed inputs):
    5.1 → L R C LFE Ls Rs      (LFE at slot 3)

  Film / Cinema / Pro Tools (dub stage, theatrical):
    5.1 → L C R Ls Rs LFE      (LFE at slot 5)

A DSP plugin that blindly assumes "channel 3 is always center" will apply
the wrong curve to dialogue in Film order and wrong EQ to the LFE in SMPTE
order.  The ``MultichannelPlugin`` protocol below enforces layout awareness at
the API level: every plugin receives a ``ProcessContext`` for the current
buffer plus a ``LayoutContext`` compatibility adapter for legacy
``SpeakerLayout``-style access.  Plugins must use semantic speaker IDs instead
of hard-coding a slot number.

See also: ``mmo.core.speaker_layout`` for the canonical ``SpeakerPosition``
enum, preset ``SpeakerLayout`` constants, and the ``remap_channels_fill()``
utility.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from mmo.dsp.buffer import AudioBufferF64, generic_channel_order
from mmo.dsp.process_context import ProcessContext

if TYPE_CHECKING:
    from mmo.core.speaker_layout import SpeakerLayout, SpeakerPosition


class PluginValidationError(ValueError):
    """Raised when a plugin stage has invalid runtime parameters."""


@dataclass
class PluginEvidenceCollector:
    """Mutable stage evidence payload that plugins populate deterministically."""

    stage_what: str = "plugin stage applied"
    stage_why: str = ""
    metrics: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] | None = None

    def set(
        self,
        *,
        stage_what: str,
        stage_why: str,
        metrics: list[dict[str, Any]],
        notes: list[str] | None = None,
    ) -> None:
        self.stage_what = stage_what
        self.stage_why = stage_why
        self.metrics = metrics
        self.notes = notes


@dataclass(frozen=True)
class PluginContext:
    """Execution context for a single plugin stage."""

    precision_mode: str
    max_theoretical_quality: bool
    evidence_collector: PluginEvidenceCollector
    stage_index: int


def _process_ctx_speaker_id(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    raw_value = getattr(value, "value", value)
    if isinstance(raw_value, str):
        return raw_value.strip()
    return ""


@runtime_checkable
class StereoPlugin(Protocol):
    """Interface for deterministic stereo plugin processors."""

    plugin_id: str

    def process_stereo(
        self,
        audio_buffer: AudioBufferF64,
        sample_rate: int,
        params: dict[str, Any],
        ctx: PluginContext,
        process_ctx: ProcessContext | None = None,
    ) -> AudioBufferF64:
        """Process a typed stereo buffer and populate ``ctx.evidence_collector``."""


@dataclass(frozen=True)
class _LayoutStandardView:
    value: str


@dataclass(frozen=True)
class _ProcessLayoutView:
    process_ctx: ProcessContext
    layout_id: str
    standard: Any
    channel_order: tuple[Any, ...]

    def __init__(self, process_ctx: ProcessContext) -> None:
        from mmo.core.speaker_layout import LayoutStandard, SpeakerPosition  # noqa: PLC0415

        channel_order: list[Any] = []
        for speaker_id in process_ctx.channel_order:
            try:
                channel_order.append(SpeakerPosition(speaker_id))
            except ValueError:
                channel_order.append(speaker_id)

        try:
            standard: Any = LayoutStandard[process_ctx.layout_standard]
        except KeyError:
            standard = _LayoutStandardView(process_ctx.layout_standard)

        object.__setattr__(self, "process_ctx", process_ctx)
        object.__setattr__(self, "layout_id", process_ctx.layout_id)
        object.__setattr__(self, "standard", standard)
        object.__setattr__(self, "channel_order", tuple(channel_order))

    @property
    def num_channels(self) -> int:
        return self.process_ctx.num_channels

    def index_of(self, position: Any) -> int | None:
        return self.process_ctx.index_of(_process_ctx_speaker_id(position))

    @property
    def lfe_slots(self) -> list[int]:
        return self.process_ctx.lfe_indices

    @property
    def height_slots(self) -> list[int]:
        return self.process_ctx.height_indices


# ---------------------------------------------------------------------------
# Layout-aware multichannel plugin types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayoutContext:
    """Speaker-layout context passed to every multichannel-aware plugin.

    Carries the fully resolved ``SpeakerLayout`` for the current buffer so
    that plugins can route audio to the correct physical speakers by semantic
    name rather than raw slot index.

    Usage in a plugin
    -----------------
    ::

        from mmo.core.speaker_layout import SpeakerPosition

        def process_multichannel(self, buf, sample_rate, params, ctx, layout_ctx):
            lfe_slot = layout_ctx.index_of(SpeakerPosition.LFE)
            if lfe_slot is not None:
                # Apply low-pass only to the LFE channel
                buf[lfe_slot] = low_pass(buf[lfe_slot], cutoff_hz=120)
            height_slots = layout_ctx.layout.height_slots
            for slot in height_slots:
                # Apply air-band only to height channels
                buf[slot] = air_band_boost(buf[slot])
    """

    # Import deferred to avoid circular dependency at module load time.
    # Callers can import SpeakerLayout from mmo.core.speaker_layout directly.
    layout: Any  # SpeakerLayout — typed as Any here to avoid the circular import
    process_ctx: ProcessContext | None = None

    @classmethod
    def from_process_context(cls, process_ctx: ProcessContext) -> LayoutContext:
        """Create a legacy layout adapter backed by a ProcessContext."""

        return cls(
            layout=_ProcessLayoutView(process_ctx),
            process_ctx=process_ctx,
        )

    def index_of(self, position: Any) -> int | None:
        """Return the 0-based slot index of ``position``, or ``None`` if absent."""
        if self.process_ctx is not None:
            return self.process_ctx.index_of(_process_ctx_speaker_id(position))
        return self.layout.index_of(position)

    @property
    def lfe_slots(self) -> list[int]:
        """Return sorted list of LFE PCM slot indices."""
        if self.process_ctx is not None:
            return self.process_ctx.lfe_indices
        return self.layout.lfe_slots

    @property
    def height_slots(self) -> list[int]:
        """Return sorted list of height-channel PCM slot indices."""
        if self.process_ctx is not None:
            return self.process_ctx.height_indices
        return self.layout.height_slots

    @property
    def num_channels(self) -> int:
        """Number of channels in the associated layout."""
        if self.process_ctx is not None:
            return self.process_ctx.num_channels
        return self.layout.num_channels


@runtime_checkable
class MultichannelPlugin(Protocol):
    """Interface for layout-aware multichannel DSP processors.

    Every plugin that operates on multichannel audio (EQ, compressor, reverb,
    panner, meter, etc.) MUST implement this protocol so that the processing
    chain can pass the correct ``LayoutContext`` at each stage.

    Contract
    --------
    1. **Never hard-code channel indices.**
       Use ``layout_ctx.index_of(SpeakerPosition.FC)`` to find the centre
       channel, ``layout_ctx.lfe_slots`` for the LFE, etc.

    2. **Handle unknown layouts gracefully.**
       If the plugin receives a layout it does not recognise, it must route
       the extra channels transparently (pass through or silence), never crash.

    3. **LFE is sovereign.**
       Apply low-frequency processing (sub-bass, redirected bass) only to
       LFE slots.  Never promote LFE content into program channels.

    4. **Heights are optional.**
       If the plugin does not process height channels, it must pass them
       through unchanged.  Silencing heights is only acceptable when the
       plugin explicitly declares ``bed_only: true`` in its manifest.

    5. **Emit evidence.**
       Every plugin must populate ``ctx.evidence_collector`` with what/why/
       metrics for deterministic explain-ability.
    """

    plugin_id: str

    def process_multichannel(
        self,
        audio_buffer: AudioBufferF64,
        sample_rate: int,
        params: dict[str, Any],
        ctx: PluginContext,
        layout_ctx: LayoutContext,
        process_ctx: ProcessContext | None = None,
    ) -> AudioBufferF64:
        """Process a multichannel audio buffer with full layout awareness.

        Parameters
        ----------
        audio_buffer:
            ``AudioBufferF64`` with explicit ``channel_order`` and
            ``sample_rate_hz`` semantics. Legacy direct NumPy-array calls may
            still be adapted in tests, but the runtime boundary always passes a
            typed buffer.
        sample_rate:
            Audio sample rate in Hz.
        params:
            Plugin-specific parameter dictionary.
        ctx:
            Execution context (precision mode, evidence collector, stage index).
        layout_ctx:
            Speaker-layout compatibility context derived from ``process_ctx``
            when needed. Use ``layout_ctx.index_of(position)`` to look up a
            speaker by semantic name; never assume fixed slot indices.
        process_ctx:
            Canonical DSP truth object for the current buffer. Prefer
            ``process_ctx.index_of("SPK.C")`` and related helpers in new code.
        """


def precision_mode_numpy_dtype(*, np: Any, precision_mode: str) -> Any:
    normalized = precision_mode.strip().lower()
    if normalized in {"f32", "float32"}:
        return np.float32
    return np.float64


def coerce_audio_buffer_for_process_context(
    *,
    value: Any,
    plugin_id: str,
    sample_rate_hz: int,
    process_ctx: ProcessContext,
) -> AudioBufferF64:
    if not isinstance(value, AudioBufferF64):
        raise PluginValidationError(
            f"{plugin_id} requires AudioBufferF64 input at the typed runtime boundary.",
        )
    if value.sample_rate_hz != int(sample_rate_hz):
        raise PluginValidationError(
            f"{plugin_id} requires audio_buffer.sample_rate_hz to match sample_rate.",
        )
    if value.channel_order != tuple(process_ctx.channel_order):
        raise PluginValidationError(
            f"{plugin_id} requires audio_buffer.channel_order to match ProcessContext.channel_order.",
        )
    if value.channels != process_ctx.num_channels:
        raise PluginValidationError(
            f"{plugin_id} requires audio_buffer.channels to match ProcessContext.num_channels.",
        )
    return value


def _layout_channel_order(
    *,
    layout_ctx: LayoutContext,
    process_ctx: ProcessContext | None,
) -> tuple[str, ...]:
    if process_ctx is not None:
        return tuple(process_ctx.channel_order)

    raw_channel_order = getattr(layout_ctx.layout, "channel_order", ())
    normalized = tuple(
        speaker_id
        for speaker_id in (
            _process_ctx_speaker_id(item) for item in raw_channel_order
        )
        if speaker_id
    )
    if len(normalized) == layout_ctx.num_channels:
        return normalized
    return generic_channel_order(layout_ctx.num_channels)


def coerce_multichannel_audio_buffer(
    *,
    value: Any,
    plugin_id: str,
    sample_rate_hz: int,
    layout_ctx: LayoutContext,
    process_ctx: ProcessContext | None = None,
) -> tuple[AudioBufferF64, bool]:
    if isinstance(value, AudioBufferF64):
        channel_order = _layout_channel_order(
            layout_ctx=layout_ctx,
            process_ctx=process_ctx,
        )
        if value.sample_rate_hz != int(sample_rate_hz):
            raise PluginValidationError(
                f"{plugin_id} requires audio_buffer.sample_rate_hz to match sample_rate.",
            )
        if value.channels != layout_ctx.num_channels:
            raise PluginValidationError(
                f"{plugin_id} requires audio_buffer.channels to match layout_ctx.num_channels.",
            )
        if value.channel_order != channel_order:
            raise PluginValidationError(
                f"{plugin_id} requires audio_buffer.channel_order to match layout semantics.",
            )
        return value, True

    import numpy as np

    matrix = np.asarray(value)
    if matrix.ndim != 2 or matrix.shape[0] != layout_ctx.num_channels:
        raise PluginValidationError(
            f"{plugin_id} requires a (channels, samples) matrix or AudioBufferF64 input.",
        )
    return (
        AudioBufferF64.from_channel_matrix(
            matrix,
            channel_order=_layout_channel_order(
                layout_ctx=layout_ctx,
                process_ctx=process_ctx,
            ),
            sample_rate_hz=sample_rate_hz,
        ),
        False,
    )


def restore_multichannel_audio_buffer(
    *,
    audio_buffer: AudioBufferF64,
    original_input_was_typed: bool,
    np: Any,
    dtype: Any,
) -> Any:
    if original_input_was_typed:
        return audio_buffer
    return audio_buffer.to_channel_matrix(np=np, dtype=dtype)


def coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, float) and value in (0.0, 1.0):
        return bool(int(value))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return None


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def parse_bypass_for_stage(*, plugin_id: str, params: dict[str, Any]) -> bool:
    bypass_raw = params.get("bypass")
    if bypass_raw is None:
        return False
    bypass_value = coerce_bool(bypass_raw)
    if bypass_value is None:
        raise PluginValidationError(
            f"{plugin_id} requires boolean params.bypass when provided.",
        )
    return bypass_value


def parse_macro_mix_for_stage(
    *,
    plugin_id: str,
    params: dict[str, Any],
) -> tuple[float, float]:
    raw_macro_mix = params.get("macro_mix")
    if raw_macro_mix is None:
        return 1.0, 1.0
    macro_mix_input = coerce_float(raw_macro_mix)
    if macro_mix_input is None:
        raise PluginValidationError(
            f"{plugin_id} requires numeric params.macro_mix "
            "in [0.0, 1.0] or [0.0, 100.0].",
        )
    if 0.0 <= macro_mix_input <= 1.0:
        return macro_mix_input, macro_mix_input
    if 0.0 <= macro_mix_input <= 100.0:
        return macro_mix_input / 100.0, macro_mix_input
    raise PluginValidationError(
        f"{plugin_id} requires params.macro_mix "
        "in [0.0, 1.0] or [0.0, 100.0].",
    )


def require_finite_float_param(
    *,
    plugin_id: str,
    params: dict[str, Any],
    param_name: str,
) -> float:
    value = coerce_float(params.get(param_name))
    if value is None or not math.isfinite(value):
        raise PluginValidationError(
            f"{plugin_id} requires numeric params.{param_name}.",
        )
    return float(value)


def optional_int_param(
    *,
    plugin_id: str,
    params: dict[str, Any],
    param_name: str,
    default_value: int,
    minimum_value: int,
    maximum_value: int,
) -> int:
    raw_value = params.get(param_name)
    if raw_value is None:
        return default_value
    if isinstance(raw_value, bool):
        raise PluginValidationError(
            f"{plugin_id} requires integer params.{param_name}.",
        )
    value = coerce_int(raw_value)
    if value is None:
        raise PluginValidationError(
            f"{plugin_id} requires integer params.{param_name}.",
        )
    if value < minimum_value or value > maximum_value:
        raise PluginValidationError(
            f"{plugin_id} requires params.{param_name} in "
            f"[{minimum_value}, {maximum_value}].",
        )
    return value


def optional_float_param(
    *,
    plugin_id: str,
    params: dict[str, Any],
    param_name: str,
    default_value: float,
    minimum_value: float,
    maximum_value: float,
) -> float:
    raw_value = params.get(param_name)
    if raw_value is None:
        return default_value
    value = coerce_float(raw_value)
    if value is None or not math.isfinite(value):
        raise PluginValidationError(
            f"{plugin_id} requires numeric params.{param_name}.",
        )
    if value < minimum_value or value > maximum_value:
        raise PluginValidationError(
            f"{plugin_id} requires params.{param_name} in "
            f"[{minimum_value}, {maximum_value}].",
        )
    return float(value)
