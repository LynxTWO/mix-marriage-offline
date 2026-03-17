# Project When Complete: Mix Marriage Offline (MMO)

<!-- markdownlint-disable-file MD013 -->

## 0) One-sentence goal

An open-source, offline, DAW-agnostic stem-folder mixing assistant that captures
mix intent as a layout-agnostic scene, then deterministically renders to
multiple speaker layouts with strict downmix QA and explainable reports.

## 1) Target users

- Mixing engineers who want fast, repeatable “mix-once, render-many” delivery.
- Hobbyists who want safe, explainable help without black-box automation.
- Tool builders who want a stable Objective Core and a flexible plugin
  ecosystem.

## 2) Core promises (must stay true)

- Offline-first. No network required for core functionality.
- Deterministic outputs: same inputs + settings → same results (including seeded
  decorrelation).
- Explainable: every issue and action includes what/why/where/confidence (+
  evidence).
- Bounded authority: auto-apply only low-risk actions inside limits. Escalate
  high-impact moves.
- Ontology-first: canonical IDs for roles, issues, actions, params, units,
  evidence, layouts, downmix policies.
- Layout safety: every render must pass translation gates and downmix similarity
  checks (at least to stereo).

## 3) Inputs and outputs (contract)

Inputs:

- A “stem folder” (or structured project folder) containing audio files +
  optional metadata.
- Optional user config/profile specifying intent, vibe, and safety limits.

Outputs:

- A validated, layout-agnostic scene file (mix intent) in JSON.
- A human-readable report + recall sheet describing decisions and QA results.
- Rendered outputs for target layouts (optional, conservative by default).
- A machine-readable render report (JSON) including gate results and evidence.

## 4) Definition of Done (checklist)

The project is “complete enough” when all items below are true.

### 4.1 Docs are complete and accurate

Note: numbered docs (`docs/00-*` through `docs/20-*`) are canonical; this
checklist references those files directly.

- [x] docs/00-proposal.md exists and matches the implemented scope.
- [x] docs/01-philosophy.md documents Objective Core vs Subjective Plugins and
      bounded authority.
- [x] docs/02-architecture.md maps modules to repo paths and data flow.
- [x] docs/SCENE_AND_RENDER_CONTRACT_OVERVIEW.md defines objects vs bed/field,
      confidence, locks, and routing intent.
- [x] docs/SCENE_AND_RENDER_CONTRACT_OVERVIEW.md defines canonical channel sets,
      orders, speaker metadata, and downmix rules.
- [x] docs/04-plugin-api.md + docs/13-plugin-authoring.md define plugin
      contracts (channel_mode, link groups, latency, determinism seeds).
- [x] docs/05-fixtures-and-ci.md documents fixtures, CI gates, and determinism
      expectations.
- [x] docs/07-export-guides.md documents how users should export stems for best
      results.
- [x] docs/06-roadmap.md clearly separates “now” vs “later.”
- [x] `README.md`, `docs/README.md`, installer-facing docs, and release-copy
      sources describe only shipped capabilities, supported artifacts, and
      current limitations.

### 4.2 Ontology is stable and versioned

- [x] ontology/\*.yaml covers roles, features, issues, actions, params, units,
      evidence.
- [x] ontology/layouts.yaml defines all supported layouts + canonical channel
      naming and order.
- [x] ontology/downmix.yaml defines explicit, versioned downmix
      matrices/policies.
- [x] ontology/gates.yaml defines QA thresholds and fallback behaviors.
- [x] Ontology changes are additive unless a version bump is made and migration
      notes exist.

### 4.3 Schemas are complete and enforced

Note: schema contracts use `schemas/*.schema.json` naming (not
`schemas/*.json`).

- [x] schemas/project.schema.json validates project input structure.
- [x] schemas/scene.schema.json validates layout-agnostic intent.
- [x] schemas/render_request.schema.json defines render targets and options.
- [x] schemas/render_report.schema.json defines QA + evidence output.
- [x] schemas/report.schema.json defines human-readable report payload shape.
- [x] schemas/plugin.schema.json defines plugin capabilities and semantics.
- [x] Source metadata tag preservation model is implemented
      (`source_metadata.technical` + canonical `TagBag` with
      `raw`/`normalized`/`warnings`).
- [x] Every schema is strict (`additionalProperties: false`) where appropriate.
- [x] CLI and core reject invalid inputs with clear, actionable errors.

### 4.4 Objective Core is implemented and tested

- [x] Validators: folder/session validation, channel semantics checks, layout
      negotiation (including FFmpeg layout alias handling).
- [x] Determinism: seeded operations are reproducible across platforms (document
      any numeric tolerances).
- [x] Export finalization is centralized and disclosed: renderer WAV outputs use
      one deterministic float64 -> PCM policy for bit depth, dither, clamping,
      and receipt metadata.
- [x] Meters: loudness, peaks/true-peak, crest factor, correlation/phase-risk,
      headroom, plus LFE-specific validation and metering.
- [x] Safety gates: hard failures and “fallback to safer routing” behavior are
      implemented.
- [x] Downmix QA: renders pass similarity gates to stereo (and optional
      additional downmix targets).
