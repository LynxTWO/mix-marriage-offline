# 17 Metadata and Tags

This document defines MMO's canonical tag preservation model and how tags are
read from source media.

## TagBag model

MMO stores source tags as a `TagBag`:

- `raw`: ordered list of `RawTag` entries.
- `normalized`: case-insensitive key map (`lower(key) -> [values]`) that keeps duplicates.
- `warnings`: non-fatal parse warnings.

`RawTag` fields:

- `source`: `"format"` or `"stream"`
- `container`: container/format label (for example `wav`, `flac`, `m4a`)
- `scope`: tag namespace (`format`, `info`, `bext`, `ixml`, `stream:<index>`, etc.)
- `key`: original tag key
- `value`: string value
- `index`: stable source index

Deterministic ordering is enforced by sorting raw tags using:

- `(source, container, scope, lower(key), index, value)`

## ffprobe-backed metadata support

For non-WAV formats (and WAV when ffprobe is used by a caller), MMO ingests:

- `payload["format"]["tags"]`
- `payload["streams"][i]["tags"]`

Common extensions routed through ffprobe in MMO include:

- `.flac`, `.wv`, `.aif`, `.aiff`, `.mp3`, `.aac`, `.ogg`, `.opus`, `.m4a`

Technical metadata keys (`channels`, `sample_rate_hz`, `duration_s`, etc.)
remain unchanged. Tag extraction is additive via `tags` (TagBag).

## WAV fallback parser support

When WAV is parsed without ffprobe, MMO reads RIFF/WAVE chunks directly and
extracts tags from:

- `LIST/INFO` subchunks (for example `INAM`, `IART`, etc.)
- `bext` fields (BWF metadata as raw tags)
- `iXML` (stored as full XML string in a raw tag)

Unknown chunk handling:

- Unknown chunk IDs do not fail parsing.
- MMO records warning entries with chunk ID and chunk size.

## Unknown-tag preservation

MMO does not discard unknown metadata keys:

- All readable tags are preserved in `raw`.
- Unknown/custom keys are still included in `normalized` via lowercased keys.
- Duplicate keys and duplicate values are retained as ordered value lists.
- Non-fatal parse anomalies are recorded in `warnings`.

This model is used in source metadata artifacts (`source_metadata.tags`) so
UI/reporting can summarize canonical fields while preserving full source tags.

## Export-time tag re-embedding and receipts

When MMO renders/transcodes outputs, it now applies tags from source `TagBag`
using a deterministic export policy and emits a metadata receipt per output.

- FLAC and WavPack (`.wv`):
  - MMO emits explicit ffmpeg `-metadata key=value` fields in stable order.
  - It includes normalized keys and namespaced raw-tag preservation fields.
- WAV:
  - MMO uses a conservative RIFF `INFO` subset only (`INAM`, `IART`, `IPRD`,
    `ICRD`, `IGNR`, `ICMT`, `ITRK` via aliases).
  - Non-INFO-compatible keys are recorded as skipped in the receipt.

Receipts are attached to rendered/transcoded output descriptors as:

- `metadata_receipt.container_format`
- `metadata_receipt.embedded_keys`
- `metadata_receipt.skipped_keys`
- `metadata_receipt.warnings`
- optional `metadata_receipt.sidecar_json_path` (for external skipped-tag
  preservation workflows)
