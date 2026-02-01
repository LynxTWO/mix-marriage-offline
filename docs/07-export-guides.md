# Export guides

MMO works best when stems are exported consistently. This guide is DAW-agnostic and focuses on rules that prevent the most common failures.

## Quick checklist
Before you export:
- All stems start at 0:00 (sample aligned).
- All stems are the same length (include reverb and delay tails).
- Same sample rate and bit depth for every file.
- No clipping. Leave headroom.
- Clear naming so roles can be assigned.

## Recommended file format
- WAV, PCM
- 24-bit (or 32-bit float if your DAW supports it cleanly)
- Keep the session sample rate (44.1k, 48k, 96k). Do not mix rates inside one folder.

Avoid:
- MP3/AAC or any other lossy exports. FLAC, WAV, or WAVPack files are recomended. WAVPack supports 32-bit floating point and is lossless compression. FLAC supports 24-bit (32-bit integer depending on build), and is also lossless and also supports tags.
- Normalization on export
- Per-stem limiting that changes the intent

## Supported stem formats (current)
MMO detects several stem formats by extension, but only WAV metadata is decoded today.

WAV (.wav/.wave):
- Metadata supported.

Lossless detected but not decoded yet:
- FLAC (.flac), WavPack (.wv), AIFF (.aif/.aiff)
- Warning: unsupported format. Export WAV for analysis.

Lossy formats:
- MP3 (.mp3), AAC (.aac), Ogg (.ogg), Opus (.opus)
- Warning: lossy stems are discouraged because further processing and resampling can compound artifacts and make comparisons less reliable.

M4A (.m4a):
- Ambiguous container (AAC or ALAC). Treated as unsupported until probed.

## Strict mode
Running `scan_session --strict` elevates lossy and unsupported format warnings to higher severity for CI and advanced checks.

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

Add a mapping file later (planned) or keep a simple text note for now. The goal is that every stem can be assigned a `ROLE.*` deterministically.

## Folder layout convention
Recommended:

```
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

Avoid:
- mixing interleaved and split-mono formats in the same folder
- exporting different channel orders stem to stem

If your DAW exports split mono only, keep the grouping obvious:
- `ROLE.MUSIC.PAD__ch00.wav`
- `ROLE.MUSIC.PAD__ch01.wav`
- and document the channel order used.

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
