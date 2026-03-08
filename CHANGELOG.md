# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.3] — 2026-03-02

### Fixed

- **Windows packaged GUI `-m mmo` regression (critical hotfix):**
  GUI passthrough now maps `-m mmo` to `mmo.__main__` for module execution while
  preserving `sys.argv[0]` as `mmo`, so frozen builds execute the CLI entrypoint
  correctly.
  (`src/mmo/gui/main.py`)
- **Frozen GUI module inclusion for passthrough:** PyInstaller GUI builds now add
  explicit hidden imports for `mmo.__main__` and `mmo.cli` so
  `mmo-gui.exe -m mmo ...` and nested CLI execution paths are available in the
  bundled binary.
  (`tools/build_binaries.py`)
- **Release CI regression lock:** Windows release workflow now smoke-tests:
  `mmo-gui.exe -m mmo --help` and
  `mmo-gui.exe -m mmo.tools.analyze_stems --help`.
  (`.github/workflows/release.yml`)
- **Passthrough mapping unit coverage:** added helper-level test coverage for
  `mmo -> mmo.__main__` mapping without executing module help output.
  (`tests/test_gui_smoke.py`)

## [1.1.2] — 2026-03-02 (broken on Windows packaged GUI)

### Fixed

- **Packaged GUI `-m mmo*` passthrough (critical hotfix):**
  `mmo-gui` now dispatches any `-m mmo...` module via `runpy` (not only `-m mmo`),
  so nested frozen subprocess calls like
  `sys.executable -m mmo.tools.analyze_stems ...` and
  `sys.executable -m mmo.tools.scan_session ...` execute correctly.
  (`src/mmo/gui/main.py` — `_try_cli_passthrough`)
- **Passthrough regression coverage:** added GUI passthrough tests for
  `mmo`, `mmo.tools.analyze_stems`, `mmo.tools.scan_session`, and
  `mmo.tools.export_report` with `--help` dispatch paths.
  (`tests/test_gui_smoke.py`)
- **PyInstaller module collection:** binary builds now explicitly collect
  `mmo.tools` submodules so packaged GUI passthrough supports current and
  future `mmo.tools.*` invocations.
  (`tools/build_binaries.py`)

### Changed

- **Release status:** `1.1.1` is marked as a broken release for packaged GUI nested
  tool subprocesses (`-m mmo.tools.*`) and is superseded by `1.1.2`.
- **Release status update:** `1.1.2` is now marked as broken for Windows packaged GUI
  `-m mmo` execution due to missing `mmo.__main__` in frozen bundles and is
  superseded by `1.1.3`.

## [1.1.1] — 2026-03-01 (broken)

### Fixed

- **Windows GUI passthrough (critical):** The packaged GUI executable now dispatches
  `sys.executable -m mmo <subcommand>` to the real CLI entrypoint before any argparse
  processing, so frozen builds no longer abort with `unrecognized arguments: -m mmo ...`.
  (`src/mmo/gui/main.py` — `_try_cli_passthrough`)
- **Windows default plugins directory:** `default_user_plugins_dir()` on Windows now
  resolves to `%LOCALAPPDATA%\mmo\plugins` (with `APPDATA` / `USERPROFILE` fallbacks)
  instead of incorrectly falling back to `C:\Windows\System32\plugins` in frozen builds.
  (`src/mmo/core/plugin_loader.py`)
- **macOS / Linux plugin directories:** macOS resolves to
  `~/Library/Application Support/mmo/plugins`; Linux honours `$XDG_DATA_HOME/mmo/plugins`
  with fallback to `~/.local/share/mmo/plugins`.

### Changed

- **GUI live-log error codes:** `_run_command` now emits structured anchor lines:
  `[GUI.E2001] spawn_failed` on subprocess launch failure,
  `[GUI.E2000] stage_failed` on nonzero exit (with stage name and return code),
  `[GUI.E2000] first_error_line` with the first meaningful error line from output,
  `[GUI.STAGE] <stage> starting.` and `[GUI.STAGE] <stage> completed ok.` for orientation.
- **Docs — Chapter 13 (Troubleshooting):** Documents GUI error codes, the Windows
  `-m mmo` broken-build note, and the corrected Windows default plugin folder path.
- **Docs — Chapter 11 (Plugins):** Lists platform-specific default plugin directories.

## [Unreleased]

### Added

- Lock-precedence single source of truth + regression matrix:
  - Added `src/mmo/core/precedence.py` as the shared lock/explicit/suggested/
    inferred merge path with canonical receipt sources
    `locked | explicit | suggested | inferred`, plus
    `original_value` / `applied_value` / `lock_id` receipt fields.
  - `scene build`, `safe-render`, placement-policy receipt propagation, and
    renderer entrypoints now re-apply precedence so locks win across templated
    scene suggestions, explicit scene payloads, resolver/plugin eligibility
    checks, and final placement rendering.
  - Added `tests/test_lock_precedence_matrix.py` to pin locked role, bus,
    azimuth, bed-cap, and scene-perspective cases end-to-end through render
    manifests and recommendation gating.