- [x] “Do no harm” defaults exist and are used when confidence is low. Done:
      rendered similarity fallback now uses a deterministic multi-step sequencer
      with explicit per-step reporting and receipt aggregation; default
      safe-render keeps partial artifacts/receipts plus explicit QA failure
      metadata when safe backoffs are exhausted instead of treating that state
      as an accidental hard stop.

#### 4.4.5 Five channel-ordering standards support (boundary convert + internal SMPTE)

- [x] `ontology/layouts.yaml` has explicit `ordering_variants` for the 5
      supported standards where applicable: SMPTE, FILM, LOGIC_PRO, VST3, AAF.
- [x] `layout_negotiation.get_channel_order(layout_id, standard)` returns the
      correct order for SMPTE (default), FILM, LOGIC_PRO, VST3, and AAF (with
      canonical fallback when a layout has no explicit variant).
- [x] `layout_negotiation.reorder_channels(data, from_order, to_order)` works on
      list, tuple, and NumPy arrays.
- [x] `render_contract.build_render_contract()` accepts `layout_standard`
      (default SMPTE) and records it in the contract.
- [x] `render_engine.render_scene_to_targets()` reads `layout_standard` from
      options and emits explainability notes.
- [x] `safe-render` CLI accepts
      `--layout-standard SMPTE|FILM|LOGIC_PRO|VST3|AAF` (default SMPTE).
- [x] `render-many` threads `layout_standard` through all per-target runs.
- [x] All render receipts and job notes include the active layout standard and
      order-selection notes.
- [x] Regression fixtures in `tests/test_dual_layout_ordering.py` pin exact
      orderings for 5.1 and 7.1.4 SMPTE and FILM.
- [x] End-to-end roundtrip regression matrix in
      `tests/test_layout_standard_roundtrips.py` verifies source->SMPTE->target
      routing for all valid multichannel `LAYOUT.*` entries across
      SMPTE/FILM/LOGIC_PRO/VST3/AAF.
- [x] `schemas/run_config.schema.json` `render.layout_standard` field present
      with enum `[“SMPTE”, “FILM”, “LOGIC_PRO”, “VST3”, “AAF”]`.
- [x] `schemas/render_report.schema.json` `render_job.layout_standard` field
      present.
- [x] `schemas/plugin.schema.json` `capabilities.supported_standards` and
      `capabilities.preferred_standard` fields present.
- [x] Every downmix matrix and QA gate is order-aware (uses channel IDs, not
      fixed indices).
- [x] Plugin channel routing uses `ProcessContext.channel_order` (list of
      `SPK.*` IDs) instead of hard-coded indices.
- [x] Golden multichannel plugin-mode tests pin manifest-declared `per_channel`,
      `linked_group`, and `true_multichannel` dispatch semantics, including
      channel-order safety and deterministic evidence on 5.1 and 7.1.4 fixtures.

#### 4.4.1 Loudness and layout mapping (meter contract)

- [x] Program loudness uses ITU-R BS.1770-5 weighting with explicit, tested
      channel mapping.
- [x] LFE is excluded from program loudness (weight 0.0) and is always reported
      separately.
- [x] Loudness method selection is versioned via a method registry
      (`src/mmo/core/loudness_methods.py`) with stable IDs and placeholder
      forward-compat entries.
- [x] Render-run loudness target selection is versioned via `LOUD.*` ontology
      profiles (`ontology/loudness_profiles.yaml`) and emitted as deterministic
      preflight/report receipts.
- [x] Common layout naming conventions are mapped correctly, including
      FFmpeg-style aliases:
  - 5.1 (back surrounds: BL/BR).
  - 5.1(side) (side surrounds: SL/SR).
- [x] BS.1770-5 Table 4 position weighting is applied for advanced sound-system
      channels from ontology azimuth/elevation metadata, with deterministic
      warning receipts for unknown positions.
- [x] 9.1.6/7.1.6 metadata coverage is complete for loudness weighting inputs,
      including TFC/TBC and wide channels.

#### 4.4.2 LFE validation and musician-friendly guidance

- [x] Supports 1+ LFE channels (x.1, x.2, …) with per-LFE and summed reporting.
- [x] Provides an LFE “content audit” that reports:
  - band-limited level/energy (configurable band, default 20–120 Hz),
  - crest/headroom and true-peak,
  - relative LFE-to-mains low-band energy ratio (profile-driven guidance, not a
    hard rule).
- [x] Detects out-of-band LFE content and flags it with evidence:
  - significant energy above the configured low-pass cutoff (default 120 Hz),
  - problematic infrasonic rumble below the configured high-pass cutoff (default
    20 Hz).
- [x] Missing-LFE derivation is policy-driven and deterministic when targets
      require LFE but source program LFE is absent:
  - default profile `LFE_DERIVE.DOLBY_120_LR24_TRIM_10` (120 Hz / LR24 / -10
    dB),
  - alternate profile `LFE_DERIVE.MUSIC_80_LR24_TRIM_10` (80 Hz / LR24 / -10 dB,
    conservative bass-management-safe rolloff),
  - phase-max test (`L+R` vs `L-R`) with stable `0.1 dB` threshold,
  - dual-LFE default mirrored mono with optional explicit stereo-LFE mode,
  - structured receipts in render plan/report (`status`, selected mode/profile,
    measured delta, threshold, and reason).
