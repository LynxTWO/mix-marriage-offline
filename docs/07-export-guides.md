# Export guides

<!-- markdownlint-disable-file MD013 -->

MMO works best when stems are exported consistently. This guide is DAW-agnostic
and focuses on rules that prevent the most common failures.

## Quick checklist

Before you export:

- All stems start at 0:00 (sample aligned).
- All stems are the same length (include reverb and delay tails).
- Same sample rate and bit depth for every file.
- No clipping. Leave headroom.
- Clear naming so roles can be assigned.

## Quick CLI flow

Use the demo stems generator to create deterministic stems, then run the
one-shot analyzer.

```sh
PYTHONPATH=src python tools/make_demo_stems.py /tmp/mmo_demo
PYTHONPATH=src python tools/analyze_stems.py /tmp/mmo_demo --out-report examples/demo_run/out.json --peak --csv examples/demo_run/recall.csv
```

Use `--keep-scan` to retain the intermediate `examples/demo_run/out.scan.json`
scan output.

Artifacts:

- `examples/demo_run/out.json` (final report after the plugin pipeline)
- `examples/demo_run/recall.csv` (recall/export summary)

## Render-many demo (7.1.4 SMPTE + FILM, all 5 standards)

Use the built-in `--demo` flag to run the render-many-standards end-to-end flow.
It loads the `fixtures/immersive/report.7_1_4.json` fixture and renders in
dry-run mode for all 5 channel-ordering standards (SMPTE, FILM, LOGIC_PRO, VST3,
AAF) in parallel. No audio files are required.

```sh
PYTHONPATH=src python -m mmo safe-render \
  --demo \
  --plugins plugins \
  --out-dir examples/demo_immersive \
  --profile PROFILE.ASSIST
```

Per-standard receipts are written to:

- `examples/demo_immersive/SMPTE/receipt.json`
- `examples/demo_immersive/FILM/receipt.json`
- `examples/demo_immersive/LOGIC_PRO/receipt.json`
- `examples/demo_immersive/VST3/receipt.json`
- `examples/demo_immersive/AAF/receipt.json`

To run the full (non-dry-run) render-many for a real 7.1.4 session, use:

```sh
PYTHONPATH=src python -m mmo safe-render \
  --report /path/to/report.json \
  --plugins plugins \
  --render-many \
  --render-many-targets stereo,5.1,7.1.4 \
  --layout-standard SMPTE \
  --out-dir rendered \
  --receipt-out receipt.json \
  --profile PROFILE.ASSIST
```

To include a headphone deliverable, add `binaural` explicitly in
`--render-many-targets`:

```sh
PYTHONPATH=src python -m mmo safe-render \
  --report /path/to/report.json \
  --plugins plugins \
  --render-many \
  --render-many-targets stereo,5.1,7.1.4,binaural \
  --layout-standard SMPTE \
  --out-dir rendered \
  --receipt-out receipt.json \
  --profile PROFILE.ASSIST
```

`binaural` (alias of `TARGET.HEADPHONES.BINAURAL` / `LAYOUT.BINAURAL`) is a
headphone deliverable. MMO renders an internal speaker-layout source first
(7.1.4, else 5.1, else stereo), then deterministically virtualizes to 2-channel
binaural output.

To render in Film (Pro Tools) channel order:

```sh
PYTHONPATH=src python -m mmo safe-render \
  --report /path/to/report.json \
  --plugins plugins \
  --render-many \
  --layout-standard FILM \
  --out-dir rendered_film \
  --receipt-out receipt_film.json \
  --profile PROFILE.ASSIST
```

Agent harness with combined schema + ontology scope:

```sh
python -m tools.agent.run graph-only --preset schemas,ontology
```

## Render (optional)

If you want MMO to render only conservative gain/trim recommendations, use the
renderer tool. It only applies low-risk, approval-free, negative gain/trim
values.

