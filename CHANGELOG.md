# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Strict BS.1770-5 loudness method registry and advanced-layout weighting:
  - Added versioned loudness method registry in `src/mmo/core/loudness_methods.py`
    with implemented `BS.1770-5` plus forward-compat placeholder IDs that fail
    with explicit `NotImplementedError`.
  - Updated truth-meter loudness entrypoints to dispatch by `method_id` instead
    of implicit hard-coded behavior.
  - Implemented BS.1770-5 Table 4 position-based `Gi` weighting from ontology
    speaker metadata, with deterministic warning receipts when positions are unknown.
  - Added `EVID.METER.LUFS_WEIGHTING_RECEIPT` for structured weighting receipts
    (method/order/mode/warnings) in scan output.
  - Extended speaker ontology metadata for immersive readiness (`SPK.TFC`,
    `SPK.TBC`, `SPK.TC`, `SPK.BC`, `SPK.FLC`, `SPK.FRC`) and added
    `LAYOUT.7_1_6` / `LAYOUT.9_1_6` rows to `ontology/speaker_positions.yaml`.
- First-class 2.1/3.x/4.x render targets across ontology, CLI, and GUI:
  - Added targets `TARGET.STEREO.2_1`, `TARGET.FRONT.3_0`,
    `TARGET.FRONT.3_1`, `TARGET.SURROUND.4_0`, and
    `TARGET.SURROUND.4_1` with deterministic token/alias resolution.
  - Added/extended layout ordering variants for
    `LAYOUT.2_1`, `LAYOUT.3_0`, `LAYOUT.3_1`, `LAYOUT.4_0`,
    `LAYOUT.4_1` across SMPTE/FILM/LOGIC_PRO/VST3/AAF (SMPTE canonical).
  - Added deterministic downmix routes for QA fold-down to stereo:
    2.1->2.0, 3.0->2.0, 3.1->2.0, 4.0->2.0, 4.1->2.0.
  - Added regression coverage for target token resolution, render-target
    registry inclusion, downmix-registry route resolution, and deterministic
    GUI target picker ordering.
- Layout-standard roundtrip contract coverage:
  - Added `docs/18-channel-standards.md` to document the five standards
    (SMPTE/FILM/LOGIC_PRO/VST3/AAF), boundary conversion, and internal SMPTE
    canonical processing.
  - Added deterministic roundtrip regression matrix
    `tests/test_layout_standard_roundtrips.py` covering all multichannel
    ontology layouts with `source -> SMPTE -> target` assertions across all
    five standards.
- Dual-LFE Phase 1 contract support:
  - Added `SPK.LFE2` speaker ontology ID and new x.2 layouts:
    `LAYOUT.5_2`, `LAYOUT.7_2`, and `LAYOUT.7_2_4`.
  - Added deterministic ordering variants for SMPTE/FILM (plus LOGIC_PRO/VST3 where applicable) on new x.2 layouts.
  - Added contract-level loudness-input mapping helper to exclude all declared LFE channels (`SPK.LFE`, `SPK.LFE2`) from program loudness inputs.
  - Tightened layout/render-target schema validation for dual-LFE identifiers and `lfe_policy` consistency.
- Dual-LFE Phase 2 analysis, QA, and fold-down support:
  - Generalized loudness/meter handling to exclude any `SPK.LFE*` speaker from program loudness calculations.
  - Expanded LFE audit output to include per-LFE rows (band energy, out-of-band detection, true-peak) and summed LFE energy metrics.
  - Extended downmix registries/policy packs with x.2 stereo fold-down conversions and an explicit dual-LFE safe split strategy (preserving single-LFE `-10 dB` combined contribution).
  - Implemented deterministic downmix `source_pre_filters` execution (`lowpass`/`highpass`, slope-aware), applied pre-matrix on declared source channels only.
  - Updated downmix QA/receipts to reflect filtered fold-down paths and report applied source pre-filters.
  - Added regression tests for multi-LFE loudness exclusion, per-channel LFE audit rows, source pre-filter behavior, and deterministic output tolerance.