- 32-channel render regression contract:
  - Added `LAYOUT.32CH` plus generic `SPK.CH01..SPK.CH32` ontology entries so
    MMO can resolve a deterministic 32-channel placeholder layout through the
    packaged data path.
  - Placement policy/rendering now falls back to a deterministic front-safe
    pair when a high-channel-count layout has no semantic `SPK.L`/`SPK.R`
    speakers, allowing end-to-end `LAYOUT.32CH` export without inventing a
    fake speaker standard.
  - Added `tests/test_32ch_end_to_end.py` as a byte-stable regression tripwire
    that renders a 32-channel WAV, asserts `nchannels == 32`, checks manifest
    `channel_order` length `32`, and pins SHA-256 stability across two runs.

- Deterministic export finalization policy for renderer WAV outputs:
  - Added `mmo.dsp.export_finalize` as the shared float64 -> PCM finalization
    path for renderer WAV writing, with centralized PCM bit-depth handling,
    deterministic seeded TPDF / high-pass TPDF dither support, and explicit
    no-dither defaults for 24-bit exports.
  - Gain-trim, baseline mixdown, and placement mixdown renderer manifests now
    disclose `export_finalization_receipt` metadata (`bit_depth`,
    `dither_policy`, seed-derivation inputs, clamp behavior, and
    `target_peak_dbfs` when applicable).
  - `render_report.stage_evidence[*].evidence` now carries the planned/exported
    finalization receipt for the `export_finalize` stage so bit depth and
    dither policy are disclosed in the deterministic report contract.

- Deterministic `render_report` stage reporting:
  - Added optional top-level `stage_metrics` and `stage_evidence` sections to
    `render_report` with stable `(job_id, stage_id, where)` ordering, covering
    `planning`, `resampling`, `dsp_hooks`, `export_finalize`, and `qa_gates`.
  - Extended the render-report builders so plan-derived reports emit
    deterministic stage placeholders while the runtime render engine now
    threads DSP dispatch/hook evidence and stage-like metrics into the final
    report payload.
  - Added opt-in `wall_clock` report support with an explicit non-deterministic
    disclaimer; default report generation remains wall-clock free so golden
    determinism tests stay byte-stable.

- Typed `AudioBufferF64` transport for renderer/plugin-chain audio boundaries:
  baseline mixdown, placement mixdown, and gain-trim renderer chunk handling
  now use explicit interleaved buffer metadata (`channel_order`,
  `channel_count`, `sample_rate_hz`) instead of ad hoc raw-list math, and the
  stereo plugin-chain runner now centralizes deterministic typed-buffer
  conversion at the plugin boundary.

- DSP `ProcessContext` routing contract:
  - Added `src/mmo/dsp/process_context.py` as the ontology-backed DSP truth
    object (`layout_id`, `layout_standard`, `channel_order`, `sample_rate_hz`,
    `seed`) with semantic speaker/group lookup helpers.
  - Refactored `src/mmo/core/dsp_dispatch.py` to build per-stem processing
    context from layout metadata instead of a hard-coded preset layout map,
    and to emit `StemResult.channel_order` alongside derived LFE/height
    indices.
  - Extended plugin contracts so DSP stages can receive `process_ctx` while
    preserving `LayoutContext` compatibility for existing multichannel plugins.
  - Removed fallback renderer layout-order maps in the baseline and placement
    mixdown renderers so target channel routing now resolves through ontology
    channel order consistently, including 9.1.6.

- Tauri desktop design-system + ergonomics CI:
  - Reworked `gui/desktop-tauri` into explicit `Dashboard` / `Presets` /
    `Run` / `Compare` screens with machine-readable widget ids, ontology-driven
    theme tokens, and the required control family:
    knob, slider, toggle, segmented selector, XY pad, preset browser, A/B
    toggle, and value readout.
  - Added direct numeric entry for drag controls, visible units on numeric
    widgets, fine-adjust modifier feedback, and a global GUI scale control with
    `90% / 100% / 115%` presets.
  - Added authored Tauri layout manifests under `gui/desktop-tauri/layouts/`
    plus `tools/validate_tauri_design_system.py`, which validates ontology/CSS
    token parity and fails CI on layout overlaps, off-screen widgets, missing
    numeric units/direct-entry metadata, or spacing below the declared design
    tokens.
  - Added Playwright desktop UI tests for breakpoint visibility, overlap
    tripwires, units visibility, direct numeric entry, fine-adjust behavior,
    and global scale switching, and wired browser installation into the desktop
    CI job.

- Web GUI dashboard meter bridge + Canvas2D stage/audition visualizers:
  - Added a Canvas2D meter bridge in `gui/web` that extracts peak, RMS,
    true-peak, and LUFS rows from scan reports and render QA artifacts, with
    a compact LUFS spread view and scene-distribution summary.
  - Replaced the web scene preview SVG with a Canvas2D stage view that shows
    objects vs. bed energy, confidence-weighted object labels, selected layout
    speakers, and audience/on-stage/band/orchestra perspective changes.
  - Added audition waveform and spectrum overlays for selected input/output
    pointers, preferring `render_qa.json` spectral data and falling back to
    bounded local audio decode for waveform extraction when possible.
  - Added GUI regression coverage for the new dashboard/audition helper
    modules in `gui/tests/dashboard_visuals.test.mjs` and
    `gui/tests/audition_overlays.test.mjs`.

