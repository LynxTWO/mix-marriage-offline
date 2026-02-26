# Mix Marriage Offline (MMO)

[![CI](https://github.com/danielboyd/mix-marriage-offline/actions/workflows/ci.yml/badge.svg)](https://github.com/danielboyd/mix-marriage-offline/actions/workflows/ci.yml)
[![Policy Validation](https://github.com/danielboyd/mix-marriage-offline/actions/workflows/policy-validation.yml/badge.svg)](https://github.com/danielboyd/mix-marriage-offline/actions/workflows/policy-validation.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

An open-source, offline mixing assistant that handles the technical math so humans can focus on vibe, intent, and performance.

MMO is a standalone tool that analyzes exported stems in a folder and produces:

- A ranked list of technical issues with evidence
- DAW-agnostic recommendations (a recall sheet you can apply anywhere)
- Translation checks (stereo, mono, phone, earbuds, car-like curves)
- Optional conservative rendered stem variants (explicit invoke only)
- A modular plugin system so strategies can evolve without breaking the core

This is not a DAW plugin. This is not "AI that mixes your song for you."
It is a technical co-pilot that keeps the engineering side honest, so the human can stay artistic.

---

## Why this exists

Mixing is two jobs wearing one hat:

- Objective engineering: gain staging, loudness safety, masking, resonances, dynamics, translation
- Subjective art: mood, texture, space, hierarchy, energy, emotional story

When one person must do both, something gets compromised. Usually it is the technical details or the creative intent. Sometimes both.

MMO's promise:

- The machine handles the technical chores relentlessly
- The human decides what the music means

## Install

Prebuilt binaries (no Python required):

- Download the matching release asset from GitHub Releases:
  - Windows: `mmo-windows-<arch>.zip`
  - Linux: `mmo-linux-<arch>.tar.gz`
  - macOS: `mmo-macos-<arch>.tar.gz`
- Extract the archive and run the binary:

```powershell
# Windows (PowerShell)
Expand-Archive .\mmo-windows-x86_64.zip -DestinationPath .
.\mmo-windows-x86_64.exe --help
```

```sh
# Linux/macOS
tar -xzf mmo-linux-x86_64.tar.gz
./mmo-linux-x86_64 --help
```

Python install (repo/dev):

```sh
pip install .
```

Optional extras:

```sh
pip install .[pdf]
pip install .[truth]
```

---

## Supported formats

- WAV (.wav/.wave) is always supported.
- FLAC (.flac) and WavPack (.wv) are supported when ffprobe/FFmpeg is available (or MMO_FFPROBE_PATH is set).
- AIFF (.aif/.aiff) is not supported yet; export WAV for now.
- Lossy formats (MP3/AAC/Ogg/Opus) will trigger warnings; re-export lossless for reliable analysis.

---

## CLI Cookbook

### Analyze stems (stereo or surround)

```sh
# Analyze a stem folder and write a report
mmo analyze ./stems --out-report out/report.json

# Analyze with peak metering
mmo scan ./stems --meters peak --out-report out/report.json

# Analyze with truth metering (requires pip install .[truth])
mmo scan ./stems --meters truth --out-report out/report.json
```

### Export reports

```sh
# Export PDF recall sheet (requires pip install .[pdf])
mmo export --report out/report.json --pdf out/report.pdf

# Export CSV issues list
mmo export --report out/report.json --csv out/issues.csv

# Export both
mmo report --report out/report.json --pdf out/report.pdf --csv out/recall.csv
```

### Layout standards: SMPTE, FILM, Logic Pro, VST3, AAF

MMO supports five channel-ordering standards for import and export.
The internal canonical standard is always **SMPTE**.

| Standard    | Used by                                        |
|-------------|------------------------------------------------|
| `SMPTE`     | Netflix, broadcast, DCP, FFmpeg, WAV/FLAC/BWF  |
| `FILM`      | Pro Tools, Dolby cinema legacy                 |
| `LOGIC_PRO` | Logic Pro (Apple), DTS                         |
| `VST3`      | Cubase, Nuendo 7.1+                            |
| `AAF`       | Metadata-driven interchange                    |

```sh
# Render with SMPTE output order (default)
mmo safe-render --report out/report.json --layout-standard SMPTE --out-dir out/smpte/

# Render with Pro Tools / FILM output order
mmo safe-render --report out/report.json --layout-standard FILM --out-dir out/film/

# Render with Logic Pro output order
mmo safe-render --report out/report.json --layout-standard LOGIC_PRO --out-dir out/logic/

# Render with VST3 / Cubase output order
mmo safe-render --report out/report.json --layout-standard VST3 --out-dir out/vst3/
```

### Mix-once, render-many: deliver to SMPTE / FILM / Logic Pro in one pass

```sh
# Full safe-render to all 5 channel standards from a single source report
mmo safe-render \
  --report out/report.json \
  --render-many \
  --render-many-targets stereo,5.1,7.1.4 \
  --out-dir out/deliverables/

# Demo flow: load the built-in 7.1.4 fixture and dry-run to all 5 standards
mmo safe-render --demo --out-dir out/demo/

# Public example session fixture (7.1.4 SMPTE + FILM), dry-run render
mmo safe-render \
  --report fixtures/public_session/report.7_1_4.json \
  --target 7.1.4 \
  --layout-standard FILM \
  --dry-run \
  --receipt-out out/public_session/receipt.json \
  --out-manifest out/public_session/render_manifest.json

# One-shot: analyze + render-many in a single workflow pass
mmo run ./stems \
  --render-many \
  --targets TARGET.STEREO.2_0 \
  --translation \
  --out-dir out/run/
```

The render-many workflow:

1. Analyzes the source session once
2. Plans renders to every requested layout + standard
3. Writes per-standard deliverable directories
4. Runs translation QA (stereo, mono, phone) when a `TARGET.STEREO.2_0` deliverable exists

### Downmix matrix

```sh
# Show the downmix matrix for 5.1 → stereo
mmo downmix show --source LAYOUT.5_1 --target LAYOUT.2_0 --format csv

# List all available layouts, policies, and conversions
mmo downmix list
mmo downmix list --policies

# QA a rendered downmix against a stereo reference
mmo downmix qa --src 5.1.flac --ref ref_stereo.flac \
  --source-layout LAYOUT.5_1 --format json

# QA then export PDF
mmo downmix qa --src 5.1.flac --ref ref_stereo.flac \
  --source-layout LAYOUT.5_1 --meters truth --emit-report qa_report.json
mmo export --report qa_report.json --pdf qa_report.pdf
```

### Plugins and ontology

```sh
# List available plugins
mmo plugins list

# Browse ontology: roles, targets, issues
mmo roles list
mmo targets list
mmo ontology integrity

# Inspect a translation profile
mmo translation show TRANS.MONO.COLLAPSE
```

---

## Mix-once, render-many: channel layout workflow

MMO uses SMPTE order internally for all processing.
Stems are remapped from the source standard on import and back to the target standard on export.

```text
Source stems  →  [remap in]  →  SMPTE (internal)  →  [remap out]  →  SMPTE / FILM / LOGIC_PRO / VST3 / AAF
```

This means you mix once and MMO handles channel reordering for every downstream standard.

**7.1.4 channel order by standard:**

| Slot  | SMPTE           | FILM            | LOGIC_PRO       | VST3            |
|-------|-----------------|-----------------|-----------------|-----------------|
| 1     | L               | L               | L               | L               |
| 2     | R               | C               | C               | R               |
| 3     | C               | R               | R               | C               |
| 4     | LFE             | Ls              | Ls              | LFE             |
| 5     | Ls              | Rs              | Rs              | Ls              |
| 6     | Rs              | Lrs             | Lrs             | Rs              |
| 7     | Lrs             | Rrs             | Rrs             | Lrs             |
| 8     | Rrs             | LFE             | LFE             | Rrs             |
| 9–12  | TFL TFR TRL TRR | TFL TFR TRL TRR | TFL TFR TRL TRR | TFL TFR TRL TRR |

See [docs/07-export-guides.md](docs/07-export-guides.md) for per-DAW export recipes.

---

## Documentation

Start here: [docs/README.md](docs/README.md)

Key reads:

- Product vision: [docs/09-product-vision.md](docs/09-product-vision.md)
- Authority modes: [docs/10-authority-profiles.md](docs/10-authority-profiles.md)
- GUI vision: [docs/11-gui-vision.md](docs/11-gui-vision.md)
- GUI dev shell: [docs/12-gui-dev.md](docs/12-gui-dev.md)
- Export guides: [docs/07-export-guides.md](docs/07-export-guides.md)

---

## Core ideas

### Objective core vs subjective plugins

MMO keeps two worlds separate on purpose:

#### Objective Core (truth layer)

- metering, validation, translation checks, safety gates, strict schemas
- deterministic and heavily tested

#### Subjective Plugins (strategy layer)

- detectors, resolvers, renderers, profiles
- fast-evolving and swappable

### Ontology-first

Open source projects fall apart when contributors cannot agree on terms. MMO uses a shared vocabulary defined in YAML:

- roles, features, issues, actions, parameters, units, evidence fields

Internal variable names can vary, but anything leaving a plugin uses canonical IDs.

### Bounded authority

The tool can recommend anything, but it only auto-applies low-risk actions within user limits. High-impact moves require explicit approval.

---

## Workflow

1. Export stems from any DAW using simple rules:
   - all stems start at 0:00
   - same sample rate and bit depth
   - consistent length
   - consistent naming roles (or assign roles in-app)
2. Point MMO at the folder
3. MMO validates, measures, detects issues, proposes actions, applies safety gates
4. MMO exports:
   - report (PDF + JSON)
   - recall sheet (CSV/TXT)
   - optional rendered stem variants

Optional conservative render (explicit invoke):

```sh
mmo safe-render --report out/report.json --out-dir out/rendered/ --dry-run
```

---

## Surround and immersive audio

MMO v0.2 includes full multi-standard support for immersive layouts (5.1, 7.1, 7.1.4, 9.1.6, etc.) via the `SpeakerLayout` module:

- channel layout awareness (2.0, 5.1, 7.1, 7.1.4, Dolby Atmos beds, etc.)
- channel-group measurement (front stage, surrounds, heights, LFE)
- downmix translation checks (surround to stereo/mono)
- common immersive risk detection
- five channel-ordering standards: SMPTE, FILM, LOGIC_PRO, VST3, AAF

Note: Dolby Atmos involves licensing and proprietary tooling. MMO will focus on open, practical workflows and translation QA without claiming to replace official renderers.

---

## Repo layout

```text
docs/       Project docs (proposal, philosophy, architecture, roadmap)
ontology/   YAML source of truth (roles, features, issues, actions, policies)
schemas/    JSON schemas for project/report/plugin I/O
src/        Core engine and CLI
plugins/    Community detectors/resolvers/renderers
fixtures/   Test sessions for regression testing
tests/      Automated tests
```

---

## Status

v0.2 — Active development.

What works now:

- Full analysis pipeline (scan, issue detection, recommendations, export)
- PDF + JSON reports, CSV recall sheets
- Downmix matrix computation and QA
- Multi-standard channel layout: SMPTE, FILM, LOGIC_PRO, VST3, AAF
- `SpeakerLayout` module with 5-standard remap and zero-fill
- `safe-render` with bounded authority gates
- Mix-once render-many: render to N standards in one pass
- Conservative subjective plugins (gain trim, translation checks)
- Deterministic pipeline, strict schemas, full CI matrix (Linux/Windows/macOS)

---

## Contributing

Contributions we expect to need (soon):

- ontology additions and cleanup (IDs, definitions, policies)
- fixture sessions and regression tests
- detectors and resolvers (as plugins)
- documentation, especially export guides for common DAWs

When the contributor docs land, start with:

- `CONTRIBUTING.md`
- `docs/04-plugin-api.md`
- `docs/05-fixtures-and-ci.md`

---

## License

Apache-2.0. See `LICENSE`.