- [x] If a corrective filter is recommended, the system must:
  - explain what/why in musician language,
  - require explicit approval before applying,
  - re-run downmix/mono compatibility checks after the change,
  - back off (or refuse) if fold-down similarity or phase-risk gates get worse.
- [x] If the user supplies explicit LFE stems, the system must not silently
      “fix” tone by moving content to mains; it may only recommend options
      (LPF/HPF, split-and-route, or leave as-is) with confidence and tradeoffs.
      What remains: continue broadening regression coverage around other
      corrective-action families, but the explicit-LFE approval/backoff path is
      now wired and fixture-covered.

### 4.5 Subjective Plugins system exists (without breaking core contracts)

- [x] Plugin interface supports max_channels ≥ 32 and declares channel_mode +
      link groups.
- [x] Contributor starter-pack examples under `examples/plugin_authoring/`
      cover `per_channel`, `linked_group`, and `true_multichannel` execution,
      plus manifest-backed safety and determinism expectations.
- [x] Plugins report latency (fixed/dynamic) and host delay-comp policy.
- [x] Plugins may suggest actions with confidence, but cannot override explicit
      user intent.
- [x] High-impact moves require explicit approval in the workflow contract.
- [x] Installed package plugin loading does not rely on repo-root imports;
      bundled manifests under `mmo.data/plugins` are discovered from any working
      directory. Done: precedence is centralized in
      `src/mmo/core/precedence.py`, safe-render re-applies it before placement
      and authority checks, and `tests/test_lock_precedence_matrix.py` pins the
      lock-vs-suggestion contract across scene build, placement, renderer
      application, and plugin eligibility. Done: medium/high recommendation
      receipts now disclose exact parameter deltas, scope, and rollback notes,
      and safe-render requires explicit per-rec user approval before those
      actions become render-eligible.

### 4.6 Rendering targets are supported (minimum viable set)

- [x] Stereo (2.0) render contract is correct and validated.
- [x] Binaural headphone deliverable is supported as a first-class target
      (`TARGET.HEADPHONES.BINAURAL` / `LAYOUT.BINAURAL`) using deterministic
      conservative virtualization with source-layout traceability.
- [x] 2.1 and 4.1 layouts are correctly supported when requested (render +
      meters + downmix QA).
- [x] First-class front/quad variants are available as explicit targets:
      `TARGET.FRONT.3_0`, `TARGET.FRONT.3_1`, `TARGET.SURROUND.4_0`,
      `TARGET.SURROUND.4_1`.
- [x] 5.1 render contract is correct and validated (including 5.1 vs 5.1(side)
      semantic differences).
- [x] 7.1 render contract is correct and validated.
- [x] One immersive bed target (example: 7.1.4) is correct and validated.
- [x] LFE policy is explicit: treated as a creative send plus bass management
      rules.
- [x] Multi-LFE layouts (example: 5.2, 7.2.4) are supported as first-class
      layouts when declared, with canonical naming/order (LFE1, LFE2, …).
- [x] “.2” is not assumed as dual-LFE program content unless explicitly required
      by target spec.
- [x] WAV channel-mask disambiguation for dual-LFE ingest/export is implemented
      with a conservative export contract: direct-out mask strategy (`mask=0`)
      plus explicit canonical SPK channel order in render-report/recall context.
- [x] Dual-LFE export caveat is documented and emitted at runtime: some external
      tools still collapse/relabel `LFE2`; users must validate with
      render-report channel order + ffprobe layout output.
- [x] All render targets support both SMPTE (default) and Film channel ordering;
      the active standard is recorded in every render contract and receipt.
- [x] Regression tests verify deterministic channel-order roundtrips across
      SMPTE/FILM/LOGIC_PRO/VST3/AAF for all valid multichannel `LAYOUT.*`
      entries. What remains: expand fixture-session coverage for front/quad
      render variants in end-to-end audio artifacts.

### 4.7 Fixtures and CI prevent regressions

- [x] Fixture sessions exist for stereo, 5.1, 7.1, and one immersive target.
- [x] Fixture for “stereo stems with baked pan/width” validates inference is
      advisory and confidence-gated.
- [x] Determinism tests exist (byte-stable or numerically stable within
      documented tolerance).
- [x] Downmix similarity tests exist and fail CI when gates regress.
- [x] Cross-OS golden fixtures validate
      `classify -> bus-plan -> scene -> safe-render --render-many` with exact
      bus-plan/scene snapshots, exact normalized manifest + receipt hashes,
      exact QA issue IDs/severities, exact channel ordering, and tolerance-based
      per-channel metrics for stereo/surround/immersive targets.
- [x] Repo-root pytest discovery is constrained to the project `tests/` tree so
      scratch dependency mirrors and transient build directories do not pollute
      CI or local full-suite runs.
- [x] Focused plugin-mode golden audio tests validate per-channel speaker-ID
      routing, linked front/surround/height group behavior, and true
      multichannel full-buffer semantics through a manifest-driven runner.