```sh
PYTHONPATH=src python tools/render_gain_trim.py /tmp/mmo_demo --report examples/demo_run/out.json --out-dir rendered
```

You can also run the renderer as part of the analyze flow:

```sh
PYTHONPATH=src python tools/analyze_stems.py /tmp/mmo_demo --out-report examples/demo_run/out.json --peak --render-gain-trim-out rendered
```

## Recommended file format

- WAV, PCM
- 24-bit (or 32-bit float if your DAW supports it cleanly)
- Keep the session sample rate (44.1k, 48k, 96k). Do not mix rates inside one
  folder.

This recommendation is about source stems you hand to MMO. MMO's own delivery
export finalization contract is documented separately below.

## Deterministic export finalization policy (v1)

MMO keeps internal processing in float64 until the final delivery boundary.
`src/mmo/dsp/export_finalize.py` is the canonical v1 contract for integer PCM
export finalization.

### What the core finalization step does

- resolves the deterministic dither policy for the target integer PCM bit depth
- derives a deterministic seed from `job_id`, `layout_id`, optional `stem_id`,
  and `render_seed` using `sha256_v1`
- clamps float64 samples to `[-1.0, 1.0)` before quantization
- rounds to signed PCM integers and clamps again to the target integer range
- emits an `export_finalization_receipt` into manifests and reports

### Default policy by output type

- Float export: `none`
  - Normative rule: do not dither or noise-shape IEEE float output.
  - Current v1 note: the shipped receipt schemas only model integer PCM
    finalization (`bit_depth` enum `16 | 24 | 32`), so float-output receipts are
    forward-looking and are not emitted by current renderers.
- PCM 16-bit integer: default `tpdf`
- PCM 24-bit integer: default `none`
- PCM 32-bit integer (`pcm_s32le`): default `none`

### Supported v1 dither policies

- `none`: no dither
- `tpdf`: deterministic triangular PDF dither
- `tpdf_hp`: deterministic high-pass TPDF using the previous per-channel TPDF
  sample as a simple error-shaping term

`tpdf_hp` is the only spectrum-shaped variant in the core v1 contract. It is
not a general psychoacoustic noise-shaping family.

### Noise-shaped policy handling

General noise-shaped export policies are **out of v1** for the core contract.
That is intentional and enforced by the current receipt schemas, which only
allow `none`, `tpdf`, and `tpdf_hp`.

If a future release adds true noise-shaped export policies, it must do so
explicitly by updating:

- `src/mmo/dsp/export_finalize.py`
- `schemas/render_manifest.schema.json`
- `schemas/apply_manifest.schema.json`
- `schemas/render_report.schema.json`

No renderer or plugin may silently invent a new export policy string in v1.

### Receipt fields and where they appear

The deterministic export contract is emitted as `export_finalization_receipt`
with these fields:

- `bit_depth`
- `dither_policy`
- `seed_derivation`
  - `algorithm`
  - `job_id`
  - `layout_id`
  - optional `stem_id`
  - `render_seed`
- `clamp_behavior`
- `target_peak_dbfs`

Current receipt locations:

- `render_manifest.renderer_manifests[*].outputs[*].export_finalization_receipt`
- `apply_manifest.renderer_manifests[*].outputs[*].export_finalization_receipt`
- `render_report.jobs[*].output_files[*].export_finalization_receipt`
- `render_report.stage_evidence[*].evidence.export_finalization_receipt`

The stage-evidence copy is useful for plan-only or report-level review. The
per-output copy is the artifact-level receipt.

### Target peak handling

`target_peak_dbfs` records a renderer-selected delivery peak target when one has
already been applied before byte serialization. Current shipped behavior is:

- `mixdown_renderer` and `placement_mixdown_renderer` populate
  `target_peak_dbfs` with `-1.0`
- `gain_trim_renderer` uses `null`
- plan-only/render-engine report assembly may also use `null` when it is only
  describing the planned export policy rather than a measured peak-targeted
  render

