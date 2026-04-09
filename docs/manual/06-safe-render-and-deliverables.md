# Safe-render, deliverables, and layout standards

Rendering is where tools can hurt people. MMO treats rendering as a gated,
receipt-driven action.

MMO has three related concepts. “Apply” is for low-risk fix-ups that can be
written back out. “Render” is for render-eligible recommendations. “Safe-render”
is the full bounded chain: detect, resolve, gate, then render.

Quick path (safe-render). mmo safe-render --report out/report.json --target
stereo --out-dir out/render --receipt-out out/receipt.json

Render-many (mix-once, render-many). mmo safe-render --report out/report.json
--render-many --render-many-targets stereo,5.1,7.1.4 --out-dir out/deliverables
--receipt-out out/receipt.json

Baseline outputs are always produced. Even when zero recommendations are
render-eligible, safe-render writes a conservative baseline WAV master for
supported layout targets.

One scene, many targets. MMO can render a single layout-agnostic scene into 2.0,
5.1, 7.1, 7.1.4, and 9.1.6. Conservative placement rules keep kick/snare/bass
anchors front-safe by default, while ambience and bed-like stems can receive
modest surround spread and subtle height sends on immersive targets.

Requesting “in the middle of the band/orchestra”. Wrap-style transient placement
is opt-in and evidence-gated. Use an explicit immersive marker (`IN_THE_MIDDLE`,
`MIDDLE_OF_BAND`, `MIDDLE_OF_ORCHESTRA`) and keep width/depth/confidence high.
Without both explicit intent and high evidence, anchors stay front-safe.

Channel-ordering standards. MMO processes internally using SMPTE ordering. MMO
can export in SMPTE, FILM, LOGIC_PRO, VST3, or AAF ordering.

Example. mmo safe-render --report out/report.json --render-many
--layout-standard FILM --out-dir out/deliverables_film --receipt-out
out/receipt_film.json

Output formats. Lossless formats are supported: wav, flac, wv, aiff, alac. (Some
formats depend on FFmpeg availability.)

Headphone preview. Use `--preview-headphones` to create deterministic headphone
preview files alongside renders.

Dry-run is your friend. Use `--dry-run` to generate the plan and receipt without
writing audio.

Approvals are explicit. Use `--approve` to override blocks when you
intentionally want to cross a safety boundary. You can approve none, all, or a
comma-separated list of recommendation IDs.

LFE derivation. For surround and immersive targets (5.1, 7.1, 7.1.4, etc.) MMO
derives LFE channel content automatically from the mixed L+R program audio using
a Linkwitz-Riley 24 dB/oct low-pass filter. Two profiles are available:

- `LFE_DERIVE.DOLBY_120_LR24_TRIM_10` — 120 Hz crossover, −10 dB trim (cinema default)
- `LFE_DERIVE.MUSIC_80_LR24_TRIM_10` — 80 Hz crossover, −10 dB trim (music default)

The derivation receipt (profile used, cutoff, phase mode, status) appears in
`render_manifest.json` under `metadata.lfe_derivation` for each surround output.

Reviewing pending approvals. Before running safe-render you can inspect which
recommendations require explicit approval:

```sh
mmo review out/report.json
```

This prints a table of pending approvals with the exact `--approve-rec` flags to
pass to `mmo safe-render`. Use `--format json` for machine-readable output or
`--risk high` to filter by risk level.

Pro notes. Keep the receipt JSON with the deliverables. That is your defensible
audit trail. If you are delivering “.2” targets, the LFE derivation is applied
automatically — check the receipt to confirm the profile and crossover used.
