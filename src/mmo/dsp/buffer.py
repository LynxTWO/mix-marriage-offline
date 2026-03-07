"""Typed interleaved audio buffers with explicit channel semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Sequence


def generic_channel_order(channels: int) -> tuple[str, ...]:
    """Return deterministic placeholder channel ids for unlabeled buffers."""

    normalized_channels = int(channels)
    if normalized_channels <= 0:
        raise ValueError("channels must be > 0")
    return tuple(f"CH.{index + 1}" for index in range(normalized_channels))


@dataclass(slots=True, frozen=True)
class AudioBufferF64:
    """Interleaved float64 audio with explicit channel ordering metadata."""

    data: list[float]
    channels: int
    channel_order: tuple[str, ...]
    sample_rate_hz: int

    def __post_init__(self) -> None:
        normalized_channels = int(self.channels)
        if normalized_channels <= 0:
            raise ValueError("channels must be > 0")

        normalized_sample_rate_hz = int(self.sample_rate_hz)
        if normalized_sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be > 0")

        normalized_order = tuple(
            channel_id.strip()
            for channel_id in self.channel_order
            if isinstance(channel_id, str) and channel_id.strip()
        )
        if len(normalized_order) != normalized_channels:
            raise ValueError("channel_order length must match channels")

        normalized_data = [float(sample) for sample in self.data]
        if len(normalized_data) % normalized_channels != 0:
            raise ValueError("interleaved data length must be frame-aligned")

        object.__setattr__(self, "data", normalized_data)
        object.__setattr__(self, "channels", normalized_channels)
        object.__setattr__(self, "channel_order", normalized_order)
        object.__setattr__(self, "sample_rate_hz", normalized_sample_rate_hz)

    @property
    def frame_count(self) -> int:
        return len(self.data) // self.channels

    def slice_frames(self, start: int, count: int) -> AudioBufferF64:
        start_frame = int(start)
        count_frames = int(count)
        if start_frame < 0:
            raise ValueError("start must be >= 0")
        if count_frames < 0:
            raise ValueError("count must be >= 0")
        if count_frames == 0 or start_frame >= self.frame_count:
            return AudioBufferF64(
                data=[],
                channels=self.channels,
                channel_order=self.channel_order,
                sample_rate_hz=self.sample_rate_hz,
            )

        end_frame = min(self.frame_count, start_frame + count_frames)
        start_offset = start_frame * self.channels
        end_offset = end_frame * self.channels
        return AudioBufferF64(
            data=self.data[start_offset:end_offset],
            channels=self.channels,
            channel_order=self.channel_order,
            sample_rate_hz=self.sample_rate_hz,
        )

    def iter_frames(self, chunk_frames: int) -> Iterator[AudioBufferF64]:
        normalized_chunk_frames = int(chunk_frames)
        if normalized_chunk_frames <= 0:
            raise ValueError("chunk_frames must be > 0")

        for start_frame in range(0, self.frame_count, normalized_chunk_frames):
            yield self.slice_frames(start_frame, normalized_chunk_frames)

    def to_planar_lists(self) -> list[list[float]]:
        planar = [[0.0] * self.frame_count for _ in range(self.channels)]
        sample_index = 0
        for frame_index in range(self.frame_count):
            for channel_index in range(self.channels):
                planar[channel_index][frame_index] = self.data[sample_index]
                sample_index += 1
        return planar

    @classmethod
    def from_planar_lists(
        cls,
        planar_data: Sequence[Sequence[float]],
        *,
        channel_order: Sequence[str],
        sample_rate_hz: int,
    ) -> AudioBufferF64:
        channels = len(planar_data)
        if channels <= 0:
            raise ValueError("planar_data must contain at least one channel")

        frame_count = len(planar_data[0])
        interleaved: list[float] = []
        for channel_samples in planar_data:
            if len(channel_samples) != frame_count:
                raise ValueError("all planar channels must have the same frame count")

        for frame_index in range(frame_count):
            for channel_index in range(channels):
                interleaved.append(float(planar_data[channel_index][frame_index]))

        return cls(
            data=interleaved,
            channels=channels,
            channel_order=tuple(channel_order),
            sample_rate_hz=sample_rate_hz,
        )

    def peak_per_channel(self) -> list[float]:
        peaks = [0.0] * self.channels
        sample_index = 0
        for _ in range(self.frame_count):
            for channel_index in range(self.channels):
                sample = abs(self.data[sample_index])
                sample_index += 1
                if sample > peaks[channel_index]:
                    peaks[channel_index] = sample
        return peaks

    def apply_gain_scalar(self, gain: float) -> AudioBufferF64:
        gain_scalar = float(gain)
        return AudioBufferF64(
            data=[sample * gain_scalar for sample in self.data],
            channels=self.channels,
            channel_order=self.channel_order,
            sample_rate_hz=self.sample_rate_hz,
        )