So in v1, export finalization records peak-target intent when available, but
`export_finalize.py` itself is the deterministic dither/clamp/quantize step.

Avoid:

- MP3/AAC or any other lossy exports. For lossless stems, use WAV, FLAC, or
  WavPack (all acceptable).
- Normalization on export
- Per-stem limiting that changes the intent

## Supported stem formats (current)

MMO detects several stem formats by extension. WAV metadata is always decoded;
FLAC/WavPack metadata is decoded when ffprobe/FFmpeg is available (or
MMO_FFPROBE_PATH is set).

WAV (.wav/.wave):

- Metadata supported.

Lossless:

- FLAC (.flac), WavPack (.wv)
- Warning: requires ffprobe/FFmpeg for metadata. If missing, install FFmpeg or
  set MMO_FFPROBE_PATH.

Lossless detected but not decoded yet:

- AIFF (.aif/.aiff)
- Warning: unsupported format. Export WAV for analysis.

Lossy formats:

- MP3 (.mp3), AAC (.aac), Ogg (.ogg), Opus (.opus)
- Warning: lossy stems are discouraged because further processing and resampling
  can compound artifacts and make comparisons less reliable.

M4A (.m4a):

- Ambiguous container (AAC or ALAC). Treated as unsupported until probed.

## Metadata behavior by output container

MMO now does best-effort tag round-trip during render/transcode and records a
deterministic `metadata_receipt` for each output.

- FLAC (`.flac`):
  - Arbitrary tag fields are supported.
  - MMO writes normalized tag keys plus deterministic raw-tag preservation
    fields via explicit ffmpeg `-metadata` args.
- WavPack (`.wv`):
  - Same policy as FLAC (arbitrary fields, normalized + raw preservation).
- WAV (`.wav`):
  - Conservative `LIST/INFO` subset only.
  - MMO maps common keys (title/artist/album/date/etc.) to INFO fields and
    records all non-INFO keys as skipped.

Receipts are visible in:

- `render_report.jobs[*].output_files[*].metadata_receipt`
- deliverables index file rows when sourced from render/apply manifests with
  receipt metadata.

## Strict mode

Running `scan_session --strict` elevates lossy and unsupported format warnings
to higher severity for CI and advanced checks.

## Stem alignment rules

MMO assumes stems can be summed and compared.

Required:

- Stems must start at the same timeline point (0:00).
- Stems must be the same duration.

Common mistakes:

- Render as used that trims silence differently per stem.
- Printing effects with tails cut off.
- Exporting only regions that do not line up.

## Naming conventions

MMO can work with friendly names, but consistency helps.

### Option A (recommended): role-first naming

Use the canonical role ID in the filename.

Examples:

- `01_ROLE.DRUMS.KICK.wav`
- `02_ROLE.DRUMS.SNARE.wav`
- `10_ROLE.VOCALS.LEAD.wav`

### Option B: human naming with a mapping file

If you prefer names like:

- `Kick In.wav`
- `Lead Vox.wav`

Add a mapping file later (planned) or keep a simple text note for now. The goal
is that every stem can be assigned a `ROLE.*` deterministically.

## Folder layout convention

Recommended:

```text
MySong/
stems/
01_ROLE.DRUMS.KICK.wav
02_ROLE.DRUMS.SNARE.wav
03_ROLE.BASS.BASS.wav
10_ROLE.VOCALS.LEAD.wav
refs/
REF_mix_you_like.wav
```

Notes:

- `refs/` is optional. Reference tracks are not included in the mix sum.
- Keep the folder self-contained so it can be zipped and shared.

## What to do about buses

If you export both stems and buses, be explicit.

Recommended:

- Export raw stems.
- Optionally export a few buses if they represent your intent:
  - `BUS_DRUMS.wav`
  - `BUS_MUSIC.wav`
  - `BUS_VOCALS.wav`

Avoid:

- exporting only buses and calling them stems
- double-printing (stems already include bus processing)