- GUI parity checklist + CI contract:
  - Added `docs/gui_parity.md` as the canonical Tauri parity checklist for the
    required `validate -> analyze -> scene -> render -> results -> compare`
    workflow plus scene-lock editing and loudness-compensated A/B compare.
  - Added `tools/validate_gui_parity.py` plus regression tests and umbrella
    contract integration so CI fails when the parity doc is missing required
    links, screens, or behaviors.
  - Declared Tauri as the primary GUI plan and CustomTkinter as the single
    fallback until parity; the fallback is deprecated after parity lands.

- Tauri desktop scaffold + CI release binaries:
  - Added `gui/desktop-tauri/` via `create-tauri-app` using the Vite
    `vanilla-ts` template, then rebranded the starter shell as `MMO Desktop`.
  - Added a GitHub Actions matrix job that installs Tauri prerequisites, runs
    desktop frontend lint/tests when present, and builds a release binary on
    Linux, macOS, and Windows.
  - CI now uploads one desktop binary artifact per OS from
    `gui/desktop-tauri/src-tauri/target/release/`.

- Tauri MMO sidecar packaging + Doctor screen:
  - Added a Tauri sidecar preparation flow that freezes the `mmo` CLI with
    bundled `mmo.data` using the existing Python binary builder, then stages
    the result under `gui/desktop-tauri/src-tauri/binaries/` using the exact
    Rust target triple that Tauri expects for `bundle.externalBin`.
  - Wired `tauri.conf.json`, Rust plugin initialization, capabilities, and the
    desktop package scripts so `tauri dev` / `tauri build` can execute the
    packaged `mmo` sidecar through `@tauri-apps/plugin-shell`.
  - Replaced the scaffold handshake UI with a Doctor screen that runs
    `mmo --version`, `mmo plugins validate --bundled-only`, and
    `mmo env doctor --format json`, then displays the bundled plugins path and
    resolved runtime data/cache/temp paths reported by the sidecar itself.
  - Added `mmo --version` plus a deterministic `mmo plugins validate`
    contract so packaged desktop flows can verify bundled plugin manifests and
    entrypoints without relying on external Python installs.
  - Replaced the doctor-only desktop surface with a direct sidecar workflow
    screen that prepares a project scaffold, validates project artifacts,
    analyzes stems into a user-chosen workspace folder, and runs
    `safe-render --live-progress` while streaming stdout/stderr into a Tauri
    timeline.
  - Added a small TypeScript sidecar wrapper that centralizes
    `Command.sidecar(...)` `execute()`/`spawn()` calls, line-buffered log
    streaming, and deterministic workspace artifact path construction for the
    desktop app.
  - Expanded the Tauri shell capability contract so the desktop app explicitly
    allowlists both `shell:allow-execute` and `shell:allow-spawn` for the MMO
    sidecar.

### Fixed

- Placement scene safe-render regressions:
  - `scene build --templates` now preserves template-authored fields outside
    the precedence-merged subset (for example `loudness_bias`) and applies
    locks on top of the fully templated scene instead of discarding
    non-precedence template data.
  - Placement subbus export now threads the renderer `session` through the
    subbus helper so explicit-scene `safe-render --export-buses` no longer
    raises a `NameError`.

### Added

- Ontology additive-change enforcement:
  - Added `tools/validate_ontology_changes.py` to diff ontology IDs against
    `main` and fail on removals without required guards.
  - Added migration-note scaffolding under `docs/ontology_migrations/`
    (`README.md` + `TEMPLATE.md`).
  - Wired ontology-change validation into umbrella contracts validation and CI
    (`tools/validate_contracts.py`, `.github/workflows/ci.yml`).

- Immersive golden-path small fixture + hash tripwire:
  - Added `fixtures/golden_path_small/` with deterministic generated stems
    (`kick`, `snare`, `bass_di`, `pad_stereo_wide`, `sfx_stereo`) plus
    expected per-layout WAV hash snapshots for
    `LAYOUT.2_0/5_1/7_1/7_1_4/9_1_6`.
  - Added `tests/test_cli_immersive_golden_path_small.py` to enforce
    `stems classify -> stems bus-plan -> scene build -> scene template apply
    (audience) -> safe-render --render-many` determinism, channel-count
    contracts, and rendered downmix-similarity pass/backoff assertions when
    optional truth-meter dependencies are installed.

- Scene-aware safe-render debug artifact exports:
  - Added `safe-render` flags `--export-stems`, `--export-buses`,
    `--export-master/--no-export-master` (default export on), and
    `--export-layouts <csv>`.
  - Placement render now writes optional stem-copy artifacts, optional
    Drums/Bass/Music/Vox/FX subbus WAVs, and optional master WAVs with
    deterministic SHA-256s in render manifest + safe-render receipt.
  - Recall sheet CSV now includes `stem_subbus_main_scene_map`
    (`stem -> subbus -> BUS.MAIN -> object/bed`) derived from render intent +
    scene context.
