# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- No unreleased entries yet.

## [1.1.0] — 2026-02-27

### Added

- Offline plugin marketplace/discovery:
  - New bundled index `ontology/plugin_index.yaml` (mirrored to packaged data).
  - New core module `src/mmo/core/plugin_market.py` for deterministic marketplace
    listing and local index snapshot updates.
  - New CLI commands: `mmo plugin list` and `mmo plugin update`.
  - New GUI marketplace browser panel backed by GUI RPC methods
    `plugin.market.list` and `plugin.market.update`.
- Smart batch watch-folder workflow:
  - New core module `src/mmo/core/watch_folder.py` with watchdog-backed
    folder monitoring, debounce/settle behavior, and deterministic
    stem-set signature tracking.
  - New CLI command `mmo watch <folder>` that auto-runs
    `run --render-many` for new/changed stem sets.
  - GUI helper `build_watch_cli_argv()` for stable watch-command argv wiring.
- Artistic GUI Visualization Dashboard v1.1 for `mmo-gui`:
  - Real-time frequency-colored spectrum analyzer with warm glow curves.
  - Vectorscope with confidence glow and deterministic trail rendering.
  - Correlation/phase meter with explicit low/medium/high risk zones.
  - Cinematic 3D speaker layout + object placement previews with confidence badges.
  - Per-object intent cards (what/why/where/confidence) and deterministic
    surface snapshot signatures for screenshot-style regression tests.
- Headphone binaural preview renderer for `safe-render`:
  - New deterministic conservative preview plugin:
    `src/mmo/plugins/subjective/binaural_preview_v0.py`
    (5-standard aware: SMPTE, FILM, LOGIC_PRO, VST3, AAF).
  - New CLI flag: `mmo safe-render --preview-headphones`.
  - GUI action: `Preview on Headphones` button in `mmo-gui`.
  - Preview outputs include explainable metadata linking each
    `.headphones.wav` to the source render output.
- Deterministic benchmark suite:
  - New `benchmarks/suite.py` with repeatable CLI + harness timing cases.
  - New benchmark usage doc: `benchmarks/README.md`.
- Community-facing workflow docs:
  - New end-user guide `docs/user_guide.md`.
  - Docs index now links the user guide directly for onboarding.

### Changed

- README release docs now target `v1.1.0` installer artifacts and include
  v1.1 highlights (marketplace, watch mode, dashboard, benchmarks, user guide).
- Project version bumped to `1.1.0`.

## [1.0.0] — 2026-02-26

### Added

- One-click installer packaging for release artifacts:
  - Windows setup `.exe` via Inno Setup.
  - macOS `.app` bundle packaging (plus zip artifact).
  - Linux `.AppImage` packaging.
- Config/preset resolution module `src/mmo/core/config.py` with merged run-config loading
  (`preset -> config file -> CLI overrides`) and ontology-first preset resolution.
- Project session persistence contract (`schemas/project_session.schema.json`) and
  deterministic save/load commands:
  - `mmo project save <project_dir> [--session <path>] [--force]`
  - `mmo project load <project_dir> [--session <path>] [--force]`
- Minimal CustomTkinter desktop GUI (`mmo-gui`) with drag/drop stems selection,
  render target controls, live subprocess logs, and high-risk approval gating.
- Full determinism harness `tests/test_full_determinism.py` for byte-stable
  safe-render + bundle outputs on the public fixture.
- Thread-safe progress/cancel core (`src/mmo/core/progress.py`) wired through CLI
  and GUI with explainable live log fields (`what/why/where/confidence`).
- Cross-platform signing hooks in `tools/build_installers.py`:
  - Authenticode (`signtool`) for Windows.
  - `codesign` verification flow for macOS apps.
  - Optional detached GPG signing for Linux AppImage artifacts.
- GitHub Pages site under `site/` with a dedicated deployment workflow
  (`.github/workflows/pages.yml`) for a public release landing page.

### Changed

- Release workflow (`.github/workflows/release.yml`) now:
  - supports both tag-push (`v*`) and manual dispatch triggers,
  - builds CLI + GUI binaries,
  - emits platform installer artifacts, and
  - carries signing env hooks via repository secrets.
- Canonical ontology preset mirror is now available at `ontology/presets/` with
  packaged data under `src/mmo/data/ontology/presets/` for install-safe loading.
- Plugin loader default external root now prefers `HOME` when present, improving
  Windows CI behavior for fallback `~/.mmo/plugins` resolution.
- README installation docs now target v1.0 installer artifacts and include
  signature/checksum verification commands.
- Project version bumped to `1.0.0`.

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

## [2026-02-17]

### Added

- Added a repo-native status and milestones system with `docs/STATUS.md` and
  `docs/milestones.yaml`.
- Added `tools/validate_milestones.py` with deterministic output for machine validation.
- Added validator tests for happy-path and deterministic error ordering.

### Changed

- Updated `tools/validate_contracts.py` to run `DOCS.MILESTONES`.