## Printing effects

Decide what truth you want MMO to evaluate.

Typical options:

- Dry stems only (effects separate)
- Printed stems including their creative effects
- Hybrid: vocals printed, drums dry, etc.

Whatever you choose, keep it consistent and name it clearly:

- `ROLE.VOCALS.LEAD_PRINTED.wav`
- `ROLE.VOCALS.LEAD_DRY.wav`

## Multichannel and surround exports

If you export multichannel stems (5.1, 7.1.4), consistency matters.

Recommended:

- Interleaved multichannel WAV per stem.
- Use a single known layout and keep it consistent across all stems.

You should be able to declare one `LAYOUT.*` for the session, such as:

- `LAYOUT.STEREO`
- `LAYOUT.5_1`
- `LAYOUT.7_1_4`
- `LAYOUT.5_2` / `LAYOUT.7_2` / `LAYOUT.7_2_4` (dual-LFE x.2 layouts)

### Dual-LFE WAV edge case (x.2 layouts)

WAV `WAVEFORMATEXTENSIBLE` defines only one standard LFE bit in `dwChannelMask`.
For dual-LFE exports (`SPK.LFE` + `SPK.LFE2`), MMO uses a conservative strategy:

- keep canonical SPK channel order in contracts/reports/recall exports,
- write WAV with a direct-out style mask strategy (`channel_mask=0`),
- include warnings when a toolchain may collapse or relabel `LFE2`.

When FFmpeg is used for export/transcode and supports `LFE2` layout strings, MMO
passes explicit layout strings such as:

- `FL+FR+FC+LFE+LFE2+SL+SR` (5.2)
- `FL+FR+FC+LFE+LFE2+SL+SR+BL+BR` (7.2)

Validation workflow:

- Confirm `render_report.jobs[*].channel_order` contains both `SPK.LFE` and
  `SPK.LFE2`.
- Confirm `render_report.jobs[*].ffmpeg_channel_layout` contains `LFE2`.
- Run ffprobe and confirm the expected layout token order:

```sh
ffprobe -v error -select_streams a:0 -show_entries stream=channels,channel_layout -of json out.wav
```

### Missing-LFE derivation (policy-driven, deterministic)

When a target layout includes LFE channels but source program content has no
LFE, MMO records a deterministic derivation receipt in plan/report contracts.

Defaults:

- profile: `LFE_DERIVE.DOLBY_120_LR24_TRIM_10` (120 Hz low-pass, LR24, -10 dB
  trim)
- alternate profile: `LFE_DERIVE.MUSIC_80_LR24_TRIM_10` (80 Hz low-pass, LR24,
  -10 dB trim; conservative bass-management-safe rolloff)
- mode: `mono`

Phase-maximization rule for derived LFE:

- candidate A: `lowpass(L) + lowpass(R)` (`L+R`)
- candidate B: `lowpass(L) + lowpass(-R)` (`L-R`)
- if loudness/energy delta is `>= 0.1 dB`, MMO selects the stronger candidate

Dual-LFE targets:

- default behavior is mirrored mono (`LFE1 = LFE2`)
- if `lfe_mode=stereo`, MMO derives `lowpass(L)` / `lowpass(R)` and can flip R
  (`flipped R`) when mono-sum loudness improves by `>= 0.1 dB`

Receipt fields include:

- selected profile and mode
- chosen sum mode (`L+R`, `L-R`, or `flipped R`)
- measured `delta_db` and threshold
- whether derivation ran and why (derived, passthrough, or not run for dry
  contract planning)

Avoid:

- mixing interleaved and split-mono formats in the same folder
- exporting different channel orders stem to stem

If your DAW exports split mono only, keep the grouping obvious:

- `ROLE.MUSIC.PAD__ch00.wav`
- `ROLE.MUSIC.PAD__ch01.wav`
- and document the channel order used.

## Immersive / height exports (7.1.4 beds)