- [x] A dedicated 32-channel render contract fixture proves MMO can export a
      deterministic `LAYOUT.32CH` artifact end-to-end (`nchannels == 32`,
      manifest `channel_order` length `32`, stable SHA-256 across two runs).
- [x] CI runs on Windows, Linux, macOS (or documents any limitations).
- [x] Packaged binaries and one-click installers receive smoke checks on
      Windows, macOS, and Linux against built release artifacts. Done:
      GitHub-hosted workflow pins now use Node 24-ready majors for
      `actions/checkout`, `actions/setup-python`, `actions/setup-node`,
      `actions/upload-artifact`, and `actions/download-artifact` where upstream
      has published them, so runtime deprecations do not silently age out the CI
      matrix. Done: CI and local desktop-dev expectations now pin the current
      validated environment surface explicitly: Node 24 LTS for GUI/Tauri work,
      Rust 1.94.0 for the Tauri crate, and versioned GitHub-hosted runner images
      instead of floating `*-latest` labels. Done: PR CI and release CI now
      build packaged Tauri desktop artifacts on Windows/macOS/Linux, launch the
      packaged app in smoke mode, verify the bundled sidecar doctor plus the
      validate -> analyze -> scene -> render happy path against a tiny fixture,
      and assert the expected workspace artifact paths. Done: packaged desktop
      smoke now probes the bundled sidecar directly for `mmo --version`,
      bundled plugin validation, and `mmo env doctor --format json` before the
      app workflow so frozen-entrypoint regressions fail fast. Done: macOS
      packaged smoke now accepts both staged `mmo-$TARGET_TRIPLE` names and
      post-bundle bare `mmo` sidecars, and missing-sidecar failures print short
      bundle-directory receipts for faster triage. Remaining RC signoff:
      complete one human fresh-install walkthrough on the `1.0.0-rc.1`
      desktop artifacts before tagging stable `1.0.0`.

### 4.8 UX/CLI is usable for real work

- [x] CLI can: validate, analyze, generate scene, render, and output reports.
- [x] CLI can generate deterministic bus planning artifacts from classified
      stems (`mmo stems bus-plan` from `stems_map.json`).
- [x] CLI can scaffold deterministic scene intent from stems artifacts
      (`mmo scene build --map <stems_map.json> --bus <bus_plan.json>`).
- [x] `mmo scene build --locks <scene_locks.yaml>` applies deterministic
      per-stem user overrides (role/bus/placement depth/surround caps/height
      caps), preserves full locked `bus_id` identity (for example
      `BUS.DRUMS.KICK`) plus derived `group_bus`, with centralized precedence
      `locks > explicit scene fields > explicit CLI flags > plugin/template suggestions > inference defaults`,
      and records canonical source provenance (`locked` / `explicit` /
      `suggested` / `inferred`) in scene metadata receipts (including
      original/applied values plus lock IDs for locked fields).
- [x] `mmo scene lint` performs deterministic pre-render scene QA with
      explainable issue reports for missing stem IDs/refs/files, duplicate
      object/bus refs, placement range violations, lock conflicts (including
      conflicting per-stem bus locks), low-confidence critical anchors (warn),
      immersive perspective without bed/ambient candidates (warn), and immersive
      perspective without template evidence (warn).
- [x] `safe-render` preflight auto-runs scene lint for explicit `--scene`
      inputs; `--scene-strict` fails fast when lint reports errors.
- [x] Target selection is interchangeable across CLI/GUI flows: `TARGET.*`,
      `LAYOUT.*`, and musician shorthands (`stereo`, `5.1`, `7.1`, `7.1.4`,
      `binaural`); ambiguous tokens fail deterministically with sorted
      candidates.
- [x] Errors are actionable (tell the user what/why/where/how to fix).
- [x] Reports include: issues, actions taken, actions suggested, confidence, and
      evidence references.
- [x] A “dry-run” mode exists for suggestions without applying changes.
- [x] Base source installs include NumPy, and `mmo env doctor` reports required
      runtime audio tool availability (`ffmpeg`/`ffprobe`) explicitly.
- [x] `safe-render` supports live explainable progress logging
      (`what/why/where/confidence`) and cooperative cancellation
      (`--cancel-file`) for CLI/GUI runs.
- [x] `safe-render` always produces baseline WAV outputs for supported
      2.0/5.1/7.1/7.1.4/9.1.6 layout targets, even when no recommendations are
      render-eligible.
- [x] Scene-driven placement rendering supports one layout-agnostic scene
      feeding conservative `2.0/5.1/7.1/7.1.4/7.1.6/9.1.6` outputs with
      deterministic role/azimuth-aware object stage routing (perspective-gated
      side/rear/wide use) and capped confidence-gated hall/room-first bed
      surround/height sends.
- [x] Optional seeded decorrelated bed widening is available for immersive
      placement renders with confidence/content gating (`BED.*` +
      hint/threshold), and is hard-bounded by rendered surround similarity QA
      with bounded backoff and auto-disable/rerender fallback when gate failure
      persists.
