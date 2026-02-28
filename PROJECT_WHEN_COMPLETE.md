# Project When Complete: Mix Marriage Offline (MMO)

## 0) One-sentence goal
An open-source, offline, DAW-agnostic stem-folder mixing assistant that captures mix intent as a layout-agnostic scene, then deterministically renders to multiple speaker layouts with strict downmix QA and explainable reports.

## 1) Target users
- Mixing engineers who want fast, repeatable “mix-once, render-many” delivery.
- Hobbyists who want safe, explainable help without black-box automation.
- Tool builders who want a stable Objective Core and a flexible plugin ecosystem.

## 2) Core promises (must stay true)
- Offline-first. No network required for core functionality.
- Deterministic outputs: same inputs + settings → same results (including seeded decorrelation).
- Explainable: every issue and action includes what/why/where/confidence (+ evidence).
- Bounded authority: auto-apply only low-risk actions inside limits. Escalate high-impact moves.
- Ontology-first: canonical IDs for roles, issues, actions, params, units, evidence, layouts, downmix policies.
- Layout safety: every render must pass translation gates and downmix similarity checks (at least to stereo).

## 3) Inputs and outputs (contract)
Inputs:
- A “stem folder” (or structured project folder) containing audio files + optional metadata.
- Optional user config/profile specifying intent, vibe, and safety limits.

Outputs:
- A validated, layout-agnostic scene file (mix intent) in JSON.
- A human-readable report + recall sheet describing decisions and QA results.
- Rendered outputs for target layouts (optional, conservative by default).
- A machine-readable render report (JSON) including gate results and evidence.

## 4) Definition of Done (checklist)
The project is “complete enough” when all items below are true.

### 4.1 Docs are complete and accurate
Note: numbered docs (`docs/00-*` through `docs/20-*`) are canonical; this checklist references those files directly.
- [x] docs/00-proposal.md exists and matches the implemented scope.
- [x] docs/01-philosophy.md documents Objective Core vs Subjective Plugins and bounded authority.
- [x] docs/02-architecture.md maps modules to repo paths and data flow.
- [x] docs/SCENE_AND_RENDER_CONTRACT_OVERVIEW.md defines objects vs bed/field, confidence, locks, and routing intent.
- [x] docs/SCENE_AND_RENDER_CONTRACT_OVERVIEW.md defines canonical channel sets, orders, speaker metadata, and downmix rules.
- [x] docs/04-plugin-api.md + docs/13-plugin-authoring.md define plugin contracts (channel_mode, link groups, latency, determinism seeds).
- [x] docs/05-fixtures-and-ci.md documents fixtures, CI gates, and determinism expectations.
- [x] docs/07-export-guides.md documents how users should export stems for best results.
- [ ] docs/06-roadmap.md clearly separates “now” vs “later.”
What remains: split roadmap sections into explicit near-term vs later tracks and align them with `docs/STATUS.md` + `docs/milestones.yaml`.