For Dolby Atmos-style bed exports (5.1.2, 5.1.4, 7.1.2, 7.1.4), additional rules
apply.

### Supported immersive layouts

| Layout | Channels | Height speakers      | Render target            |
| ------ | -------- | -------------------- | ------------------------ |
| 5.1.2  | 8        | TFL, TFR (front top) | `TARGET.IMMERSIVE.5_1_2` |
| 5.1.4  | 10       | TFL, TFR, TRL, TRR   | `TARGET.IMMERSIVE.5_1_4` |
| 7.1.2  | 10       | TFL, TFR (front top) | `TARGET.IMMERSIVE.7_1_2` |
| 7.1.4  | 12       | TFL, TFR, TRL, TRR   | `TARGET.IMMERSIVE.7_1_4` |

### Channel ordering standards

MMO supports five channel-ordering standards. The internal canonical is always
**SMPTE**. All imports from other standards are remapped to SMPTE at the file
boundary. All exports remap from SMPTE back to the target standard.

| Standard  | Used by                                                                                      | Internal?        |
| --------- | -------------------------------------------------------------------------------------------- | ---------------- |
| SMPTE     | WAV (WAVEFORMATEXTENSIBLE), FLAC, WavPack, FFmpeg, Dolby Atmos beds, Netflix delivery, DCP   | **Yes — always** |
| FILM      | Pro Tools internal tracks/metering, cinema dubbing stages, theatrical feature-film pipelines | No               |
| LOGIC_PRO | Logic Pro bounces, DTS-native files, Apple ecosystem                                         | No               |
| VST3      | Steinberg Cubase/Nuendo for 7.1+; follows SMPTE for ≤5.1                                     | No               |
| AAF       | AAF/OMF/XML interchange (ordering read from per-channel labels, not assumed)                 | No               |

#### SMPTE / ITU-R BS.775 (default)

| Layout | Channel order                           |
| ------ | --------------------------------------- |
| 2.0    | L R                                     |
| 2.1    | L R LFE                                 |
| 5.1    | L R C LFE Ls Rs                         |
| 7.1    | L R C LFE Ls Rs Lrs Rrs                 |
| 5.1.2  | L R C LFE Ls Rs TFL TFR                 |
| 5.1.4  | L R C LFE Ls Rs TFL TFR TRL TRR         |
| 7.1.2  | L R C LFE Ls Rs Lrs Rrs TFL TFR         |
| 7.1.4  | L R C LFE Ls Rs Lrs Rrs TFL TFR TRL TRR |

Verify 7.1.4 SMPTE: the first four channels must be L, R, C, LFE.

#### Film / Cinema / Pro Tools

| Layout | Channel order                           |
| ------ | --------------------------------------- |
| 2.0    | L R                                     |
| 2.1    | L R LFE                                 |
| 5.1    | L C R Ls Rs LFE                         |
| 7.1    | L C R Ls Rs Lrs Rrs LFE                 |
| 5.1.2  | L C R Ls Rs LFE TFL TFR                 |
| 5.1.4  | L C R Ls Rs LFE TFL TFR TRL TRR         |
| 7.1.2  | L C R Ls Rs Lrs Rrs LFE TFL TFR         |
| 7.1.4  | L C R Ls Rs Lrs Rrs LFE TFL TFR TRL TRR |

#### Logic Pro / DTS

| Layout | Channel order           |
| ------ | ----------------------- |
| 5.1    | L R Ls Rs C LFE         |
| 7.1    | L R Lrs Rrs Ls Rs C LFE |

Logic Pro bounces a "5.1 WAV" without a channel mask — it is very likely in
LOGIC_PRO order even if the header does not state it.

#### Steinberg VST3 (Cubase / Nuendo) for 7.1+

Follows SMPTE for ≤5.1. For 7.1+, rear surrounds (Lrs/Rrs) occupy slots 4-5 and
side surrounds (Lss/Rss) occupy slots 6-7 — the reverse of SMPTE.