- Optional deterministic immersive bed decorrelation plugin:
  - Added renderer option `render_export_options.decorrelated_bed_widening`
    for seeded decorrelated widening on qualifying bed stems
    (`BED.*` + content hints + confidence threshold).
  - Added hard QA gate integration against rendered stereo reference:
    run rendered surround similarity gate, apply bounded backoff retry, and
    auto-disable/rerender without the plugin when gate failure persists.
  - Added placement renderer regression coverage for confidence gating,
    deterministic output stability, and QA-triggered auto-disable behavior.

- Scene QA lint command for pre-render validation:
  - Added `mmo scene lint --scene <scene.json> [--scene-locks <scene_locks.yaml|json>] [--out <report.json>]`.
  - Lint checks now cover missing stem references, duplicate object/bus references,
    azimuth/width/depth range issues, lock conflicts against role/bus/layout
    assumptions, low-confidence critical anchors (warn), and immersive
    perspective without bed/ambient candidates (warn).
  - Lint now also checks missing stem IDs/files, conflicting per-stem bus locks,
    immersive perspective with no template evidence (warn), and immersive
    low-confidence perspective intent (warn).
  - `safe-render` now runs scene lint automatically for explicit `--scene`
    preflight inputs and `--scene-strict` fails fast when lint reports errors.
  - Added deterministic report generation + stable issue ordering with CLI
    exit code `2` on lint errors and `0` for warnings-only results.
  - Added CLI regression coverage for deterministic lint payload output and
    warnings-only non-failing behavior.

- GUI scene lock editing workflow (dev shell v1):
  - Added scene lock editor controls in web GUI: object list with confidence,
    per-stem role override, front-only toggle, surround cap slider, height cap
    slider, and scene perspective selector.
  - Added GUI RPC methods `scene.locks.inspect` and `scene.locks.save` to load
    and persist `scene_locks.yaml`, then apply overrides to
    `drafts/scene.draft.json` for immediate re-render.
  - Added GUI RPC regression coverage for inspect/save round-trips and lock
    field preservation.

- Desktop GUI Scene Preview v1 (read-only):
  - Desktop GUI post-analyze flow now runs deterministic `scene build` + `scene lint`
    from `_mmo_gui/stems_map.json` + `_mmo_gui/bus_plan.json` and writes
    `_mmo_gui/scene.json` + `_mmo_gui/scene_lint.json`.
  - Added a read-only `Scene` tab that surfaces scene perspective, object
    azimuth/width/depth/confidence rows, bed-bus listing (with content hints),
    and warning-level scene-lint issues for explainable object-vs-bed intent review.
  - Added GUI smoke coverage for scene CLI argv wiring and deterministic
    scene-summary rendering.

### Fixed

- GUI `-m mmo*` passthrough no longer executes modules via `runpy`:
  - Passthrough now imports target modules and calls callable `main()` entrypoints
    directly, preserving prior exit-code behavior while avoiding
    `RuntimeWarning: '<module>' found in sys.modules ...` noise in smoke/CI logs.
  - Added GUI smoke regression coverage that preloads a tool module and asserts
    passthrough help dispatch emits no `runpy` warning text.
  - (`src/mmo/gui/main.py`, `tests/test_gui_smoke.py`)

- `safe-render` now supports first-class explicit scene inputs:
  - Added `--scene <scene.json>`, `--scene-locks <scene_locks.yaml|json>`,
    and `--scene-strict`.
  - Explicit scene input now takes precedence over implicit scene rebuilds.
  - When scene locks are provided, lock overrides are applied before placement
    policy evaluation.
  - Safe-render receipts now record scene mode (`explicit` vs `auto_built`),
    scene source path, and scene-locks source path.

- Safe-render zero-output contract is now explicit and fail-safe:
  - Added `ISSUE.RENDER.NO_OUTPUTS` emission when full safe-render renderer
    stage writes zero outputs.
  - Full safe-render now exits non-zero by default on `outputs=0`, with
    explicit override via `--allow-empty-outputs`.
  - Desktop GUI now surfaces a persistent warning banner with receipt-path
    link behavior whenever final safe-render returns non-zero or emits
    `ISSUE.RENDER.NO_OUTPUTS`.
  - Added regression coverage for stub-only renderer runs to assert
    non-zero exit and receipt issue presence.

- Scene build locks now preserve full per-stem `bus_id` identity in scene
  objects/receipts (for example `BUS.DRUMS.KICK`) while still deriving
  deterministic `group_bus` for routing safety.
  - Updated lock application to persist locked `bus_id` with precedence
    `locks > explicit metadata > inference`.
  - Extended scene schema (root + packaged mirror) to allow optional
    object/receipt `bus_id`.
  - Added regression assertions in lock + CLI scene lock tests for
    `ROLE.DRUM.KICK` + `BUS.DRUMS.KICK` overrides.

