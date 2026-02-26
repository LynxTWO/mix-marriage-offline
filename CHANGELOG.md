# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] — 2026-02-26

### Added

- **5-standard channel layout support** (SMPTE, FILM, LOGIC_PRO, VST3, AAF) via the new
  `SpeakerLayout` module (`src/mmo/core/speaker_layout.py`).
  - SMPTE is the internal canonical standard; all import/export remaps at the boundary.
  - `remap_channels_fill()` for zero-fill remap when source is missing channels.
  - Preset `SpeakerLayout` constants for 2.0, 5.1, 7.1, 7.1.4, 9.1.6, SDDS 7.1, etc.
  - `MultichannelPlugin` + `LayoutContext` protocol in `mmo.dsp.plugins.base`.
- **Mix-once render-many** workflow (`mmo safe-render --render-many`):
  - Render to SMPTE, FILM, LOGIC_PRO, VST3, and AAF in a single pass.
  - `--layout-standard` flag on `safe-render` and `render` commands.
  - `--render-many-targets` to specify per-run target layout IDs.
  - Demo flow (`--demo`): loads the built-in 7.1.4 SMPTE+FILM fixture and dry-runs to
    all 5 standards — no audio files required.
- **Conservative subjective plugins** pack:
  - Spatial polish: width/depth/azimuth annotation and gain-trim suggestions.
  - Speaker layout-aware plugin interface (per-channel-group processing).
- **Immersive fixtures** (`fixtures/immersive/`):
  - `report.7_1_4.json` — minimal valid 7.1.4 SMPTE+FILM session fixture.
  - `fixtures/layouts/` — YAML layout descriptors for SMPTE and FILM 7.1.4 examples.
- **PDF report + recall sheet** polish:
  - Multi-standard layout tables in PDF output.
  - Render-many delivery summary section in PDF.
- **Edge-case layout IDs**: `LAYOUT.7_1_6`, `LAYOUT.9_1_6`, `LAYOUT.SDDS_7_1` added to
  the layout registry and fixture.
- `WAVEFORMATEXTENSIBLE` height channel mask bits in `mmo.dsp.channel_layout`.
- CI matrix extended: Python 3.12, 3.13, 3.14 on Linux, Windows, macOS.

### Changed

- Internal temp path in tests uses `tempfile.gettempdir()` instead of hardcoded `/tmp/`.
- `mmo.resources` resolver used everywhere for ontology/schema loading (no repo-root
  path assumptions).

## [Unreleased]

### Added

- Config/preset resolution module `src/mmo/core/config.py` with merged run-config loading
  (`preset -> config file -> CLI overrides`) and ontology-first preset resolution
  (`ontology/presets/` preferred, legacy `presets/` still supported).
- New project session persistence contract (`schemas/project_session.schema.json`) and
  deterministic save/load support for `scene + history + receipts`.
- New CLI commands:
  - `mmo project save <project_dir> [--session <path>] [--force]`
  - `mmo project load <project_dir> [--session <path>] [--force]`
- GUI RPC integration for session persistence via:
  - `project.save`
  - `project.load`
- Canonical ontology preset mirror at `ontology/presets/` (plus packaged mirror under
  `src/mmo/data/ontology/presets/`) to keep install-safe preset loading.

- Minimal viable CustomTkinter desktop GUI (`mmo-gui`, `src/mmo/gui/main.py`) with:
  drag/drop stems selection, target selector, `--render-many`, `--layout-standard`,
  live subprocess log streaming, and high-risk approval dialog before final safe-render.
- Repo launcher `gui/main.py` and packaged GUI entrypoint `src/mmo/gui/__main__.py`.
- Binary packaging support for GUI artifacts via `tools/build_binaries.py --with-gui`
  (`--gui-entrypoint`, `--gui-name`) so CLI + GUI can ship together.
- Cross-platform release binary packaging via `tools/build_binaries.py`, with
  PyInstaller as the primary backend and automatic Nuitka fallback.
- Release workflow binary matrix for `ubuntu-latest`, `windows-latest`, and
  `macos-latest`, publishing per-platform archives and checksums.
- Clarified living-doc roles: `PROJECT_WHEN_COMPLETE.md` (progress/status),
  `CHANGELOG.md` (release summary), and `GEMINI.md` (AI/operator guidance).
- Added local-only ignore rules for temp/build artifacts (`.mmo_tmp`, `mmo_tmp`,
  `.tmp_pip`, pip temp caches, `.venv_wsl`, `build`).
- Full determinism harness `tests/test_full_determinism.py` that asserts
  byte-stable safe-render + bundle artifacts for SMPTE and FILM on the new
  public fixture `fixtures/public_session/report.7_1_4.json`.

## [2026-02-17]

### Added

- Added a repo-native status and milestones system with `docs/STATUS.md` and
  `docs/milestones.yaml`.
- Added `tools/validate_milestones.py` with deterministic output for machine validation.
- Added validator tests for happy-path and deterministic error ordering.

### Changed

- Updated `tools/validate_contracts.py` to run `DOCS.MILESTONES`.