| Layout | Channel order                             |
| ------ | ----------------------------------------- |
| 7.1    | L R C LFE Lrs Rrs Lss Rss                 |
| 7.1.4  | L R C LFE Lrs Rrs Lss Rss TFL TFR TRL TRR |

#### AAF / OMF / XML interchange

AAF containers carry explicit per-channel speaker labels or a channel mask. The
ordering must be read from the metadata, not assumed. Use
`--layout-standard AAF` when a layout was inferred from AAF metadata.

### Specifying the layout standard on the CLI

Pass `--layout-standard <STANDARD>` to any render or export command to declare
the active ordering for file I/O. MMO will remap at the import/export boundary.

```sh
# Analyze stems in SMPTE order (default — no flag needed)
PYTHONPATH=src python tools/analyze_stems.py /path/to/stems \
  --out-report out.json --csv recall.csv

# Analyze stems exported from Pro Tools (Film order)
PYTHONPATH=src python tools/analyze_stems.py /path/to/stems \
  --layout-standard FILM --out-report out.json --csv recall.csv

# Analyze stems bounced from Logic Pro
PYTHONPATH=src python tools/analyze_stems.py /path/to/stems \
  --layout-standard LOGIC_PRO --out-report out.json --csv recall.csv

# Analyze stems from a Cubase/Nuendo 7.1.4 session
PYTHONPATH=src python tools/analyze_stems.py /path/to/stems \
  --layout-standard VST3 --out-report out.json --csv recall.csv

# Render conservative gain/trim recommendations — Film input, SMPTE output
PYTHONPATH=src python tools/render_gain_trim.py /path/to/stems \
  --report out.json --layout-standard FILM --out-dir rendered
```

If your project uses Film ordering, pass `--layout-standard FILM` to
`mmo safe-render` so MMO generates the correct `channel_order` in the render
contract and receipt.

Export your DAW project using SMPTE channel order for best compatibility with
MMO defaults.

### Height channel rules

Height channels (TFL, TFR, TRL, TRR) at elevation 45°:

- Must be included in the interleaved stem, not as separate files.
- Export at the same level as bed channels — do not pre-attenuate heights.
- MMO applies -6 dB height-to-bed fold for downstream downmix (per
  `POLICY.DOWNMIX.IMMERSIVE_FOLDOWN_V0`).

### Height "air" guidance

Height channels carry the spatial air layer (overhead ambience, ceiling
reflections, objects above).

Recommended practices:

- Keep height content below -12 dBFS RMS to avoid overwhelming the bed.
- Treat heights conservatively: MMO is advisory, not prescriptive.
- If you intend silence in heights, still export them (as silence) to maintain
  channel count consistency.

### Downmix paths for immersive

MMO can validate fold-down translation for:

- 7.1.4 → 5.1 via `DMX.IMM.7_1_4_TO_5_1.COMPOSED`
- 7.1.4 → 2.0 via `DMX.IMM.7_1_4_TO_2_0.COMPOSED`
- 5.1.4 → 5.1 via `DMX.IMM.5_1_4_TO_5_1.HEIGHT_TO_BED`

Run downmix QA for a 7.1.4 source:

```sh
PYTHONPATH=src python -m mmo downmix qa \
  --src /path/to/714_src.wav \
  --ref /path/to/stereo_ref.wav \
  --source-layout LAYOUT.7_1_4 \
  --target-layout LAYOUT.2_0
```

## Headroom and safety

Leave room for analysis and translation checks.

Recommended:

- peaks below -1.0 dBFS on stems
- true peak below -1.0 dBTP on the mix bus export (if you include it)

Do not:

- normalize stems to 0 dBFS
- clip and assume it is fine because it is loud

## Sanity check before you run MMO

Pick 2 to 3 stems and confirm:

- they start at the same time
- they end at the same time
- summing them in your DAW lines up with expectation

If that is true, MMO can do reliable math.