- Placement scene/render stereo imaging is now preserved end-to-end:
  - Added deterministic stereo feature extraction (`src/mmo/core/stem_features.py`)
    using L/R correlation + side/mid ratio for `width_hint` and ILD-window
    analysis for `azimuth_hint`.
  - `build_scene_from_session()` now infers stereo hints from actual stereo WAV
    stems when confidence is high enough, writes `object.width_hint` and
    `object.azimuth_hint`, and stores metric/value evidence in
    `metadata.stereo_hints` (with schema updates in both scene schema mirrors).
  - `placement_mixdown_renderer` no longer folds every stem to mono:
    `LAYOUT.2_0` now sums stereo stems channel-wise, while multichannel layouts
    use deterministic mid/side routing that keeps stereo side energy in L/R.
  - Side wrap remains conservative: by default there is no surround leakage for
    anchor-like objects; optional tiny wide-channel wrap only engages when
    immersive perspective (`in_band`/`in_orchestra`) and high confidence are present.
  - Added regression coverage for scene hint evidence + confidence gating and
    stereo render energy-ratio preservation / wrap behavior.
  - Placement renderer mixdown now uses deterministic two-pass streaming
    (`chunk_frames=4096`): pass 1 scans mixed chunk peaks, pass 2 writes
    trimmed PCM24 directly to the wave writer, avoiding full-program
    in-memory accumulation on long sessions.
  - Placement and baseline mixdown renderers now share a lossless
    multiformat decode abstraction (`wav`, `flac`, `wv`, `aiff`/`aif`,
    `ape`) and no longer skip stems solely for sample-rate mismatches.
- Added deterministic sample-rate policy + SRC receipts:
    explicit session override when provided, otherwise deterministic
    `44.1k`-family vs `48k`-family selection followed by exact-rate majority
    with upward tiebreak inside the winning family; mismatched stems are
    resampled with deterministic linear interpolation and decisions are
    recorded in renderer metadata/warnings and promoted into per-job
    `render_report` `resampling_receipt` payloads.
  - Added regression coverage for mixed-lossless session rendering and
    deterministic sample-rate selection/resampling behavior.

### Added

- Role-driven deterministic seating templates and immersive-aware placement routing:
  - Added scene-template registry entries:
    `TEMPLATE.SEATING.ORCHESTRA_AUDIENCE`,
    `TEMPLATE.SEATING.ORCHESTRA.IN_ORCHESTRA`, and
    `TEMPLATE.SEATING.BAND.IN_BAND` (root + packaged ontology mirror),
    including scene perspective patches and per-role azimuth regions.
  - Extended scene-template contracts to support role/content matching
    (`role_id`, `role_regex`, `stem_id`, `group_bus`, `bus_id`,
    `content_hint`) and generalized template IDs to `TEMPLATE.*`
    (schemas + packaged mirrors + UI bundle schema pattern updates).
  - Placement policy now consumes template-applied azimuth intent and
    deterministic role defaults to route object sends by region across
    L/C/R, LS/RS, LRS/RRS, and LW/RW (where available), with perspective
    gating so brass/percussion rear bias activates only in `in_orchestra`.
  - Added deterministic section slot spreading so dense/odd instrument sets
    distribute naturally instead of collapsing to one point, and added
    explicit rare-role placement coverage through new roles:
    `ROLE.BRASS.TUBA`, `ROLE.WINDS.BAGPIPE`,
    `ROLE.WINDS.DIDGERIDOO`, `ROLE.WINDS.DUDUK`,
    `ROLE.WINDS.PAN_FLUTE`, `ROLE.WINDS.SHAKUHACHI`,
    `ROLE.WW.BASSOON`, `ROLE.WW.OBOE`, and `ROLE.WW.PICCOLO`.
  - Expanded role ontology + stem inference coverage for uncommon/rare
    instruments across strings (bowed/plucked/struck/harp families), brass
    variants (cornet/flugelhorn/euphonium), woodwinds (bass clarinet,
    contrabassoon, English horn, recorder/ocarina/whistle), free-reed keys,
    and mallet/latin/world percussion so large mixed stem sets classify into
    deterministic stage families without dropping to unknown.
  - Added hybrid stress coverage for `INTENT.PERSPECTIVE=in_orchestra`
    template placement (mixed orchestral + band + rare instruments), and
    refreshed stems-small render-plan hash expectations so the deterministic
    self-dogfood regression harness stays aligned with the expanded role map.
  - Bed overhead sends are now hall/room-focused and capped; non-hall/room
    beds stay surround-only by default (object heights remain bed-first).
  - Added regression coverage for mini-orchestra stems-map → scene → template
    → placement behavior, including violin left bias and brass rear bias only
    in `in_orchestra`.

- Scene builder + conservative surround bed routing contract hardening:
  - Scene schema now allows deterministic bed-to-stem mapping via
    `beds[].stem_ids` (root schema + packaged mirror).
  - `mmo scene build --map <stems_map.json> --bus <bus_plan.json> --out <scene.json>`
    now emits stricter conservative classification behavior:
    bed candidates include pads/ambience/room/long-SFX/drones/crowds/reverbs;
    unknowns remain low-confidence objects with no placement hints.
  - Placement policy v1 now enforces front-only object routing, subtle
    deterministic bed surround/height sends (capped, ~-12 dB relative), and
    confidence/lock-based surround-disable behavior.
  - Added deterministic bed stem routing from scene (`beds[].stem_ids`) into
    render-intent `stem_sends`, with bed rows overriding object rows per stem.

