from __future__ import annotations

from typing import Any, Iterable, Sequence

from mmo.core.media_tags import TagBag, tag_bag_to_mapping

_ARBITRARY_FIELD_CONTAINERS = frozenset({"flac", "wv", "wavpack"})
_WAV_CONTAINERS = frozenset({"wav", "wave"})
_KEY_ALLOWED_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_.-")
_WAV_INFO_ALIASES: dict[str, str] = {
    "album": "IPRD",
    "album_artist": "IART",
    "albumtitle": "IPRD",
    "artist": "IART",
    "author": "IART",
    "comment": "ICMT",
    "date": "ICRD",
    "description": "ICMT",
    "genre": "IGNR",
    "iart": "IART",
    "icmt": "ICMT",
    "icrd": "ICRD",
    "ignr": "IGNR",
    "inam": "INAM",
    "iprd": "IPRD",
    "itrk": "ITRK",
    "name": "INAM",
    "origination_date": "ICRD",
    "performer": "IART",
    "title": "INAM",
    "track": "INAM",
    "track_number": "ITRK",
    "tracknumber": "ITRK",
    "tracktitle": "INAM",
    "year": "ICRD",
}


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _normalize_container_id(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in _WAV_CONTAINERS:
        return "wav"
    if normalized in _ARBITRARY_FIELD_CONTAINERS:
        return "wv" if normalized in {"wv", "wavpack"} else "flac"
    return normalized


def _sanitize_metadata_key(raw: str) -> str:
    normalized = raw.strip().lower().replace(" ", "_")
    if not normalized:
        return ""
    cleaned_chars = [
        char if char in _KEY_ALLOWED_CHARS else "_"
        for char in normalized
    ]
    cleaned = "".join(cleaned_chars).strip("_.-")
    if not cleaned:
        return ""
    if cleaned[0].isdigit():
        cleaned = f"tag_{cleaned}"
    return cleaned


def _sorted_unique_strings(values: Iterable[str]) -> list[str]:
    return sorted(
        {
            value.strip()
            for value in values
            if isinstance(value, str) and value.strip()
        },
        key=lambda item: (item.lower(), item),
    )


def _ffmpeg_metadata_args(fields: Sequence[tuple[str, str]]) -> list[str]:
    args: list[str] = []
    for key, value in fields:
        args.extend(["-metadata", f"{key}={value}"])
    return args


def _all_tag_keys(tag_bag: TagBag) -> list[str]:
    keys = list(tag_bag.normalized.keys())
    keys.extend(raw.key for raw in tag_bag.raw if raw.key.strip())
    return _sorted_unique_strings(keys)


def _metadata_rows_for_arbitrary_fields(
    tag_bag: TagBag,
) -> tuple[list[tuple[str, str]], list[str], list[str], list[str]]:
    rows: list[tuple[str, str]] = []
    embedded_keys: list[str] = []
    skipped_keys: list[str] = []
    warnings: list[str] = list(tag_bag.warnings)

    for key in sorted(tag_bag.normalized.keys()):
        safe_key = _sanitize_metadata_key(key)
        if not safe_key:
            warnings.append(f"Skipped normalized key with invalid metadata name: {key!r}")
            skipped_keys.append(key)
            continue
        values = tag_bag.normalized.get(key) or []
        for index, value in enumerate(values, start=1):
            value_text = _coerce_str(value).strip()
            if value_text == "":
                continue
            field_key = safe_key if index == 1 else f"{safe_key}__{index}"
            rows.append((field_key, value_text))
            embedded_keys.append(key)

    for raw_tag in tag_bag.raw:
        raw_key = _coerce_str(raw_tag.key).strip()
        raw_value = _coerce_str(raw_tag.value).strip()
        if not raw_key or raw_value == "":
            continue
        safe_key = _sanitize_metadata_key(raw_key)
        safe_scope = _sanitize_metadata_key(raw_tag.scope)
        if not safe_key or not safe_scope:
            warnings.append(f"Skipped raw key with invalid metadata name: {raw_key!r}")
            skipped_keys.append(raw_key)
            continue
        rows.append(
            (
                (
                    "mmo_raw"
                    f"__{_sanitize_metadata_key(raw_tag.source)}"
                    f"__{safe_scope}"
                    f"__{raw_tag.index:03d}"
                    f"__{safe_key}"
                ),
                raw_value,
            )
        )
        embedded_keys.append(raw_key)

    rows.sort(key=lambda item: (item[0], item[1]))
    return rows, embedded_keys, skipped_keys, warnings


def _wav_info_field_for_key(key: str) -> str | None:
    normalized = key.strip().lower()
    if not normalized:
        return None
    return _WAV_INFO_ALIASES.get(normalized)


def _metadata_rows_for_wav_info(
    tag_bag: TagBag,
) -> tuple[list[tuple[str, str]], list[str], list[str], list[str]]:
    rows: list[tuple[str, str]] = []
    embedded_keys: list[str] = []
    skipped_keys: list[str] = []
    warnings: list[str] = list(tag_bag.warnings)
    used_info_fields: set[str] = set()

    candidates: list[tuple[str, str]] = []
    for key in sorted(tag_bag.normalized.keys()):
        values = tag_bag.normalized.get(key) or []
        for value in values:
            value_text = _coerce_str(value).strip()
            if value_text == "":
                continue
            candidates.append((key, value_text))
    for raw_tag in tag_bag.raw:
        key = _coerce_str(raw_tag.key).strip()
        value = _coerce_str(raw_tag.value).strip()
        if not key or value == "":
            continue
        candidates.append((key, value))

    for key, value in candidates:
        info_field = _wav_info_field_for_key(key)
        if info_field is None:
            skipped_keys.append(key)
            continue
        if info_field in used_info_fields:
            skipped_keys.append(key)
            warnings.append(
                (
                    "WAV INFO field already populated; skipped duplicate key "
                    f"{key!r} for field {info_field}."
                ),
            )
            continue
        used_info_fields.add(info_field)
        rows.append((info_field, value))
        embedded_keys.append(key)

    rows.sort(key=lambda item: (item[0], item[1]))
    return rows, embedded_keys, skipped_keys, warnings


def build_ffmpeg_tag_export_args(
    tag_bag: TagBag,
    output_container_format_id: str,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return deterministic metadata args + receipt keys for ffmpeg export."""
    container_id = _normalize_container_id(output_container_format_id)

    if container_id in _ARBITRARY_FIELD_CONTAINERS:
        rows, embedded_keys, skipped_keys, warnings = _metadata_rows_for_arbitrary_fields(tag_bag)
        embedded_sorted = _sorted_unique_strings(embedded_keys)
        skipped_sorted = [
            key
            for key in _sorted_unique_strings(skipped_keys)
            if key not in set(embedded_sorted)
        ]
        warnings_sorted = _sorted_unique_strings(warnings)
        return (
            _ffmpeg_metadata_args(rows),
            embedded_sorted,
            skipped_sorted,
            warnings_sorted,
        )

    if container_id == "wav":
        rows, embedded_keys, skipped_keys, warnings = _metadata_rows_for_wav_info(tag_bag)
        embedded_sorted = _sorted_unique_strings(embedded_keys)
        skipped_sorted = [
            key
            for key in _sorted_unique_strings(skipped_keys)
            if key not in set(embedded_sorted)
        ]
        warnings_sorted = _sorted_unique_strings(warnings)
        return (
            _ffmpeg_metadata_args(rows),
            embedded_sorted,
            skipped_sorted,
            warnings_sorted,
        )

    all_keys = _all_tag_keys(tag_bag)
    warnings = list(tag_bag.warnings)
    if all_keys:
        warnings.append(
            (
                "Metadata export is not supported for output container "
                f"{container_id or output_container_format_id!r}."
            )
        )
    return (
        [],
        [],
        all_keys,
        _sorted_unique_strings(warnings),
    )


def metadata_receipt_mapping(
    *,
    output_container_format_id: str,
    embedded_keys: Sequence[str],
    skipped_keys: Sequence[str],
    warnings: Sequence[str],
    sidecar_json_path: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic metadata receipt mapping for reports/deliverables."""
    embedded = _sorted_unique_strings(embedded_keys)
    skipped = [
        key
        for key in _sorted_unique_strings(skipped_keys)
        if key not in set(embedded)
    ]
    payload: dict[str, Any] = {
        "container_format": _normalize_container_id(output_container_format_id),
        "embedded_keys": embedded,
        "skipped_keys": skipped,
        "warnings": _sorted_unique_strings(warnings),
    }
    sidecar_path = _coerce_str(sidecar_json_path).strip()
    if sidecar_path:
        payload["sidecar_json_path"] = sidecar_path
    return payload


def metadata_receipt_sidecar_payload(
    *,
    tag_bag: TagBag,
    output_container_format_id: str,
    embedded_keys: Sequence[str],
    skipped_keys: Sequence[str],
    warnings: Sequence[str],
) -> dict[str, Any]:
    """Build optional sidecar payload for skipped metadata preservation."""
    return {
        "schema_version": "0.1.0",
        "metadata_receipt": metadata_receipt_mapping(
            output_container_format_id=output_container_format_id,
            embedded_keys=embedded_keys,
            skipped_keys=skipped_keys,
            warnings=warnings,
        ),
        "tags": tag_bag_to_mapping(tag_bag),
    }
