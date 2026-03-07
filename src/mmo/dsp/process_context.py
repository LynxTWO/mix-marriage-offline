"""Semantic DSP execution context built from layout ontology channel order."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from mmo.core.layout_negotiation import (
    DEFAULT_CHANNEL_STANDARD,
    get_channel_order,
    get_layout_info,
)
from mmo.resources import load_ontology_yaml

_DEFAULT_SAMPLE_RATE_HZ = 48_000
_FRONT_GROUP_ALIASES: frozenset[str] = frozenset({"front", "center"})
_FALLBACK_GROUP_SPEAKERS: dict[str, frozenset[str]] = {
    "front": frozenset(
        {
            "SPK.M",
            "SPK.L",
            "SPK.R",
            "SPK.C",
            "SPK.HL",
            "SPK.HR",
            "SPK.LW",
            "SPK.RW",
            "SPK.FLC",
            "SPK.FRC",
        }
    ),
    "surround": frozenset({"SPK.LS", "SPK.RS"}),
    "rear": frozenset({"SPK.LRS", "SPK.RRS", "SPK.BC"}),
}
_HEIGHT_PREFIX = "SPK.T"
_LFE_PREFIX = "SPK.LFE"


def _normalize_layout_id(layout_id: str) -> str:
    return layout_id.strip()


def _normalize_standard(layout_standard: str) -> str:
    normalized = layout_standard.strip().upper()
    return normalized or DEFAULT_CHANNEL_STANDARD


def _normalize_sample_rate_hz(sample_rate_hz: int) -> int:
    value = int(sample_rate_hz)
    if value <= 0:
        raise ValueError("sample_rate_hz must be > 0.")
    return value


def _normalize_seed(seed: int) -> int:
    return int(seed)


@lru_cache(maxsize=1)
def _speaker_groups_from_ontology() -> dict[str, frozenset[str]]:
    try:
        payload = load_ontology_yaml("speakers.yaml")
    except (FileNotFoundError, ImportError, RuntimeError, OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}

    speakers_payload = payload.get("speakers")
    if not isinstance(speakers_payload, dict):
        return {}

    groups: dict[str, set[str]] = {}
    for spk_id, info in speakers_payload.items():
        if spk_id == "_meta":
            continue
        if not isinstance(spk_id, str) or not spk_id.strip():
            continue
        if not isinstance(info, dict):
            continue

        normalized_spk_id = spk_id.strip()
        raw_group = info.get("channel_group")
        if isinstance(raw_group, str) and raw_group.strip():
            groups.setdefault(raw_group.strip().lower(), set()).add(normalized_spk_id)
        if bool(info.get("is_height")):
            groups.setdefault("height", set()).add(normalized_spk_id)
        if bool(info.get("is_lfe")):
            groups.setdefault("lfe", set()).add(normalized_spk_id)

    if groups.get("center"):
        groups.setdefault("front", set()).update(groups["center"])

    return {
        group_name: frozenset(sorted(speaker_ids))
        for group_name, speaker_ids in groups.items()
        if speaker_ids
    }


def _speaker_ids_for_group(group_name: str) -> frozenset[str]:
    normalized = group_name.strip().lower()
    if not normalized:
        return frozenset()

    ontology_groups = _speaker_groups_from_ontology()
    if normalized == "front":
        speaker_ids: set[str] = set()
        for alias in _FRONT_GROUP_ALIASES:
            speaker_ids.update(ontology_groups.get(alias, ()))
        if speaker_ids:
            return frozenset(sorted(speaker_ids))
    else:
        speaker_ids = set(ontology_groups.get(normalized, ()))
        if speaker_ids:
            return frozenset(sorted(speaker_ids))

    if normalized in _FALLBACK_GROUP_SPEAKERS:
        return _FALLBACK_GROUP_SPEAKERS[normalized]
    return frozenset()


def _fallback_group_match(group_name: str, speaker_id: str) -> bool:
    normalized = group_name.strip().lower()
    if normalized == "height":
        return speaker_id.startswith(_HEIGHT_PREFIX)
    if normalized == "lfe":
        return speaker_id.startswith(_LFE_PREFIX)
    return speaker_id in _FALLBACK_GROUP_SPEAKERS.get(normalized, frozenset())


@dataclass(frozen=True)
class ProcessContext:
    """Canonical DSP execution context for one audio buffer."""

    layout_id: str
    layout_standard: str
    channel_order: tuple[str, ...]
    sample_rate_hz: int
    seed: int

    def __post_init__(self) -> None:
        normalized_layout_id = _normalize_layout_id(self.layout_id)
        if not normalized_layout_id:
            raise ValueError("layout_id must be a non-empty string.")

        normalized_standard = _normalize_standard(self.layout_standard)
        normalized_order = tuple(
            speaker_id.strip()
            for speaker_id in self.channel_order
            if isinstance(speaker_id, str) and speaker_id.strip()
        )
        if not normalized_order:
            raise ValueError("channel_order must contain at least one SPK.* ID.")

        object.__setattr__(self, "layout_id", normalized_layout_id)
        object.__setattr__(self, "layout_standard", normalized_standard)
        object.__setattr__(self, "channel_order", normalized_order)
        object.__setattr__(
            self,
            "sample_rate_hz",
            _normalize_sample_rate_hz(self.sample_rate_hz),
        )
        object.__setattr__(self, "seed", _normalize_seed(self.seed))

    @classmethod
    def from_layout(
        cls,
        layout_id: str,
        *,
        layout_standard: str = DEFAULT_CHANNEL_STANDARD,
        sample_rate_hz: int = _DEFAULT_SAMPLE_RATE_HZ,
        seed: int = 0,
    ) -> ProcessContext:
        normalized_layout_id = _normalize_layout_id(layout_id)
        if not normalized_layout_id:
            raise ValueError("layout_id must be a non-empty string.")

        entry = get_layout_info(normalized_layout_id)
        if entry is None:
            raise ValueError(f"Unknown layout_id: {layout_id!r}")

        normalized_standard = _normalize_standard(layout_standard)
        channel_order = get_channel_order(
            normalized_layout_id,
            normalized_standard,
        )
        if not channel_order:
            raise ValueError(
                f"Layout {normalized_layout_id!r} has no channel_order for "
                f"standard {normalized_standard!r}."
            )

        return cls(
            layout_id=normalized_layout_id,
            layout_standard=normalized_standard,
            channel_order=tuple(channel_order),
            sample_rate_hz=sample_rate_hz,
            seed=seed,
        )

    @property
    def num_channels(self) -> int:
        return len(self.channel_order)

    @property
    def lfe_indices(self) -> list[int]:
        return self.group_indices("lfe")

    @property
    def height_indices(self) -> list[int]:
        return self.group_indices("height")

    def index_of(self, spk_id: str) -> int | None:
        normalized = spk_id.strip()
        if not normalized:
            return None
        for index, candidate in enumerate(self.channel_order):
            if candidate == normalized:
                return index
        return None

    def indices_of(self, spk_ids: set[str]) -> list[int]:
        normalized = {
            spk_id.strip()
            for spk_id in spk_ids
            if isinstance(spk_id, str) and spk_id.strip()
        }
        if not normalized:
            return []
        return [
            index
            for index, candidate in enumerate(self.channel_order)
            if candidate in normalized
        ]

    def has(self, spk_id: str) -> bool:
        return self.index_of(spk_id) is not None

    def group_indices(self, group_name: str) -> list[int]:
        speaker_ids = _speaker_ids_for_group(group_name)
        if speaker_ids:
            return self.indices_of(set(speaker_ids))
        return [
            index
            for index, candidate in enumerate(self.channel_order)
            if _fallback_group_match(group_name, candidate)
        ]


def build_process_context(
    layout_id: str,
    *,
    standard: str | None = None,
    layout_standard: str = DEFAULT_CHANNEL_STANDARD,
    sample_rate_hz: int = _DEFAULT_SAMPLE_RATE_HZ,
    seed: int = 0,
) -> ProcessContext:
    """Resolve a layout ontology entry into a ProcessContext."""

    return ProcessContext.from_layout(
        layout_id,
        layout_standard=standard or layout_standard,
        sample_rate_hz=sample_rate_hz,
        seed=seed,
    )