- [x] `safe-render` supports first-class explicit scene workflows: `--scene` is
      preferred over implicit scene rebuild, optional `--scene-locks` overrides
      are applied before placement policy, and receipts always record scene
      source + lock source provenance (`explicit` vs `auto_built`).
- [x] Placement scene renderer uses deterministic two-pass streaming
      (`chunk_frames=4096`): pass 1 peak scan + pass 2 trimmed PCM24 chunk
      writes, so long sessions avoid full-program in-memory mix buffers.
- [x] Placement + baseline safe-render mixdown paths now use a shared lossless
      decode abstraction (`wav`/`flac`/`wv`/`aiff`/`aif`/`ape`) with
      deterministic sample-rate policy (`explicit override`, otherwise dominant
      `44.1k` vs `48k` family, then exact-rate majority with upward tiebreak)
      and deterministic linear resampling receipts in output metadata and
      `render_report` jobs.
- [x] Stem-role inference now includes broad uncommon/rare instrument aliases
      (world strings/winds/brass/percussion/keys/guitars), and those roles feed
      the same deterministic template + placement path so large mixed ensembles
      still map into explainable real-world stage families in `in_orchestra`
      mode.
- [x] `safe-render` never reports zero-output renderer stages as success: it
      emits `ISSUE.RENDER.NO_OUTPUTS` and exits non-zero by default unless
      `--allow-empty-outputs` is explicitly set.
- [x] `safe-render` supports deterministic headphone preview rendering via
      `--preview-headphones`, writing explainable binaural preview outputs that
      reference their source render artifacts.
- [x] `safe-render` now supports scene-aware debug exports for DAW recall:
      `--export-stems`, `--export-buses`, `--export-master/--no-export-master`,
      and `--export-layouts` produce deterministic stem-copy/subbus/master
      artifacts with manifest/receipt hashes, and recall-sheet context now
      includes `stem -> subbus -> BUS.MAIN -> scene object/bed` mapping.
- [x] `mmo watch <folder>` supports smart batch processing for incoming stems by
      debouncing filesystem events and auto-running deterministic
      `--render-many` workflows on changed stem sets.
- [x] `mmo watch <folder>` can emit deterministic visual batch-queue snapshots
      with cinematic progress states (`--visual-queue --cinematic-progress`) for
      operator monitoring without changing render decisions.
- [x] Offline plugin marketplace discovery is available via bundled ontology
      index, CLI (`mmo plugin list/update`), and GUI browser surfaces.
- [x] Desktop GUI includes an artistic `Discover` marketplace tab with preview
      cards and deterministic one-click offline plugin install flow.
- [x] Compare is a first-class user-facing workflow across CLI and GUI:
      artifact-backed compare flows (`current vs last run`, `report vs report`)
      are visible from results surfaces, `compare_report.json` records the
      deterministic loudness-match method/amount, and any evaluation-only
      compensation is disclosed in user-visible compare results. Done: the
      Tauri workflow now adds contextual artifact quick actions
      (copy/reveal/open sibling receipt-manifest-QA plus rerun compare/render
      shortcuts) anywhere the core workspace artifacts are surfaced, plus a
      bounded in-app audition transport for selected preview artifacts and
      compare A/B playback. Done: audition gain setup now fails open to
      `audio.volume` if Web Audio gain-node setup stalls, so playback cannot be
      trapped in `Loading` by a suspended `AudioContext`.
- [x] A “variant runner” can render multiple output variants
      (profiles/presets/targets) while reusing cached analysis artifacts keyed
      by content hash.
- [x] Project session JSON persistence exists for `scene + history + receipts`
      via `mmo project save/load`, with deterministic JSON output and strict
      schema validation. Tauri parity for the desktop workflow is complete,
      including scene-lock editing plus compare/results artifact parity.

### 4.8.1 GUI is ergonomically safe and AI-readable (a work of art in itself, so creatives and nerds alike love it. Strong typography, cinematic color contrast, and intentional spacing/visual hierarchy so it feels crafted, not utilitarian, while still staying cross-platform and deterministic)

- [x] GUI delivery has one desktop app policy: Tauri is the shipped desktop
      app path, and the retired CustomTkinter path is removed from source,
      packaging, CI, and release workflows.
- [x] `docs/gui_parity.md` defines the required Tauri screens/behaviors and CI
      fails when the checklist loses required links, screens, or behaviors.
- [x] Legacy CustomTkinter source, packaging, and release machinery are retired
      so desktop distribution is Tauri-only and standalone frozen binaries are
      CLI-only.
- [x] GUI includes a bounded-authority `Preview on Headphones` action that
      forwards to `safe-render --preview-headphones` and writes deterministic
      binaural audition files.
- [x] Web GUI Audition panel includes deterministic headphone preview visuals:
      pulsing waveform display and warm analog L/R metering driven by live
      playback.
- [x] Web GUI includes a deterministic scene-intent top-down preview
      (5.1/7.1/7.1.4/9.1.6) showing labeled object dots with confidence, bed
      halo energy, and warnings for low-confidence intent rows or missing lock
      coverage.
