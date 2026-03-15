# Mix Marriage Offline (MMO)

[![CI](https://github.com/LynxTWO/mix-marriage-offline/actions/workflows/ci.yml/badge.svg)](https://github.com/LynxTWO/mix-marriage-offline/actions/workflows/ci.yml)
[![Policy Validation](https://github.com/LynxTWO/mix-marriage-offline/actions/workflows/policy-validation.yml/badge.svg)](https://github.com/LynxTWO/mix-marriage-offline/actions/workflows/policy-validation.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

An open-source, offline mixing assistant for deterministic analysis,
layout-agnostic scene intent, and mix-once/render-many delivery.

Website:
[lynxtwo.github.io/mix-marriage-offline](https://lynxtwo.github.io/mix-marriage-offline/)

MMO is not a DAW plugin and it is not "AI that mixes your song for you." It is a
technical co-pilot that keeps the engineering side honest while the human keeps
the musical intent.

## What MMO Ships Today

- Deterministic contract artifacts for analysis and delivery: `report.json`,
  `scene.json`, `render_plan.json`, `render_report.json`,
  `render_manifest.json`, `receipt.json`, and `compare_report.json`.
- CLI workflows for `scan`, `analyze`, `run`, `safe-render`, `compare`,
  `project`, `watch`, `scene`, `render-plan`, and `render-run`.
- Mix-once/render-many delivery from one scene into multiple target layouts.
- A compare workflow that can write `compare_report.json` and compare PDF
  exports, with fair-listen `loudness_match` disclosure when sibling
  `render_qa.json` artifacts exist.
- First-class render targets for stereo, surround, immersive, and headphone
  delivery, including deterministic binaural/headphone preview flows.
- Five supported channel-ordering standards at the I/O boundary: `SMPTE`,
  `FILM`, `LOGIC_PRO`, `VST3`, and `AAF`.
- A shipped Tauri desktop app path for packaged releases, plus the legacy
  CustomTkinter fallback GUI while Tauri parity is still finishing.
- Offline plugin marketplace/discovery, project/session artifacts, translation
  QA, downmix QA, and watch-folder batch automation.

## Still Not Complete Yet

- The Tauri desktop app is the primary GUI path, but it does not yet have full
  parity for scene-lock editing.
- Cross-platform packaged desktop smoke coverage now gates the shipped Tauri
  bundles on Windows, macOS, and Linux.
- The legacy `mmo-gui` fallback remains available during the transition, but it
  is not the long-term primary GUI.
- MMO does not claim to replace proprietary Atmos renderers or licensed Dolby
  workflows.

## Install And Runtime Expectations

Recommended for end users:

- Download the packaged desktop release from GitHub Releases.
- Release assets provide a Windows installer, macOS app bundle, and Linux
  AppImage for the Tauri desktop app.

Source install:

```sh
pip install .
```

Optional extras:

```sh
pip install .[pdf]
pip install .[gui]
pip install .[watch]
```

Runtime expectations:

- Python `3.12+` for source installs.
- FFmpeg and ffprobe are expected for core audio workflows such as decode,
  render, metadata handling, and QA on real-world sessions.
- NumPy is part of the base install.
- ReportLab is only needed for PDF exports.
- `.[gui]` installs the legacy fallback `mmo-gui` entrypoint.

Verify your environment:

```sh
mmo --help
mmo env doctor --format text
```

If FFmpeg or ffprobe are not on `PATH`, set `MMO_FFMPEG_PATH` and
`MMO_FFPROBE_PATH`.

## Current Workflow Snapshot

Quick one-button run:

```sh
mmo run --stems ./stems --out out/run_001 --export-csv --export-pdf --bundle
```

What that gets you:

- deterministic analysis artifacts in one output folder
- `report.json` plus optional PDF/CSV exports
- optional `scene.json`, `render_plan.json`, `ui_bundle.json`, and delivery
  helpers when requested

Project scaffold flow:

```sh
mmo project init --stems-root ./stems --out-dir ./project
mmo project refresh --project-dir ./project --stems-root ./stems
```

This is the clean path for longer-running sessions, teams, and GUI-backed
workspaces.

## Compare Workflow

MMO can compare two runs or two report folders and write a deterministic
artifact describing what changed.

```sh
mmo compare \
  --a out/run_a/report.json \
  --b out/run_b/report.json \
  --out out/compare_report.json \
  --pdf out/compare_report.pdf
```

When sibling `render_qa.json` files are present, the compare artifact also
records the evaluation-only loudness compensation MMO used for fair listening.

## Mix-Once, Render-Many

Safe-render is the bounded, receipt-driven render flow:

```sh
mmo safe-render \
  --report out/run_001/report.json \
  --render-many \
  --render-many-targets stereo,5.1,7.1.4,binaural \
  --layout-standard SMPTE \
  --preview-headphones \
  --out-dir out/deliverables \
  --receipt-out out/receipt.json
```

What ships in this path today:

- deterministic scene-aware render contracts
- one scene rendered to many targets in one pass
- conservative fallback sequencing and QA receipts
- explicit approval gates for higher-impact recommendations
- optional headphone preview WAVs via `--preview-headphones`

`run --render-many` is also available when you want analyze plus delivery in one
command:

```sh
mmo run \
  --stems ./stems \
  --out out/run_render_many \
  --render-many \
  --targets TARGET.STEREO.2_0,TARGET.SURROUND.5_1,TARGET.IMMERSIVE.7_1_4 \
  --translation \
  --deliverables-index \
  --listen-pack
```

## Targets, Layouts, And Ordering Standards

Current first-class render targets include:

- stereo: `2.0`, `2.1`
- front stage: `3.0`, `3.1`
- surround: `4.0`, `4.1`, `5.1`, `7.1`
- immersive: `5.1.2`, `5.1.4`, `7.1.2`, `7.1.4`, `9.1.6`
- headphones: `binaural`

The layout registry also includes additional layouts used for validation and
routing contracts, including `7.1.6`, `SDDS 7.1`, and `32CH`.

MMO keeps internal processing in canonical `SMPTE` order and remaps at the I/O
boundary for these standards:

| Standard    | Typical use                         |
| ----------- | ----------------------------------- |
| `SMPTE`     | broadcast, FFmpeg, WAV/FLAC/BWF     |
| `FILM`      | Pro Tools and cinema-style ordering |
| `LOGIC_PRO` | Logic Pro / DTS ordering            |
| `VST3`      | Cubase / Nuendo 7.1+ ordering       |
| `AAF`       | metadata-driven interchange         |

See [docs/18-channel-standards.md](docs/18-channel-standards.md) and
[docs/15-target-selection.md](docs/15-target-selection.md) for the canonical
contracts.

## Desktop App Status

MMO currently has two desktop paths:

- Primary path: the packaged Tauri desktop app in
  [gui/desktop-tauri/README.md](gui/desktop-tauri/README.md)
- Fallback path: the legacy CustomTkinter `mmo-gui` flow documented in
  [docs/manual/10-gui-walkthrough.md](docs/manual/10-gui-walkthrough.md)

Tauri already covers the artifact-backed workflow sequence:
`Validate -> Analyze -> Scene -> Render -> Results -> Compare`.

Fallback GUI status:

- still available for bounded desktop workflows
- still useful when you want the old point-and-click pipeline quickly
- intentionally treated as fallback-only until Tauri parity is complete

## Documentation

Start here: [docs/README.md](docs/README.md)

Recommended reads:

- [docs/manual/00-manual-overview.md](docs/manual/00-manual-overview.md)
- [docs/00-quickstart.md](docs/00-quickstart.md)
- [docs/02-architecture.md](docs/02-architecture.md)
- [docs/15-target-selection.md](docs/15-target-selection.md)
- [docs/18-channel-standards.md](docs/18-channel-standards.md)
- [docs/11-gui-vision.md](docs/11-gui-vision.md)
- [docs/gui_parity.md](docs/gui_parity.md)
- [docs/STATUS.md](docs/STATUS.md)

## Repo Layout

```text
docs/       Canonical docs and user manual
ontology/   YAML source of truth for IDs, layouts, policies, and presets
schemas/    JSON schemas for reports, scenes, renders, plugins, and projects
src/        MMO engine, CLI, bundled data, and GUI bridge code
gui/        Desktop app implementations (Tauri primary, CTK fallback)
fixtures/   Deterministic audio and contract fixtures
tests/      Cross-platform regression coverage
tools/      Validation and workflow helper scripts
```

## License

Apache-2.0. See [LICENSE](LICENSE).
