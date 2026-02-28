from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

RawTagSource = Literal["format", "stream"]


_TECHNICAL_KEYS: tuple[str, ...] = (
    "channels",
    "sample_rate_hz",
    "duration_s",
    "bits_per_sample",
    "codec_name",
    "channel_layout",
    "audio_format",
    "audio_format_resolved",
    "num_frames",
    "data_bytes",
    "byte_rate",
    "block_align",
    "channel_mask",
)
_INT_TECHNICAL_KEYS: frozenset[str] = frozenset({
    "channels",
    "sample_rate_hz",
    "bits_per_sample",
    "audio_format",
    "audio_format_resolved",
    "num_frames",
    "data_bytes",
    "byte_rate",
    "block_align",
    "channel_mask",
})
_FLOAT_TECHNICAL_KEYS: frozenset[str] = frozenset({"duration_s"})
_STR_TECHNICAL_KEYS: frozenset[str] = frozenset({"codec_name", "channel_layout"})

_SUMMARY_FIELD_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("title", ("title", "inam", "name", "track", "tracktitle")),
    ("artist", ("artist", "iart", "author", "performer", "album_artist")),
    ("album", ("album", "iprd", "albumtitle")),
    (
        "date",
        (
            "date",
            "year",
            "icrd",
            "origination_date",
            "creation_time",
        ),
    ),
)


@dataclass(frozen=True)
class RawTag:
    source: RawTagSource
    container: str
    scope: str
    key: str
    value: str
    index: int


@dataclass(frozen=True)
class TagBag:
    raw: tuple[RawTag, ...]
    normalized: dict[str, list[str]]
    warnings: tuple[str, ...]


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _normalized_source(value: str) -> RawTagSource:
    if value == "stream":
        return "stream"
    return "format"


def _normalized_index(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, str) and value.strip():
        try:
            return max(int(value), 0)
        except ValueError:
            return 0
    return 0


def _tag_sort_key(tag: RawTag) -> tuple[str, str, str, str, int, str]:
    return (
        tag.source,
        tag.container,
        tag.scope,
        tag.key.lower(),
        tag.index,
        tag.value,
    )


def canonicalize_tag_bag(
    raw_tags: Iterable[RawTag],
    warnings: Iterable[str] | None = None,
) -> TagBag:
    normalized_raw: list[RawTag] = []
    for raw in raw_tags:
        source = _normalized_source(_coerce_str(raw.source).strip().lower())
        container = _coerce_str(raw.container).strip().lower() or "unknown"
        scope = _coerce_str(raw.scope).strip().lower() or "unknown"
        key = _coerce_str(raw.key).strip()
        value = _coerce_str(raw.value).strip()
        if not key or value == "":
            continue
        normalized_raw.append(
            RawTag(
                source=source,
                container=container,
                scope=scope,
                key=key,
                value=value,
                index=_normalized_index(raw.index),
            )
        )

    sorted_raw = tuple(sorted(normalized_raw, key=_tag_sort_key))

    normalized_map: dict[str, list[str]] = {}
    for raw in sorted_raw:
        key_lower = raw.key.lower()
        values = normalized_map.setdefault(key_lower, [])
        values.append(raw.value)
    normalized_ordered = {key: normalized_map[key] for key in sorted(normalized_map.keys())}

    warning_values = ()
    if warnings is not None:
        warning_values = tuple(
            sorted(
                {
                    warning.strip()
                    for warning in warnings
                    if isinstance(warning, str) and warning.strip()
                }
            )
        )

    return TagBag(raw=sorted_raw, normalized=normalized_ordered, warnings=warning_values)


def empty_tag_bag() -> TagBag:
    return TagBag(raw=(), normalized={}, warnings=())


def raw_tag_to_mapping(tag: RawTag) -> dict[str, Any]:
    return {
        "source": tag.source,
        "container": tag.container,
        "scope": tag.scope,
        "key": tag.key,
        "value": tag.value,
        "index": tag.index,
    }


def tag_bag_to_mapping(tag_bag: TagBag) -> dict[str, Any]:
    return {
        "raw": [raw_tag_to_mapping(raw) for raw in tag_bag.raw],
        "normalized": {
            key: list(values)
            for key, values in sorted(tag_bag.normalized.items(), key=lambda item: item[0])
        },
        "warnings": list(tag_bag.warnings),
    }