- [x] Web GUI now includes scene lock editing with save-to-file flow: per-object
      confidence list, per-stem role override dropdown, front-only toggle,
      surround/height cap sliders, perspective selector, and deterministic save
      to `scene_locks.yaml` with scene draft refresh for re-render.
- [x] Desktop GUI Analyze immediately surfaces deterministic stems routing
      context: `_mmo_gui/stems_map.json` + `_mmo_gui/bus_plan.json` (+ CSV
      summary) are generated, and the Dashboard shows role counts with a
      hierarchical bus tree.
- [x] Desktop GUI includes a first-class Scene tab after Analyze:
      `_mmo_gui/scene.json` + `_mmo_gui/scene_lint.json` are generated, the tab
      surfaces perspective/object/bed explainability plus lint warnings, and
      the Tauri workflow can inspect/edit/save deterministic
      `scene_locks.yaml` overrides with scene refresh for reruns.
- [x] An isolated Tauri desktop scaffold now exists under `gui/desktop-tauri`,
      using a Vite frontend with cross-platform CI release-binary builds on
      Windows, macOS, and Linux.
- [x] Canonical Tauri manual screenshots are regenerated in CI through
      `tools/capture_tauri_screenshots.py` and diffed against
      `docs/manual/assets/screenshots`, so screenshot regressions track the
      shipped desktop workflow instead of the legacy Tk GUI. Done: the
      canonical Tauri baselines now use a fixed-region `1280 x 900` CSS-pixel
      capture contract instead of unstable full-page document height.
- [x] The Tauri desktop app now stages a frozen `mmo` CLI as a sidecar, ships
      bundled MMO packaged data through that sidecar, and includes a Doctor
      screen that verifies `mmo --version`, bundled plugin validation, and
      runtime path resolution without system Python/Node installs. Done: the
      sidecar build contract is now pinned to a dedicated frozen-safe absolute
      import stub so packaged binaries do not depend on `mmo.__main__`
      semantics.
- [x] The Tauri desktop app now runs prepare/validate/analyze/render directly
      through the packaged sidecar, streams live stdout/stderr into a desktop
      timeline, and writes deterministic artifacts under a user-provided
      workspace folder without requiring the Node `gui/server.mjs` runtime in
      production.
- [x] The Tauri GUI exposes the same workflow as the CLI: validate ->
      analyze -> scene -> render -> results -> compare, using the same
      project/report/scene/render artifacts the CLI writes.
- [x] GUI copy and structure follow the design system in
      ontology/gui_design.yaml (theme tokens, screen templates, and progressive
      disclosure).
- [x] Any plugin/config UI is generated from JSON Schema with optional UI hints
      (example: x_mmo_ui or a dedicated ui_hints registry) so agents do not
      hand-build one-off forms. The required Tauri parity behaviors tracked in
      `docs/gui_parity.md` are complete for the desktop workflow.

Interaction standards (non-negotiable):

- [x] Primary desktop workflow supports keyboard-first operation: visible focus
      states, major-panel shortcuts, tab semantics, Results artifact-browser
      selection, and keyboard adjustment for slider/knob/XY controls.
- [x] Every numeric control supports direct text entry (exact value).
- [x] Every drag control supports a fine-adjust modifier (Shift/Ctrl is fine)
      with visible on-screen feedback while engaged.
- [x] Units are always visible (Hz, dB, ms, LUFS, degrees, samples) and
      rounding/display rules are consistent.

Reusable component library (minimum set for v1 GUI parity):

- [x] Controls: knob/rotary, fader/slider, toggle/button, segmented selector, XY
      pad, preset browser with search/tags, A/B toggle, value readout.
- [x] Metering: peak/RMS, true-peak, LUFS, multi-channel meters
      (surround/immersive energy distribution), plus deterministic desktop
      inspection for gain reduction and stereo/phase coherence.
- [x] Visualizers (offline-rendered is acceptable): waveform (pre/post overlay),
      spectrum (FFT), optional spectrogram, EQ curve editor, and desktop
      vectorscope/transfer-curve proxies sourced from artifacts.

AI-readable layout export + validation (prevents overlaps/off-screen UI):

- [x] The GUI can export a machine-readable layout manifest per screen/view that
      conforms to:
  - schemas/ui_layout.schema.json (authored contract), and
  - schemas/ui_layout_snapshot.schema.json (resolved snapshot with pixel boxes
    and violations). The layout snapshot must include:
  - viewport size,
  - section and widget ids,
  - per-widget param_ref (when applicable),
  - bounding boxes (x_px, y_px, width_px, height_px),
  - per-widget minimum sizes.
- [x] A layout validator runs in CI and fails on:
  - overlapping interactive hit targets,
  - controls rendered off-screen at supported breakpoints,
  - missing labels/units for numeric controls,
  - insufficient spacing versus the declared spacing tokens.
- [x] A global GUI scale control exists (or responsive scaling equivalent) for
      laptop vs 4K displays. Done: Firefox design-system regression coverage now
      keeps required Tauri widgets inside viewport bounds at the mobile
      breakpoint, exact-entry -> drag flows retain visible fine-adjust
      feedback without scroll-induced coordinate drift, and card-overlap
      assertions now scope to top-level Tauri widgets so nested sub-controls do
      not create false layout collisions.