- 7.1.6 conservative immersive support + downmix QA fallback coverage:
  - Placement mixdown renderer now emits `LAYOUT.7_1_6` alongside existing
    immersive outputs.
  - Rendered surround-vs-stereo similarity fallback now includes `LAYOUT.7_1_6`
    in the one-shot bounded backoff gate set.
  - Added versioned `LAYOUT.7_1_6 -> LAYOUT.2_0` downmix conversion
    (`DMX.IMM.7_1_6_TO_2_0.COMPOSED`) to ontology policy and matrix registries
    (root + packaged mirrors).

- Placement receipts now explicitly explain immersive sends:
  - `stem_send_summary` rows include per-stem `surround_sends`,
    `overhead_sends`, and `why` evidence arrays for deterministic receipts.

- GUI scene-intent preview contract + web rendering:
  - Added deterministic `scene_preview` payload in `ui_bundle.json` with
    layout options for `LAYOUT.5_1`, `LAYOUT.7_1`, `LAYOUT.7_1_4`, and
    `LAYOUT.9_1_6`, plus per-object confidence/position rows and bed energy.
  - Added scene-preview warnings for low confidence and missing lock coverage.
  - Web GUI now renders a top-down scene view with layout selector, labeled
    object dots (confidence), and bed halo visualization before audition.

- Stems-small real-world naming regression fixture chain:
  - Added compact redistributable fixture sessions under
    `fixtures/stems_small/` covering numeric suffixes and compound naming
    patterns observed in real inventories (`ElecGtr`, `BackingVox`,
    `Synth*`, `SFX`, `BassDI`, drum mic variants).
  - Added deterministic expected snapshots:
    `fixtures/expected_bus_plan.json` and `fixtures/expected_scene.json`.
  - Added CI regression coverage in `tests/test_stems_small_regression.py`
    for stems->bus-plan->scene snapshots, SHA-256 output hashing, target-chain
    render-plan determinism (`2.0/5.1/7.1/7.1.4/9.1.6`), and passing downmix
    gate checks for downmix targets.

- Conservative immersive height render targets and strict fallback routing:
  - Added `TARGET.IMMERSIVE.9_1_6` plus bed-first fallback notes for `TARGET.IMMERSIVE.7_1_4` / `TARGET.IMMERSIVE.9_1_6` in render target registries.
  - Added `LAYOUT.9_1_6` downmix conversions (`-> 7.1.4`, `-> 7.1`, `-> 5.1`, `-> 2.0`) and conservative immersive matrices in the fold-down policy pack, including a bed-first `9.1.6 -> 7.1.4` path.
  - Added regression coverage for immersive target registration, `9.1.6` shorthand token resolution, and downmix conversion inventory/fallback path assertions.

- Scene build lock/override contract for intent steering:
  - Added `mmo scene build --locks <scene_locks.yaml>` support for both
    `--report` and `--map/--bus` build paths.
  - Added `src/mmo/core/locks.py` with deterministic override loading and
    precedence resolution (`locks > explicit metadata > inference`) for
    per-stem `role_id`, `bus_id`, placement (`azimuth_deg`, `width`, `depth`),
    surround send caps, and height send caps.
  - Extended `scene.schema.json` (plus packaged mirror) with
    `intent.surround_send_caps` / `intent.height_send_caps` /
    `intent.perspective` and richer `metadata.locks_receipt` sources so scene
    artifacts record `locked` vs `explicit_metadata` vs `inferred` provenance
    across azimuth/width/depth/surround/height.
  - Placement policy now enforces `LOCK.NO_HEIGHT_SEND`, applies
    `intent.height_send_caps` to immersive top channels, and carries expanded
    lock provenance markers into render-intent notes for downstream receipts.
  - Added explicit immersive perspective intent (`INTENT.PERSPECTIVE`) with
    deterministic scene-level markers (`in_band`, `in_orchestra`) in placement
    render-intent notes.
  - Added coverage in `tests/test_locks.py`, `tests/test_cli_scene.py`, and
    `tests/test_placement_policy.py`.

- DSP pipeline hook scaffold with strict bounded authority:
  - Added strict `schemas/plugin_manifest.json` (plus packaged mirror) for DSP
    hook plugin manifests (`schema_version`, `stage_scope`, authority,
    evidence contract, and parameter bounds).
  - Added deterministic bus-aware hook runner at
    `src/mmo/core/dsp_pipeline_hooks.py` with three canonical stages:
    `pre_bus_stem`, `bus`, and `post_master`, including authority refusal
    paths and explainable `what/why/where/confidence` events.
  - Added one low-risk default plugin:
    `DSP.PLUGIN.HPF_RUMBLE_GUARD_V0` (conservative high-pass planning only for
    non-bass roles when rumble evidence confidence is high).
  - Wired render-engine stem dispatch flow to execute DSP hooks and emit DSP
    explainability events through `ProgressTracker` logs.
  - Added deterministic coverage in
    `tests/test_dsp_pipeline_hooks.py` and
    `tests/test_render_engine_dsp_hooks.py`.