- Dual-LFE Phase 3 export-contract and documentation completion:
  - Render-report jobs now include canonical contract fields (`target_layout_id`, `channel_count`, `channel_order`, `ffmpeg_channel_layout`) sourced from resolved layout contracts.
  - Dual-LFE WAV jobs emit explicit warnings for `WAVEFORMATEXTENSIBLE` single-LFE-mask limits and include deterministic validation instructions.
  - Recall-sheet export now carries render channel-order and export-warning context columns for x.2 traceability.
  - FFmpeg transcoding now forwards explicit channel layout strings (including `LFE2` when supported) for layout-preserving non-WAV exports.
  - Added deterministic dual-LFE render fixtures for `5.2`, `7.2`, and `7.2.4`, plus regression tests covering channel order/count contracts and WAV warning behavior.
- Artistic headphone preview UX polish in `mmo-gui`:
  - Added a dedicated `Preview on Headphones` control in the Audition panel.
  - Added deterministic pulsing waveform visualization and warm analog L/R metering
    driven by live audio analyser data.
  - Added deterministic screenshot assets:
    `docs/screenshots/preview_headphones_desktop.svg` and
    `docs/screenshots/preview_headphones_mobile.svg`.
- Binaural preview renderer refinement:
  - Added conservative HRTF far-ear shading control (`hrtf_amount`) while preserving
    existing RMS gate behavior and deterministic output.
  - Improved five-standard layout awareness with explicit standard fallback candidates
    (including AAF -> FILM/SMPTE fallback) and preview metadata trace fields.
- First-class binaural render target:
  - Added ontology entries for `SPK.HL`/`SPK.HR`, `LAYOUT.BINAURAL`, and
    `TARGET.HEADPHONES.BINAURAL`.
  - `safe-render`, `render-many`, and variants now accept binaural via
    shorthand/`LAYOUT.*`/`TARGET.*` tokens.
  - Binaural output uses deterministic conservative virtualization from an
    auto-selected source layout (7.1.4 -> 5.1 -> stereo) and records the
    source-layout explainability notes in contracts/receipts.
- Watch-folder cinematic queue telemetry:
  - Added deterministic watch-batch queue snapshots in `src/mmo/core/watch_folder.py`
    with explicit pending/running/succeeded/failed states.
  - Added ASCII cinematic queue rendering for live operator visibility.
  - Added CLI flags `mmo watch --visual-queue --cinematic-progress`.
  - Added GUI watch-argv support for visual queue flags via `build_watch_cli_argv()`.
- Artistic offline plugin hub:
  - Added deterministic plugin marketplace install flow (`plugin install`,
    `plugin.market.install`) that copies bundled offline plugin assets into
    a chosen plugin root.
  - Added a new `Discover` tab in `mmo-gui` with styled preview cards and
    one-click install actions.
  - Extended `ontology/plugin_index.yaml` with preview metadata and
    install asset root contract for bundled offline installs.
- Digital-first plugin quality mandates:
  - Extended `schemas/plugin.schema.json` with `capabilities.dsp_traits`
    and `measurable_claims` truth-contract shape.
  - Tightened `tools/validate_plugins.py` to require renderer seed-policy +
    DSP trait declarations and nonlinear anti-aliasing strategies.
  - Updated renderer/plugin-market manifests and authoring docs to document
    measurable claim contracts and gate-respecting DSP expectations.
- Best-effort metadata round-trip with receipts:
  - Added export-side tag application policy (`src/mmo/core/tag_export.py`)
    for deterministic ffmpeg metadata args and embedded/skipped key tracking.
  - Render/transcode paths now clear inherited metadata and apply explicit
    deterministic `-metadata` entries per container policy (FLAC/WV arbitrary
    fields; WAV conservative INFO subset).
  - `render_report` output files now include strict `metadata_receipt`
    sections, and deliverables index file rows preserve receipts when present.
  - Added FLAC/WV custom-tag fixtures + tests for TagBag preservation and
    export receipts, plus WAV subset/skipped receipt coverage.

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