## 4.9 DSP engine and plugin execution (Definition of Done)

The project is not considered complete until the DSP pipeline, plugin contracts,
and render behavior below are implemented, documented, and covered by tests.
The remaining DSP/plugin contract items below are now closed unless new scope is
added.

### 4.9.1 DSP core guarantees

- [x] Internal processing uses a documented floating-point format (default:
      64-bit float).
- [x] Export finalization has a documented, deterministic policy (per target
      format/bit depth):
  - none (when exporting float),
  - TPDF (and optional high-pass TPDF),
  - optional noise shaping. Experimental “no-noise” or ML-based approaches are
    allowed only as explicitly selected plugins, never as a silent default.
- [x] All DSP is offline-render capable (no realtime assumptions).
- [x] Sample rate handling is explicit:
  - [x] Session target sample rate selection is deterministic and explainable,
        and any resampling uses a declared algorithm with deterministic settings
        plus per-job receipts.
- [x] Channel counts up to at least 32 are supported end-to-end.
- [x] Plugin order is deterministic and serialized in reports.
- [x] Every processing decision that can affect tone/balance/spatialization is
      either:
  - (a) explicitly requested by the user intent, or
  - (b) recommended with confidence and requires approval if high-impact, or
  - (c) skipped when confidence is low.

### 4.9.2 Canonical DSP stages (pipeline shape)

- [x] The engine implements a stable, documented stage graph (minimum):
  1. Input normalization and alignment (optional, conservative).
  2. Analysis/metering pass (no audio mutation).
  3. Scene inference pass (advisory only, writes intent with confidence).
  4. Pre-render corrective pass (low-risk only, bounded authority).
  5. Render pass (scene → target layout) with routing + downmix policy.
  6. Post-render QA pass (gates, downmix similarity, correlation/phase-risk).
  7. Export pass (format, dither policy, loudness/true-peak constraints).
- [x] Deterministic DSP hook scaffold exists for the corrective-pass boundary:
      `pre_bus_stem` (per-stem), `bus` (per-bus group), and `post_master` stage
      hooks with bounded-authority enforcement and explainable event output.
- [x] Each stage emits evidence and timing into the render report.

### 4.9.3 Plugin API: audio processing contract

- [x] A plugin manifest declares:
  - name/id/version
  - max_channels
  - channel_mode: per-channel | linked-group | true-multichannel
  - supported link groups (front, surrounds, heights, all, custom)
  - latency: fixed or dynamic (and exact reporting method)
  - deterministic_seed_usage: yes/no + seed inputs
  - requirements: needs speaker positions? bed-only? objects-capable?
- [x] Renderer manifests include digital-first DSP traits
      (`capabilities.dsp_traits`) with explicit `tier` + `linearity`.
- [x] Nonlinear renderer manifests declare anti-aliasing strategy (not `none`).
- [x] Renderer manifests include measurable truth contracts via
      `capabilities.dsp_traits.measurable_claims`.
- [x] Plugins operate on typed buffers with explicit channel semantics (not “raw
      arrays”). Done: stereo render execution and manifest-driven plugin-mode
      dispatch now pass `mmo.dsp.buffer.AudioBufferF64` at the real plugin
      boundary and reject mismatched return types loudly.
- [x] Plugins must be pure with respect to determinism:
  - [x] No internal randomness unless seeded from the provided seed.
  - [x] No wall-clock/time-based behavior.
  - [x] No dependency on host thread scheduling for results.

### 4.9.4 Bounded authority for DSP (what plugins may change)

- [x] Plugins are classified by impact level:
  - Low-risk: metering, analysis, small safety-limited trims, de-click, DC
    removal.
  - Medium: gentle EQ/dynamics within strict ranges.
  - High: tone reshaping, balance changes, spatial placement changes, aggressive
    dynamics, destructive edits.
- [x] Only low-risk changes may be auto-applied, and only within user-defined
      limits.
- [x] Medium/high changes must be output as recommendations with:
  - what/why/where/confidence
  - the exact parameter deltas proposed
  - rollback notes (how to undo)
- [x] Any change to object vs bed classification or spatial routing is treated
      as high-impact unless explicitly user-locked.

### 4.9.5 Multichannel and layout safety rules (DSP-level)

- [x] Plugins must declare whether they are:
  - bed-only
  - object-capable
  - layout-agnostic (works pre-render)
  - layout-specific (works post-render)
- [x] If a plugin cannot guarantee safe multichannel behavior, the engine must:
  - [x] restrict it to safe channel groups, or
  - [x] bypass it, and log a warning with evidence.

### 4.9.6 Downmix QA and fallback behaviors (DSP-level)

- [x] Render outputs must pass downmix similarity gates (minimum: stereo).
- [x] Render-many includes a deterministic one-shot surround fallback: compare
      `stereo` vs `downmix(rendered 5.1/7.1)`, then attenuate surround sends and
      retry once when the similarity gate fails.
- [x] If a gate fails, the system applies a documented fallback strategy:
  - reduce surround/height aggressiveness
  - reduce decorrelation
  - collapse risky wideners
  - move ambiguous energy forward
  - re-run render + QA until pass or stop with an explainable failure report