- Downmix similarity gate framework for rendered surround vs stereo reference:
  - Added deterministic rendered-audio gate metrics for
    `loudness delta`, `correlation over time`, `coarse-band spectral distance`,
    `peak delta`, and `true-peak delta`.
  - Added one-shot bounded fallback for `LAYOUT.5_1`/`LAYOUT.7_1` that reduces
    surround channel sends and re-runs similarity once.
  - Wired render-many workflow to run these checks when stereo + surround
    outputs are both available and to persist results in `report.downmix_qa`.
  - Added version annotations for canonical `5.1 -> 2.0` and `7.1 -> 2.0`
    downmix policies in ontology contract + packaged mirror.

- Baseline mixdown renderer for safe-render zero-recommendation runs:
  - Added `PLUGIN.RENDERER.MIXDOWN_BASELINE` with `true_multichannel`
    capability metadata (`max_channels: 16`) and deterministic headroom
    policy (`worst_case_peak_sum -> -1 dBFS`, fallback `-12 dB` trim).
  - Added `src/mmo/plugins/renderers/mixdown_renderer.py` to write
    conservative layout masters:
    `LAYOUT_2_0/master.wav`, `LAYOUT_5_1/master.wav`, `LAYOUT_7_1/master.wav`,
    `LAYOUT_7_1_4/master.wav`, and `LAYOUT_9_1_6/master.wav`
    (always emitted per run, even with zero eligible recommendations).
  - Added fixture-driven safe-render coverage for baseline output existence
    and deterministic output hashes.
- Scene-driven placement mixdown renderer and immersive send expansion:
  - Added `PLUGIN.RENDERER.PLACEMENT_MIXDOWN_V1` with deterministic scene-based
    placement rendering for `LAYOUT.2_0`, `LAYOUT.5_1`, `LAYOUT.7_1`,
    `LAYOUT.7_1_4`, `LAYOUT.7_1_6`, and `LAYOUT.9_1_6` (WAV PCM24 output).
  - Expanded conservative placement policy support to immersive layouts with
    explicit wide/height speaker handling (`SPK.LW/RW`,
    `SPK.TFL/TFR/TRL/TRR/TFC/TBC`), front-only object routing, and
    confidence-gated/capped bed sends for translation safety.
  - Extended rendered surround-similarity fallback attenuation to cover
    immersive backoff channels (surrounds, heights, wides) for
    `LAYOUT.7_1_4`, `LAYOUT.7_1_6`, and `LAYOUT.9_1_6` in addition to `5.1/7.1`.
- Deterministic stems bus-plan artifact generator:
  - Added `mmo stems bus-plan --map <stems_map.json> --out <bus_plan.json> [--csv <bus_plan.csv>]`
    to build a schema-validated `mmo.bus_plan.v1` artifact from classified stems.
  - Added `src/mmo/core/bus_plan.py` with deterministic stem ordering, fixed main-bus group
    ordering (`DRUMS`, `BASS`, `MUSIC`, `VOX`, `FX`, `OTHER`), and drum consolidation rules
    (`KICK`, `SNARE`, `TOMS`, `PERC`, `CYMBALS`) under `BUS.MASTER`.
  - Added `schemas/bus_plan.schema.json` and packaged mirror
    `src/mmo/data/schemas/bus_plan.schema.json`.
  - Added end-to-end CLI coverage in `tests/test_cli_stems_bus_plan.py` validating schema
    compliance and expected bus assignments for kick/snare/synth/SFX stems.
- GUI Analyze now emits and surfaces stems bus planning:
  - Desktop GUI post-analyze stage now runs deterministic
    `stems classify` and `stems bus-plan` into `_mmo_gui/`
    (`stems_map.json`, `bus_plan.json`, `bus_plan.summary.csv`) before safe-render.
  - Dashboard now shows a dedicated post-analyze `Role counts` + `Bus tree` panel,
    and Live Log mirrors that summary for immediate review.
  - Bus-plan hierarchy now includes `BUS.MASTER` as root, routes grouped buses under
    that root, consolidates cymbals as `BUS.DRUMS.CYMBALS`, and collapses
    `ROLE.BASS.*` to `BUS.BASS`.
  - Added GUI smoke coverage for deterministic post-analyze CLI argv generation and
    bus-plan summary rendering.
- Scene intent scaffolding from stems artifacts:
  - Added `mmo scene build --map <stems_map.json> --bus <bus_plan.json> --out <scene.json> [--profile PROFILE.ASSIST]`
    to generate deterministic scene intent scaffolding from bus-plan inputs.
  - Extended `src/mmo/core/scene_builder.py` with conservative object-vs-bed classification
    (FX/reverbs/rooms/ambience/pads/crowd -> beds; close-miked drums/bass/lead vocals -> objects;
    unknowns remain low-confidence objects with no azimuth hint).
  - Extended `schemas/scene.schema.json` (+ packaged mirror) with optional scene-intent
    scaffolding fields: `generated_utc`, `source_refs`, object placement hints, bed content hints,
    and conservative `rules` defaults.
  - Added fixture-driven and CLI coverage in `tests/test_scene_builder_bus_plan.py` and
    `tests/test_cli_scene.py` for schema validity, deterministic output, and conservative fallback behavior.