### 4.2 Ontology is stable and versioned
- [x] ontology/*.yaml covers roles, features, issues, actions, params, units, evidence.
- [x] ontology/layouts.yaml defines all supported layouts + canonical channel naming and order.
- [x] ontology/downmix.yaml defines explicit, versioned downmix matrices/policies.
- [x] ontology/gates.yaml defines QA thresholds and fallback behaviors.
- [ ] Ontology changes are additive unless a version bump is made and migration notes exist.
What remains: add enforced ontology versioning/deprecation policy with CI checks for migration-note requirements.

### 4.3 Schemas are complete and enforced
Note: schema contracts use `schemas/*.schema.json` naming (not `schemas/*.json`).
- [x] schemas/project.schema.json validates project input structure.
- [x] schemas/scene.schema.json validates layout-agnostic intent.
- [x] schemas/render_request.schema.json defines render targets and options.
- [x] schemas/render_report.schema.json defines QA + evidence output.
- [x] schemas/report.schema.json defines human-readable report payload shape.
- [x] schemas/plugin.schema.json defines plugin capabilities and semantics.
- [x] Source metadata tag preservation model is implemented (`source_metadata.technical` + canonical `TagBag` with `raw`/`normalized`/`warnings`).
- [x] Every schema is strict (`additionalProperties: false`) where appropriate.
- [x] CLI and core reject invalid inputs with clear, actionable errors.

### 4.4 Objective Core is implemented and tested
- [x] Validators: folder/session validation, channel semantics checks, layout negotiation (including FFmpeg layout alias handling).
- [x] Determinism: seeded operations are reproducible across platforms (document any numeric tolerances).
- [x] Meters: loudness, peaks/true-peak, crest factor, correlation/phase-risk, headroom, plus LFE-specific validation and metering.
- [x] Safety gates: hard failures and “fallback to safer routing” behavior are implemented.
- [x] Downmix QA: renders pass similarity gates to stereo (and optional additional downmix targets).
- [x] “Do no harm” defaults exist and are used when confidence is low.

#### 4.4.5 Five channel-ordering standards support (boundary convert + internal SMPTE)
- [x] `ontology/layouts.yaml` has explicit `ordering_variants` for the 5 supported standards where applicable: SMPTE, FILM, LOGIC_PRO, VST3, AAF.
- [x] `layout_negotiation.get_channel_order(layout_id, standard)` returns the correct order for SMPTE (default), FILM, LOGIC_PRO, VST3, and AAF (with canonical fallback when a layout has no explicit variant).
- [x] `layout_negotiation.reorder_channels(data, from_order, to_order)` works on list, tuple, and NumPy arrays.
- [x] `render_contract.build_render_contract()` accepts `layout_standard` (default SMPTE) and records it in the contract.
- [x] `render_engine.render_scene_to_targets()` reads `layout_standard` from options and emits explainability notes.
- [x] `safe-render` CLI accepts `--layout-standard SMPTE|FILM|LOGIC_PRO|VST3|AAF` (default SMPTE).
- [x] `render-many` threads `layout_standard` through all per-target runs.
- [x] All render receipts and job notes include the active layout standard and order-selection notes.
- [x] Regression fixtures in `tests/test_dual_layout_ordering.py` pin exact orderings for 5.1 and 7.1.4 SMPTE and FILM.
- [x] End-to-end roundtrip regression matrix in `tests/test_layout_standard_roundtrips.py` verifies source->SMPTE->target routing for all valid multichannel `LAYOUT.*` entries across SMPTE/FILM/LOGIC_PRO/VST3/AAF.
- [x] `schemas/run_config.schema.json` `render.layout_standard` field present with enum `[“SMPTE”, “FILM”, “LOGIC_PRO”, “VST3”, “AAF”]`.
- [x] `schemas/render_report.schema.json` `render_job.layout_standard` field present.
- [x] `schemas/plugin.schema.json` `capabilities.supported_standards` and `capabilities.preferred_standard` fields present.
- [x] Every downmix matrix and QA gate is order-aware (uses channel IDs, not fixed indices).
- [ ] Plugin channel routing uses `ProcessContext.channel_order` (list of `SPK.*` IDs) instead of hard-coded indices.

#### 4.4.1 Loudness and layout mapping (meter contract)
- [x] Program loudness uses ITU-R BS.1770-5 weighting with explicit, tested channel mapping.
- [x] LFE is excluded from program loudness (weight 0.0) and is always reported separately.
- [x] Common layout naming conventions are mapped correctly, including FFmpeg-style aliases:
  - 5.1 (back surrounds: BL/BR).
  - 5.1(side) (side surrounds: SL/SR).
- [x] Layout inference treats BL/BR vs SL/SR differently for routing/semantics, while using the same BS.1770 surround weighting rules for loudness.

#### 4.4.2 LFE validation and musician-friendly guidance
- [x] Supports 1+ LFE channels (x.1, x.2, …) with per-LFE and summed reporting.
- [x] Provides an LFE “content audit” that reports:
  - band-limited level/energy (configurable band, default 20–120 Hz),
  - crest/headroom and true-peak,
  - relative LFE-to-mains low-band energy ratio (profile-driven guidance, not a hard rule).
- [x] Detects out-of-band LFE content and flags it with evidence:
  - significant energy above the configured low-pass cutoff (default 120 Hz),
  - problematic infrasonic rumble below the configured high-pass cutoff (default 20 Hz).
- [ ] If a corrective filter is recommended, the system must:
  - explain what/why in musician language,
  - require explicit approval before applying,
  - re-run downmix/mono compatibility checks after the change,
  - back off (or refuse) if fold-down similarity or phase-risk gates get worse.
- [ ] If the user supplies explicit LFE stems, the system must not silently “fix” tone by moving content to mains; it may only recommend options (LPF/HPF, split-and-route, or leave as-is) with confidence and tradeoffs.
What remains: wire corrective-filter recommendations into an approval + re-QA/backoff loop and harden explicit-LFE no-silent-fix behavior with dedicated integration fixtures.


### 4.5 Subjective Plugins system exists (without breaking core contracts)
- [x] Plugin interface supports max_channels ≥ 32 and declares channel_mode + link groups.
- [x] Plugins report latency (fixed/dynamic) and host delay-comp policy.
- [ ] Plugins may suggest actions with confidence, but cannot override explicit user intent.
- [x] High-impact moves require explicit approval in the workflow contract.
- [x] Installed package plugin loading does not rely on repo-root imports; bundled
  manifests under `mmo.data/plugins` are discovered from any working directory.
What remains: tighten user-intent/lock precedence guarantees across all resolver/plugin paths with explicit regression coverage.

### 4.6 Rendering targets are supported (minimum viable set)
- [x] Stereo (2.0) render contract is correct and validated.
- [x] Binaural headphone deliverable is supported as a first-class target
  (`TARGET.HEADPHONES.BINAURAL` / `LAYOUT.BINAURAL`) using deterministic
  conservative virtualization with source-layout traceability.
- [ ] 2.1 and 4.1 layouts are correctly supported when requested (render + meters + downmix QA).
- [x] 5.1 render contract is correct and validated (including 5.1 vs 5.1(side) semantic differences).
- [x] 7.1 render contract is correct and validated.
- [x] One immersive bed target (example: 7.1.4) is correct and validated.
- [x] LFE policy is explicit: treated as a creative send plus bass management rules.
- [x] Multi-LFE layouts (example: 5.2, 7.2.4) are supported as first-class layouts when declared, with canonical naming/order (LFE1, LFE2, …).
- [x] “.2” is not assumed as dual-LFE program content unless explicitly required by target spec.
- [x] WAV channel-mask disambiguation for dual-LFE ingest/export is implemented with a conservative export contract: direct-out mask strategy (`mask=0`) plus explicit canonical SPK channel order in render-report/recall context.
- [x] Dual-LFE export caveat is documented and emitted at runtime: some external tools still collapse/relabel `LFE2`; users must validate with render-report channel order + ffprobe layout output.
- [x] All render targets support both SMPTE (default) and Film channel ordering; the active standard is recorded in every render contract and receipt.
- [x] Regression tests verify deterministic channel-order roundtrips across SMPTE/FILM/LOGIC_PRO/VST3/AAF for all valid multichannel `LAYOUT.*` entries.
What remains: add first-class 2.1/4.1 targets.


### 4.7 Fixtures and CI prevent regressions
- [ ] Fixture sessions exist for stereo, 5.1, 7.1, and one immersive target.
- [ ] Fixture for “stereo stems with baked pan/width” validates inference is advisory and confidence-gated.
- [x] Determinism tests exist (byte-stable or numerically stable within documented tolerance).
- [x] Downmix similarity tests exist and fail CI when gates regress.
- [x] CI runs on Windows, Linux, macOS (or documents any limitations).
What remains: expand fixture corpus with dedicated 5.1/7.1 session sets and an explicit baked-pan confidence-gating case.

### 4.8 UX/CLI is usable for real work
- [x] CLI can: validate, analyze, generate scene, render, and output reports.
- [x] Target selection is interchangeable across CLI/GUI flows: `TARGET.*`,
  `LAYOUT.*`, and musician shorthands (`stereo`, `5.1`, `7.1`, `7.1.4`,
  `binaural`);
  ambiguous tokens fail deterministically with sorted candidates.
- [x] Errors are actionable (tell the user what/why/where/how to fix).
- [x] Reports include: issues, actions taken, actions suggested, confidence, and evidence references.
- [x] A “dry-run” mode exists for suggestions without applying changes.
- [x] `safe-render` supports live explainable progress logging (`what/why/where/confidence`)
  and cooperative cancellation (`--cancel-file`) for CLI/GUI runs.
- [x] `safe-render` supports deterministic headphone preview rendering via
  `--preview-headphones`, writing explainable binaural preview outputs that
  reference their source render artifacts.
- [x] `mmo watch <folder>` supports smart batch processing for incoming stems by
  debouncing filesystem events and auto-running deterministic `--render-many`
  workflows on changed stem sets.
- [x] `mmo watch <folder>` can emit deterministic visual batch-queue snapshots with
  cinematic progress states (`--visual-queue --cinematic-progress`) for operator
  monitoring without changing render decisions.
- [x] Offline plugin marketplace discovery is available via bundled ontology index,
  CLI (`mmo plugin list/update`), and GUI browser surfaces.
- [x] Desktop GUI includes an artistic `Discover` marketplace tab with preview
  cards and deterministic one-click offline plugin install flow.
- [ ] Preview/A-B audition is loudness-compensated by default (auto-gain for evaluation), and the report discloses the compensation used.
- [ ] Presets (example: EQ vibe presets) can be initialized from measured stem features, and preset preview does not create surprise loudness jumps.
- [x] A “variant runner” can render multiple output variants (profiles/presets/targets) while reusing cached analysis artifacts keyed by content hash.
- [x] Project session JSON persistence exists for `scene + history + receipts` via `mmo project save/load`, with deterministic JSON output and strict schema validation.
What remains: make loudness-matched A/B compensation visible in report artifacts and add preset-preview loudness-jump guards for all shipped preset packs.

### 4.8.1 GUI is ergonomically safe and AI-readable (a work of art in itself, so creatives and nerds alike love it. Strong typography, cinematic color contrast, and intentional spacing/visual hierarchy so it feels crafted, not utilitarian, while still staying cross-platform and deterministic)
- [x] Minimal desktop CustomTkinter shell exists for stems drop, target/layout selection,
  live logs, and bounded-authority approval flow before final safe-render.
- [x] Visualization Dashboard v1.1 exists as the primary GUI surface with deterministic
  spectrum/vectorscope/correlation visuals, cinematic 3D speaker/object views, and
  explainable per-object intent cards (`what/why/where/confidence`).
- [x] GUI includes a bounded-authority `Preview on Headphones` action that
  forwards to `safe-render --preview-headphones` and writes deterministic
  binaural audition files.
- [x] Web GUI Audition panel includes deterministic headphone preview visuals:
  pulsing waveform display and warm analog L/R metering driven by live playback.
- [ ] A GUI exists (local web app is fine) that exposes the same workflow as the CLI: validate → analyze → scene → render → results → compare.
- [ ] GUI copy and structure follow the design system in ontology/gui_design.yaml (theme tokens, screen templates, and progressive disclosure).
- [x] Any plugin/config UI is generated from JSON Schema with optional UI hints (example: x_mmo_ui or a dedicated ui_hints registry) so agents do not hand-build one-off forms.
What remains: finish full CLI parity across GUI screens and enforce design-system conformance at screen composition level, not only ontology/schema level.

Interaction standards (non-negotiable):
- [ ] Every numeric control supports direct text entry (exact value).
- [ ] Every drag control supports a fine-adjust modifier (Shift/Ctrl is fine) with visible on-screen feedback while engaged.
- [ ] Units are always visible (Hz, dB, ms, LUFS, degrees, samples) and rounding/display rules are consistent.
- [ ] A/B compare is loudness-compensated by default so “louder is better” bias is reduced (compare-to-silence style behavior).

Reusable component library (minimum set for v1 GUI parity):
- [ ] Controls: knob/rotary, fader/slider, toggle/button, segmented selector, XY pad, preset browser with search/tags, A/B toggle, value readout.
- [ ] Metering: peak/RMS, true-peak, LUFS, multi-channel meters (surround/immersive energy distribution).
- [ ] Visualizers (offline-rendered is acceptable): waveform (pre/post overlay), spectrum (FFT), optional spectrogram, EQ curve editor.
- [ ] Dynamics/spatial views (offline-rendered is acceptable): gain reduction meter, phase correlation, goniometer/vectorscope, optional transfer curve.
- [ ] Explainability: hint overlays (“what/why”), confidence indicator for recommendations, and a compact “what changed” summary.

Artist-first controls (optional, but should be supported as the GUI matures):
- [ ] Macro controls with semantic labels (example: Warmth, Air, Punch, Glue) that map to multiple parameters and always disclose what they change.
- [ ] Mood/texture selectors (tag chips or icons) that swap whole preset strategies without jargon.
- [ ] “Safe mode” toggle that prevents destructive choices (clipping, hard gate overrides) while still allowing creative exploration.
- [ ] Reference matcher view (delta-to-reference) and a per-bus/track priority list that can guide recommendation ranking.
- [ ] A/B/C/D morphing control (or equivalent) for blending between multiple states.
- [ ] Optional history scrub/timeline view for stepping through previous states (can be implemented as an enhanced undo stack).
- [ ] Optional soundstage + masking views (2D bubble map + conflict highlights) for non-technical spatial understanding.

AI-readable layout export + validation (prevents overlaps/off-screen UI):
- [x] The GUI can export a machine-readable layout manifest per screen/view that conforms to:
  - schemas/ui_layout.schema.json (authored contract), and
  - schemas/ui_layout_snapshot.schema.json (resolved snapshot with pixel boxes and violations).
  The layout snapshot must include:
  - viewport size,
  - section and widget ids,
  - per-widget param_ref (when applicable),
  - bounding boxes (x_px, y_px, width_px, height_px),
  - per-widget minimum sizes.
- [ ] A layout validator runs in CI and fails on:
  - overlapping interactive hit targets,
  - controls rendered off-screen at supported breakpoints,
  - missing labels/units for numeric controls,
  - insufficient spacing versus the declared spacing tokens.
- [ ] A global GUI scale control exists (or responsive scaling equivalent) for laptop vs 4K displays.


## 4.9 DSP engine and plugin execution (Definition of Done)

The project is not considered complete until the DSP pipeline, plugin contracts, and render behavior below are implemented, documented, and covered by tests.
What remains: the core DSP path is functional, but formalized fallback sequencing, stricter plugin purity guarantees, and full export-policy documentation still need to be locked and tested end-to-end.

### 4.9.1 DSP core guarantees
- [x] Internal processing uses a documented floating-point format (default: 64-bit float).
- [ ] Export finalization has a documented, deterministic policy (per target format/bit depth):
  - none (when exporting float),
  - TPDF (and optional high-pass TPDF),
  - optional noise shaping.
  Experimental “no-noise” or ML-based approaches are allowed only as explicitly selected plugins, never as a silent default.
- [x] All DSP is offline-render capable (no realtime assumptions).
- [ ] Sample rate handling is explicit:
  - [ ] Either a single project sample rate is enforced, or resampling is done with a declared algorithm and deterministic settings.
- [ ] Channel counts up to at least 32 are supported end-to-end.
- [x] Plugin order is deterministic and serialized in reports.
- [ ] Every processing decision that can affect tone/balance/spatialization is either:
  - (a) explicitly requested by the user intent, or
  - (b) recommended with confidence and requires approval if high-impact, or
  - (c) skipped when confidence is low.


### 4.9.2 Canonical DSP stages (pipeline shape)
- [ ] The engine implements a stable, documented stage graph (minimum):
  1) Input normalization and alignment (optional, conservative).
  2) Analysis/metering pass (no audio mutation).
  3) Scene inference pass (advisory only, writes intent with confidence).
  4) Pre-render corrective pass (low-risk only, bounded authority).
  5) Render pass (scene → target layout) with routing + downmix policy.
  6) Post-render QA pass (gates, downmix similarity, correlation/phase-risk).
  7) Export pass (format, dither policy, loudness/true-peak constraints).
- [ ] Each stage emits evidence and timing into the render report.

### 4.9.3 Plugin API: audio processing contract
- [x] A plugin manifest declares:
  - name/id/version
  - max_channels
  - channel_mode: per-channel | linked-group | true-multichannel
  - supported link groups (front, surrounds, heights, all, custom)
  - latency: fixed or dynamic (and exact reporting method)
  - deterministic_seed_usage: yes/no + seed inputs
  - requirements: needs speaker positions? bed-only? objects-capable?
- [x] Renderer manifests include digital-first DSP traits (`capabilities.dsp_traits`)
  with explicit `tier` + `linearity`.
- [x] Nonlinear renderer manifests declare anti-aliasing strategy (not `none`).
- [x] Renderer manifests include measurable truth contracts via
  `capabilities.dsp_traits.measurable_claims`.
- [ ] Plugins operate on typed buffers with explicit channel semantics (not “raw arrays”).
- [ ] Plugins must be pure with respect to determinism:
  - [ ] No internal randomness unless seeded from the provided seed.
  - [ ] No wall-clock/time-based behavior.
  - [ ] No dependency on host thread scheduling for results.

### 4.9.4 Bounded authority for DSP (what plugins may change)
- [x] Plugins are classified by impact level:
  - Low-risk: metering, analysis, small safety-limited trims, de-click, DC removal.
  - Medium: gentle EQ/dynamics within strict ranges.
  - High: tone reshaping, balance changes, spatial placement changes, aggressive dynamics, destructive edits.
- [x] Only low-risk changes may be auto-applied, and only within user-defined limits.
- [ ] Medium/high changes must be output as recommendations with:
  - what/why/where/confidence
  - the exact parameter deltas proposed
  - rollback notes (how to undo)
- [ ] Any change to object vs bed classification or spatial routing is treated as high-impact unless explicitly user-locked.

### 4.9.5 Multichannel and layout safety rules (DSP-level)
- [ ] Plugins must declare whether they are:
  - bed-only
  - object-capable
  - layout-agnostic (works pre-render)
  - layout-specific (works post-render)
- [ ] If a plugin cannot guarantee safe multichannel behavior, the engine must:
  - [ ] restrict it to safe channel groups, or
  - [ ] bypass it, and log a warning with evidence.

### 4.9.6 Downmix QA and fallback behaviors (DSP-level)
- [x] Render outputs must pass downmix similarity gates (minimum: stereo).
- [ ] If a gate fails, the system applies a documented fallback strategy:
  - reduce surround/height aggressiveness
  - reduce decorrelation
  - collapse risky wideners
  - move ambiguous energy forward
  - re-run render + QA until pass or stop with an explainable failure report
- [ ] Failures are never silent. Reports must show the failing metrics and the fallback actions attempted.

### 4.9.7 Formats, export, and reproducibility
- [x] Export formats are explicit and deterministic:
  - WAV/BWF at minimum.
  - Optional: FLAC and/or WavPack (deterministic encoder settings).
  - Optional: Wave64 for very large multichannel outputs.
- [x] Export metadata round-trip is best-effort and explainable:
  - FLAC/WavPack outputs re-embed normalized + raw tag fields deterministically.
  - WAV outputs embed conservative INFO subsets and emit skipped-key receipts.
  - `render_report`/deliverables file rows carry `metadata_receipt` entries.
- [ ] Rendered files embed enough metadata for traceability:
  - tool version, scene hash, render contract version, downmix policy version.
- [ ] Golden fixtures prove:
  - determinism across OS targets (within documented tolerance),
  - consistent gating outcomes,
  - identical channel ordering and naming per contract.


### 4.9.8 Tests required for “complete”
- [x] Unit tests for plugin manifest validation and stage ordering determinism.
- [ ] Golden-audio tests for at least:
  - one per-channel plugin
  - one linked-group plugin
  - one true-multichannel plugin
- [ ] A regression test that proves a failed downmix gate triggers the correct fallback sequence.

## 5) Non-goals (explicitly out of scope for “complete”)
- DAW plugin hosting (VST/AU/AAX).
- Black-box ML that overrides gates or explicit user intent.
- Claims of reconstructing true object metadata from a stereo bounce.
- Guaranteed literal front-back placement from stereo cues (treat depth as directness/diffuseness proxies).

## 6) Milestones (suggested order)
1) Docs + ontology + schemas (contracts first).
2) Validators + meters + gates (Objective Core).
3) Scene generation + reporting.
4) Rendering targets + downmix QA.
5) Plugin system + conservative detectors/resolvers.
6) Fixtures + CI hardening + cross-platform polish.

## 7) Update policy (prevents “context rot”)
- Any PR that changes behavior must update:
  - the relevant doc section,
  - the schema (if shape changed),
  - and at least one test/fixture.
- If docs and code disagree, code is “wrong” until docs are updated or scope is revised.

## 8) Source of truth pointers
- Primary contracts: docs/ + ontology/ + schemas/
- Process rules for AI tools: AGENTS.md


## 9) Optional capabilities (nice-to-have, not required for v1 completion)
- Layout router/splitter stage that can split/assign/recombine stems based on channel semantics and roles (useful for complex multichannel stems).
- Support for very large “many-channel” layouts (example: 9.1.6, 9.4.6) as long as they fit within max_channels, with clear layout negotiation rules.
- Additional export targets and packaging (listen packs, audition bundles, multiple preset variants) with cached analysis reuse.
