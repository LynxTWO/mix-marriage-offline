# Mix Marriage Offline (MMO)

[![CI](https://github.com/LynxTWO/mix-marriage-offline/actions/workflows/ci.yml/badge.svg)](https://github.com/LynxTWO/mix-marriage-offline/actions/workflows/ci.yml)
[![Policy Validation](https://github.com/LynxTWO/mix-marriage-offline/actions/workflows/policy-validation.yml/badge.svg)](https://github.com/LynxTWO/mix-marriage-offline/actions/workflows/policy-validation.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

MMO is an open-source, offline mixing assistant for stem folders.

It does not "mix the song for you." Think of it more like a careful assistant
in the room: it listens to your exported parts, writes down what it found,
builds a speaker-placement plan, renders delivery versions, and leaves a clear
paper trail so you can trust what happened.

Website:
[lynxtwo.github.io/mix-marriage-offline](https://lynxtwo.github.io/mix-marriage-offline/)

## Quick Translation Of MMO Terms

- `stems folder`: the folder full of exported audio tracks from your DAW.
- `workspace`: MMO's session notebook. This is the folder where it writes every
  report, scene, render, and receipt.
- `scene`: a speaker-placement plan. Think of it like a stage plot for your
  mix, not a new audio bounce.
- `receipt`: a packing slip for the render. It says what MMO changed, what it
  refused to change, and why.
- `QA`: the post-render quality check MMO runs on the files it wrote.

## Recommended Install: Packaged Desktop App

Most end users should start with the packaged desktop release from GitHub
Releases.

Release assets ship:

- Windows installer
- macOS app bundle
- Linux AppImage
- standalone CLI binaries for headless or automation workflows

After install:

1. Launch the MMO desktop app.
2. Choose your `stems folder`.
3. Choose your `workspace`.
4. Run the workflow in order:
   `Validate -> Analyze -> Scene -> Render -> Results -> Compare`

If you want a quick confidence check before real work, open `Doctor` first.

## What The Desktop Workflow Writes

MMO keeps the main workflow artifact-first. In a normal desktop run, your
workspace will contain files like these:

- `project/validation.json`: the setup and file-structure check
- `report.json`: the main analysis report
- `report.scan.json`: the raw scan details behind the report
- `stems_map.json`: MMO's stem classification map
- `bus_plan.json`: the grouped routing draft
- `bus_plan.summary.csv`: a spreadsheet-friendly bus summary
- `scene.json`: the placement plan
- `scene_lint.json`: scene warnings and errors
- `render/`: the actual bounced audio files
- `render_manifest.json`: the list of files MMO wrote
- `safe_render_receipt.json`: what changed, what was blocked, and why
- `render_qa.json`: the post-render QA report
- `compare_report.json`: the A/B comparison report

In the desktop app, the `Results` screen also gives you quick actions for the
most important artifacts: `Receipt`, `Manifest`, and `QA`.

## What MMO Ships Today

- Packaged desktop workflow for `Validate -> Analyze -> Scene -> Render -> Results -> Compare`
- Deterministic JSON artifacts that explain each step instead of hiding it
- Mix-once/render-many delivery across stereo, surround, immersive, and
  binaural targets
- Fair-listen compare reporting with disclosed loudness compensation when
  sibling `render_qa.json` files are available
- Five channel-ordering standards at the I/O boundary:
  `SMPTE`, `FILM`, `LOGIC_PRO`, `VST3`, and `AAF`
- Offline plugin discovery plus bounded, receipt-backed recommendation flows

## Source Install And CLI

If you want to run MMO from source:

```sh
pip install .
```

Optional extras:

```sh
pip install .[pdf]
pip install .[watch]
```

Runtime expectations:

- Python `3.12+`
- `ffmpeg` and `ffprobe` for real audio workflows
- NumPy is part of the base install
- ReportLab is only needed for PDF export

Verify the source install:

```sh
mmo --help
mmo env doctor --format text
```

If FFmpeg tools are not on `PATH`, set:

- `MMO_FFMPEG_PATH=/path/to/ffmpeg`
- `MMO_FFPROBE_PATH=/path/to/ffprobe`

## Known Limits In v1

- MMO is not a DAW plugin and it does not replace your creative judgement.
- MMO does not claim to replace licensed Dolby or proprietary Atmos renderers.
- Real audio workflows depend on `ffmpeg` and `ffprobe`; if those tools are
  missing, MMO will stop and tell you instead of guessing.
- `Compare` works best when both sides come from finished MMO workspaces or
  from the matching `report.json` files inside those workspaces.
- Automated packaged smoke runs already cover Windows, macOS, and Linux in CI.
  Final human fresh-install signoff on release-candidate artifacts remains part
  of the ship checklist before a v1 tag.

## Documentation

Start here: [docs/README.md](docs/README.md)

Recommended user docs:

- [docs/manual/00-manual-overview.md](docs/manual/00-manual-overview.md)
- [docs/manual/02-install-and-verify.md](docs/manual/02-install-and-verify.md)
- [docs/manual/10-gui-walkthrough.md](docs/manual/10-gui-walkthrough.md)
- [docs/manual/13-troubleshooting.md](docs/manual/13-troubleshooting.md)
- [docs/00-quickstart.md](docs/00-quickstart.md)
- [docs/15-target-selection.md](docs/15-target-selection.md)
- [docs/18-channel-standards.md](docs/18-channel-standards.md)
- [docs/STATUS.md](docs/STATUS.md)

Plugin contributors should start here:

- [docs/04-plugin-api.md](docs/04-plugin-api.md)
- [docs/13-plugin-authoring.md](docs/13-plugin-authoring.md)
- [examples/plugin_authoring/README.md](examples/plugin_authoring/README.md)

## Repo Layout

```text
docs/       Canonical docs and user manual
ontology/   YAML source of truth for IDs, layouts, policies, and presets
schemas/    JSON schemas for reports, scenes, renders, plugins, and projects
src/        MMO engine, CLI, bundled data, and desktop sidecar bridge code
gui/        Tauri desktop frontend, web dev shell, and frontend test assets
fixtures/   Deterministic audio and contract fixtures
tests/      Cross-platform regression coverage
tools/      Validation and workflow helper scripts
```

## License

Apache-2.0. See [LICENSE](LICENSE).