- Conservative surround placement policy (scene -> layout mapping):
  - Added `src/mmo/core/placement_policy.py` with deterministic, safety-first channel-send mapping for
    `LAYOUT.2_0`, `LAYOUT.5_1`, and `LAYOUT.7_1`.
  - Rules keep kick/snare/bass front-safe by default, optionally anchor lead/dialogue to center,
    apply modest surround sends for pads/ambience/long FX, and gate percussion/hihat surround sends
    behind width/confidence thresholds.
  - Added a transient-anchor surround-wrap exception only when both explicit immersive intent
    (for example `intent.loudness_bias=back` / “you are there” markers) and high
    width/depth/confidence evidence agree, with lock-aware safety overrides
    (`LOCK.NO_STEREO_WIDENING`, `LOCK.PRESERVE_CENTER_IMAGE`, `LOCK.PRESERVE_TRANSIENTS`).
  - `render_plan` jobs now optionally carry `render_intent` payloads, and `render_report` mirrors them
    so placement policy can be inspected in receipts.
  - Added fixture-driven policy coverage in `tests/test_placement_policy.py` plus integration checks in
    `tests/test_cli_render_plan_from_request.py` and `tests/test_cli_render_report.py`.
- User manual source added under `docs/manual/`:
  - 15 chapters (`00-manual-overview.md` through `14-glossary.md`) covering install,
    stems prep, the four main workflows, reports, safe-render, translation QA,
    presets/locks, watch-folder automation, GUI walkthrough, plugins, projects,
    and troubleshooting.
  - `docs/manual/manual.yaml` — ordered chapter manifest (single source of chapter order).
  - `docs/manual/glossary.yaml` — structured glossary source with terms, definitions,
    and see-also links.
  - Fixed command flags in `docs/manual/12-projects-sessions-and-artifacts.md`:
    `project save` and `project load` now include the required positional `project_dir`.
- Doc accuracy fixes:
  - `docs/user_guide.md` corrected: `scan --out-report` → `scan --out`;
    `report --csv` → `export --csv`; `watch --out-dir` → `watch --out`;
    `project save`/`project load` now include required positional `project_dir`.
    File is now a short quickstart pointer that links to the User Manual.
  - `docs/README.md`: User Manual listed first in "Start here" with links to
    `manual/manual.yaml`; `user_guide.md` re-described as a quickstart pointer.
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
- Versioned loudness profile registry and render receipts:
  - Added data-driven loudness profile ontology at
    `ontology/loudness_profiles.yaml` with broadcast and streaming profiles,
    including compliance vs informational classification and best-effort notes.
  - Added strict schema `schemas/loudness_profiles.schema.json` and wired
    `render_request`/`render_plan` contracts to accept `options.loudness_profile_id`.
  - Added `src/mmo/core/loudness_profiles.py` loader/validator with
    deterministic ordering and stable unknown-profile errors.
  - `render_report` and `render_preflight` now include
    `loudness_profile_receipt` (target, tolerance, true-peak, method, scope,
    warnings), including clear non-fatal warnings for informational profiles
    and not-yet-implemented metering methods.
  - Added contributor doc `docs/21-loudness-profiles.md` describing profile
    contract semantics and no-code registry updates.
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
- Missing-LFE derivation as a deterministic policy primitive:
  - Added `ontology/lfe_derivation_profiles.yaml` + strict schema
    `schemas/lfe_derivation_profiles.schema.json` with default
    `LFE_DERIVE.DOLBY_120_LR24_TRIM_10` and alternate
    `LFE_DERIVE.MUSIC_80_LR24_TRIM_10`.
  - Extended render request/plan/report contracts with
    `lfe_derivation_profile_id`, `lfe_mode`, and structured `lfe_receipt`
    payloads.
  - Added `src/mmo/dsp/lfe_derive.py` deterministic low-pass + phase-max test
    primitive (`L+R` vs `L-R`, `0.1 dB` threshold) with mono and stereo-LFE
    behavior for dual-LFE targets.
  - Planner/report integration now records whether LFE is passthrough vs
    derived (and why), including profile/mode/threshold/delta receipts in
    dry-run contracts.
  - Added unit/integration coverage for in-phase/out-of-phase selection,
    below-threshold default behavior, dual-LFE mirroring, stereo-LFE flip
    decisions, and schema-valid deterministic receipts.
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

### Fixed

- Role-name validation now uses classifier-derived tokens to handle numeric
  suffixes and common compounds (for example `Kick1`, `ElecGtr1`,
  `BackingVox2`, `SFX5`) and avoid `ISSUE.VALIDATION.UNKNOWN_ROLE` false
  positives. Added generic synth recognition via `ROLE.SYNTH.OTHER`
  (`synth`/`synth01`) and `SubDrop` recognition under `ROLE.FX.IMPACT`.

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