def _raw_tag_from_mapping(value: Any) -> RawTag | None:
    if not isinstance(value, Mapping):
        return None

    key = _coerce_str(value.get("key")).strip()
    value_text = _coerce_str(value.get("value")).strip()
    if not key or value_text == "":
        return None

    source = _normalized_source(_coerce_str(value.get("source")).strip().lower())
    container = _coerce_str(value.get("container")).strip().lower() or "unknown"
    scope = _coerce_str(value.get("scope")).strip().lower() or "unknown"
    index = _normalized_index(value.get("index"))

    return RawTag(
        source=source,
        container=container,
        scope=scope,
        key=key,
        value=value_text,
        index=index,
    )


def tag_bag_from_mapping(value: Any) -> TagBag:
    if not isinstance(value, Mapping):
        return empty_tag_bag()

    raw_rows: list[RawTag] = []
    raw_value = value.get("raw")
    if isinstance(raw_value, list):
        for item in raw_value:
            raw_tag = _raw_tag_from_mapping(item)
            if raw_tag is not None:
                raw_rows.append(raw_tag)

    warnings_value = value.get("warnings")
    warnings: list[str] = []
    if isinstance(warnings_value, list):
        warnings = [
            warning.strip()
            for warning in warnings_value
            if isinstance(warning, str) and warning.strip()
        ]

    return canonicalize_tag_bag(raw_rows, warnings)


def merge_tag_bags(tag_bags: Iterable[TagBag]) -> TagBag:
    raw_tags: list[RawTag] = []
    warnings: list[str] = []
    for tag_bag in tag_bags:
        raw_tags.extend(tag_bag.raw)
        warnings.extend(tag_bag.warnings)
    return canonicalize_tag_bag(raw_tags, warnings)


def technical_metadata_from_probe(metadata: Mapping[str, Any]) -> dict[str, Any]:
    technical: dict[str, Any] = {}
    for key in _TECHNICAL_KEYS:
        value = metadata.get(key)
        if key in _INT_TECHNICAL_KEYS:
            if isinstance(value, int) and not isinstance(value, bool):
                technical[key] = value
            continue
        if key in _FLOAT_TECHNICAL_KEYS:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                technical[key] = float(value)
            continue
        if key in _STR_TECHNICAL_KEYS:
            if isinstance(value, str) and value.strip():
                technical[key] = value.strip()
            continue
    return technical


def source_metadata_from_probe(metadata: Mapping[str, Any]) -> dict[str, Any]:
    technical = technical_metadata_from_probe(metadata)
    tag_bag = tag_bag_from_mapping(metadata.get("tags"))
    return {
        "technical": technical,
        "tags": tag_bag_to_mapping(tag_bag),
    }


def source_metadata_from_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    technical_raw = value.get("technical")
    technical_value: Mapping[str, Any]
    if isinstance(technical_raw, Mapping):
        technical_value = technical_raw
    else:
        technical_value = {}
    return {
        "technical": technical_metadata_from_probe(technical_value),
        "tags": tag_bag_to_mapping(tag_bag_from_mapping(value.get("tags"))),
    }


def _pick_summary_value(
    normalized_map: Mapping[str, list[str]],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        values = normalized_map.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value:
                return value
    return None


def summary_from_tag_bag(tag_bag: TagBag) -> dict[str, str | None]:
    summary: dict[str, str | None] = {}
    for field, aliases in _SUMMARY_FIELD_KEYS:
        summary[field] = _pick_summary_value(tag_bag.normalized, aliases)
    return summary


def summarize_stem_source_tags(stems: Any) -> dict[str, Any]:
    if not isinstance(stems, list):
        stems = []

    rows = [row for row in stems if isinstance(row, Mapping)]
    rows.sort(
        key=lambda row: (
            _coerce_str(row.get("stem_id")).strip(),
            _coerce_str(row.get("file_path")).strip(),
        )
    )

    tag_bags: list[TagBag] = []
    for row in rows:
        source_metadata = row.get("source_metadata")
        if isinstance(source_metadata, Mapping):
            tag_bags.append(tag_bag_from_mapping(source_metadata.get("tags")))
            continue
        # Backward-compat: allow direct per-stem tags payload if present.
        tag_bags.append(tag_bag_from_mapping(row.get("tags")))

    merged = merge_tag_bags(tag_bags)
    return {
        "normalized": summary_from_tag_bag(merged),
        "preserved_tag_count": len(merged.raw),
        "warnings": list(merged.warnings),
    }
