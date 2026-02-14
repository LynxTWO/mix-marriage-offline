# 20. Stems Audition Pack

This guide describes the `stems audition` command, which renders short per-bus-group
WAV bounces from a classified `stems_map`, plus a deterministic manifest.

## What is an audition pack?

After classification, you know which stems belong to DRUMS, BASS, VOCALS, etc.
An audition pack creates a quick WAV preview for each bus group so you can listen
to the grouped stems without loading them into a DAW. This is useful for:

- Verifying classification results by ear.
- Sharing lightweight previews with collaborators.
- Spot-checking before committing to a full render pipeline.

## Running the command

After you have a `stems_map.json` (from `stems classify` or `stems pipeline`):

```powershell
python -m mmo stems audition --stems-map stems_map.json --stems-dir ./stems/ --out-dir auditions/
```

This produces:

- `auditions/stems_auditions/<bus_group>.wav` for each bus group with renderable stems
- `auditions/stems_auditions/manifest.json` describing all outputs and warnings

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--stems-map` | (required) | Path to `stems_map.json` |
| `--stems-dir` | (required) | Root directory where stem audio files live |
| `--out-dir` | (required) | Output directory (auditions written to `<out-dir>/stems_auditions/`) |
| `--segment` | `30` | Audition segment length in seconds |
| `--format` | `json` | Output format: `json` or `text` |
| `--overwrite` | off | Allow overwriting existing audition outputs |

### Example JSON output

```json
{
  "attempted_groups_count": 3,
  "manifest_path": "auditions/stems_auditions/manifest.json",
  "missing_files_count": 0,
  "ok": true,
  "out_dir": "auditions/stems_auditions",
  "rendered_groups_count": 3,
  "skipped_mismatch_count": 0
}
```

## Determinism

All outputs are deterministic given the same inputs:

- **Group ordering**: sorted lexicographically by `bus_group_id`.
- **Stem ordering within groups**: sorted lexicographically by `rel_path`.
- **Filename slugging**: lowercase, non-alphanumeric characters replaced with `_`,
  collapsed and stripped.  Example: `"DRUMS"` becomes `drums.wav`.
- **Manifest JSON**: written with `indent=2, sort_keys=True`.
- **WAV output**: identical bytes across runs for the same inputs.

## Limitations

- **No resampling**: all stems in a group must share the same sample rate.
  The target sample rate is set by the first renderable file (by sorted order).
  Files with a different rate are skipped with a warning.
- **16-bit only**: only 16-bit WAV files are supported.  Other bit depths are skipped.
- **Max 2 channels**: files with more than 2 channels are skipped.
- **No ffmpeg**: uses Python `wave` module only (stdlib).
- **Mono-to-stereo upmix**: mono files are upmixed by duplicating the channel
  when the target is stereo.
- **Truncation/padding**: sources longer than the segment length are truncated;
  shorter sources are zero-padded to the exact segment length.
- **Mixing**: frames are accumulated in int32 and clamped to int16.
  No normalization or limiting is applied.

## Manifest format

The `manifest.json` file validates against `schemas/stems_audition_manifest.schema.json`
and contains:

| Field | Type | Description |
|-------|------|-------------|
| `segment_seconds` | number | Requested segment duration |
| `stems_dir` | string | Source stems directory (forward slashes) |
| `groups` | array | One entry per bus group (sorted by `bus_group_id`) |
| `warnings` | array | Sorted list of warning strings |
| `rendered_groups_count` | integer | Number of groups that produced a WAV |
| `attempted_groups_count` | integer | Total number of bus groups found |

Each group entry contains:

| Field | Type | Description |
|-------|------|-------------|
| `bus_group_id` | string | The bus group identifier |
| `output_wav` | string | Filename of the output WAV (empty if not rendered) |
| `stems_included` | array | Sorted list of `rel_path` values mixed into this WAV |
| `stems_missing` | array | Sorted list of missing `rel_path` values |
| `stems_skipped_mismatch` | array | Sorted list of `{rel_path, reason}` objects |

## Error handling

If **no groups** produce any renderable output, the command exits with code 1
and prints a stable JSON error:

```json
{
  "error_code": "NO_RENDERABLE_GROUPS",
  "groups_attempted_count": 2,
  "missing_files_count": 2,
  "ok": false
}
```

Individual missing or incompatible files are recorded as warnings in the manifest
but do not prevent other groups from rendering.