- [x] Failures are never silent. Reports must show the failing metrics and the
      fallback actions attempted. Done: safe-render now preserves renderer-side
      fallback config from session fixtures, records ordered per-step
      before/after QA metrics through safety collapse, and surfaces explicit
      gate-failure diagnostics when collapse still does not pass.

### 4.9.7 Formats, export, and reproducibility

- [x] Export formats are explicit and deterministic:
  - WAV/BWF at minimum.
  - Optional: FLAC and/or WavPack (deterministic encoder settings).
  - Optional: Wave64 for very large multichannel outputs.
- [x] Export metadata round-trip is best-effort and explainable:
  - FLAC/WavPack outputs re-embed normalized + raw tag fields deterministically.
  - WAV outputs embed conservative INFO subsets and emit skipped-key receipts.
  - `render_report`/deliverables file rows carry `metadata_receipt` entries.
- [x] Rendered files embed enough metadata for traceability:
  - tool version, optional git commit, scene hash, render contract version,
    downmix policy version.
  - layout/profile/export-profile IDs and deterministic seed are embedded in
    renderer WAV outputs (`iXML`) and ffmpeg-backed lossless outputs (`flac`,
    `wv`, `aiff`, `alac`).
- [x] Golden fixtures prove:
  - determinism across OS targets (within documented tolerance),
  - consistent gating outcomes,
  - identical channel ordering and naming per contract.

### 4.9.8 Tests required for “complete”

- [x] Unit tests for plugin manifest validation and stage ordering determinism.
- [x] Golden-audio tests for at least:
  - one per-channel plugin
  - one linked-group plugin
  - one true-multichannel plugin
- [x] A regression test that proves a failed downmix gate triggers the correct
      fallback sequence.

## 5) Non-goals (explicitly out of scope for “complete”)

- DAW plugin hosting (VST/AU/AAX).
- Black-box ML that overrides gates or explicit user intent.
- Claims of reconstructing true object metadata from a stereo bounce.
- Guaranteed literal front-back placement from stereo cues (treat depth as
  directness/diffuseness proxies).

## 6) Milestones (suggested order)

1. Docs + ontology + schemas (contracts first).
2. Validators + meters + gates (Objective Core).
3. Scene generation + reporting.
4. Rendering targets + downmix QA.
5. Plugin system + conservative detectors/resolvers.
6. Fixtures + CI hardening + cross-platform polish.

## 7) Update policy (prevents “context rot”)

- Any PR that changes behavior must update:
  - the relevant doc section,
  - the schema (if shape changed),
  - and at least one test/fixture.
- If docs and code disagree, code is “wrong” until docs are updated or scope is
  revised.

## 8) Source of truth pointers

- Primary contracts: docs/ + ontology/ + schemas/
- Process rules for AI tools: AGENTS.md

## 9) Optional capabilities (post-v1)

These items should stay tracked, but they do not block v1 completion once
sections 4.1 through 4.9 are closed.

- [x] Presets (example: EQ vibe presets) can be initialized from measured stem
      or report context with bounded, explainable preview metadata, and preset
      preview does not create surprise loudness jumps because any preview
      compensation remains evaluation-only unless explicitly committed.
- [x] Dynamics/spatial views (offline-rendered is acceptable): gain reduction
      meter, phase correlation, goniometer/vectorscope, optional transfer
      curve. Done: the Tauri Results screen now renders deterministic,
      artifact-backed inspection widgets from `safe_render_receipt.json` and
      `render_qa.json`.
- [x] Explainability overlays (“what/why”), confidence indicator for
      recommendations, and a compact “what changed” summary. Done: the Tauri
      Results/Compare screens now surface hover/focus hint overlays,
      receipt-backed recommendation confidence rows, and compact change-summary
      chips without making optional macro/mood extras blocking.
- [ ] Macro controls with semantic labels (example: Warmth, Air, Punch, Glue)
      that map to multiple parameters and always disclose what they change.
- [ ] Mood/texture selectors (tag chips or icons) that swap whole preset
      strategies without jargon.
- [ ] “Safe mode” toggle that prevents destructive choices (clipping, hard gate
      overrides) while still allowing creative exploration.
- [ ] Reference matcher view (delta-to-reference) and a per-bus/track priority
      list that can guide recommendation ranking.
- [ ] A/B/C/D morphing control (or equivalent) for blending between multiple
      states.
- [ ] Optional history scrub/timeline view for stepping through previous states
      (can be implemented as an enhanced undo stack).
- [ ] Optional soundstage + masking views (2D bubble map + conflict highlights)
      for non-technical spatial understanding.
- [ ] Layout router/splitter stage that can split/assign/recombine stems based
      on channel semantics and roles (useful for complex multichannel stems).
- [ ] Support for very large “many-channel” layouts (example: 9.1.6, 9.4.6) as
      long as they fit within `max_channels`, with clear layout negotiation
      rules.
- [ ] Additional export targets and packaging (listen packs, audition bundles,
      multiple preset variants) with cached analysis reuse.
