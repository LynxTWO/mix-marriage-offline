# GEMINI: Repo context preamble (MMO)

<!-- markdownlint-disable-file MD013 -->

You are working in the Mix Marriage Offline (MMO) repository.

Read these first (source of truth):

1. PROJECT_WHEN_COMPLETE.md (finish line and Definition of Done)
2. AGENTS.md (repo workflow, commands, constraints)
3. docs/ (architecture + contracts)
4. ontology/ and schemas/ (canonical IDs and strict validation)

Non-negotiables:

- Offline-first, deterministic behavior, explainability, bounded authority.
- Keep medium/high recommendation contracts explicit: recommendation payloads
  and safe-render receipts must disclose exact deltas, scope, and rollback
  steps, and those recommendations must not become render-eligible unless the
  user explicitly approves the concrete `recommendation_id`.
- Objective Core contracts cannot be broken by plugins.
- Layout safety and downmix QA gates must be preserved.
- Keep DSP execution routed by ontology-backed `ProcessContext.channel_order`
  and semantic `SPK.*` IDs; do not reintroduce hard-coded slot assumptions or
  partial preset layout maps.
- Keep `src/mmo/dsp/plugin_mode_runner.py`, `tests/plugins/`, and
  `tests/test_plugin_modes_golden.py` aligned so manifest-declared
  `per_channel`, `linked_group`, and `true_multichannel` semantics stay pinned
  by deterministic 5.1 / 7.1.4 regression coverage.
- Keep chunk-level renderer and plugin-boundary audio transport on
  `mmo.dsp.buffer.AudioBufferF64` so interleaved data keeps explicit
  `channel_order` and `sample_rate_hz` metadata instead of reverting to raw list
  math at conversion boundaries.
- Keep runtime determinism purity enforcement active at plugin boundaries:
  reject unseeded RNG, wall-clock/timer access, and thread/executor spawning,
  and keep any approved randomness derived explicitly from `process_ctx.seed`.
- Keep float64 -> PCM export finalization centralized in
  `mmo.dsp.export_finalize`; renderer WAV paths must disclose deterministic
  bit-depth / dither policy via `export_finalization_receipt` instead of
  reintroducing per-renderer quantize/dither code.
- Keep GUI dashboard rendering deterministic (frame + surface snapshot
  signatures).
- Keep explicit Tauri manual screenshot capture deterministic and canonical:
  the opt-in capture flow should emit the named canonical states documented in
  `docs/manual/assets/screenshots/README.md`: `tauri_session_ready`,
  `tauri_session_loaded_compact`, `tauri_scene_loaded`,
  `tauri_scene_locks_editor`, `tauri_results_loaded`, and
  `tauri_compare_loaded` from fixture-backed UI actions rather than
  hand-curated images; committed PNGs should use the documented fixed-region
  `1280 x 900` CSS-pixel capture contract (not unstable full-page document
  renders), and native OS dialogs should remain text-only instead of entering
  the committed baseline set.
- Route runtime progress/cancel/live-log wiring through `mmo.core.progress` and
  keep ETA/runtime diagnostics out of deterministic persisted artifacts.
  `render_report.stage_metrics` / `stage_evidence` must stay deterministic; use
  opt-in `wall_clock` only when a caller explicitly requests non-deterministic
  elapsed-time diagnostics.
- Keep `fixtures/public_session/report.7_1_4.json` and
  `tests/test_full_determinism.py` in sync for full-pipeline byte-stability
  checks.
- Keep `fixtures/golden/` and `tests/test_golden_fixtures.py` in sync for the
  cross-OS classify->bus-plan->scene->safe-render tripwire: exact scene/bus
  snapshots, exact normalized manifest/receipt hashes, exact channel ordering,
  exact QA issue IDs/severities, and tolerance-based per-channel audio metrics.
- Keep watch-folder automation deterministic: debounce event bursts, detect
  changed stem sets by signature, and launch install-safe `python -m mmo run`
  render-many batches.
- Keep watch-folder visual queue telemetry deterministic (stable ordering,
  explicit state transitions, and install-safe CLI wiring).
- Keep safe-render baseline mixdown deterministic: supported
  2.0/5.1/7.1/7.1.4/9.1.6 targets must still emit conservative WAV masters when
  recommendations are not render-eligible.
- Keep safe-render explicit scene workflows first-class and deterministic:
  `--scene` must take precedence over hidden scene rebuilds, optional
  `--scene-locks` must apply before placement policy and be re-applied before
  authority/eligibility checks, and receipt artifacts must preserve canonical
  scene/lock source provenance.
- Keep renderer safety classes explicit and enforced: manifests with capability
  objects must declare `scene_scope` and `layout_safety`, and the render
  pipeline must either restrict plugins to a provably safe subset or bypass
  them with explainable skipped receipt rows instead of guessing.
- Keep scene-aware safe-render export artifacts deterministic and explainable:
  `--export-stems`, `--export-buses`, `--export-master/--no-export-master`, and
  `--export-layouts` must emit stable file paths + SHA-256 hashes in render
  manifest/receipt outputs and preserve stem->subbus->main-bus->scene mapping
  context for recall CSV generation.
- Keep scene-driven placement mixdown deterministic when enabled: one
  layout-agnostic scene should render conservative 2.0/5.1/7.1/7.1.4/7.1.6/9.1.6
  outputs with role/azimuth-driven object stage routing (perspective-gated
  side/rear/wide use) and subtle confidence-gated/capped hall-room-first bed
  surround-height sends.
- Keep placement mixdown memory bounded for long sessions by using deterministic
  two-pass streaming (fixed-size chunk peak scan, then trimmed PCM24 chunk
  writes) instead of whole-program in-memory accumulation.
- Keep optional immersive bed decorrelation deterministic and QA-bounded: seeded
  decorrelated bed widening may run only for qualified bed content, and if
  rendered surround similarity fails after one bounded backoff retry, the
  renderer must auto-disable and rerender without that plugin stage.
- Preserve explicit `session.render_export_options` extras through `safe-render`
  CLI normalization so renderer-scoped deterministic options (for example
  decorrelated bed widening) are not silently dropped when export toggles are
  applied.
- Keep placement and baseline mixdown ingest multiformat-lossless-safe: decode
  `wav`/`flac`/`wv`/`aiff`/`aif`/`ape` through the shared decoder abstraction
  and apply deterministic family-aware sample-rate policy/resampling with
  explainable receipts and per-job `render_report` disclosure instead of
  silently skipping mismatched stems.
- Preserve stereo imaging in placement render paths: stereo stems should not
  collapse to mono in `LAYOUT.2_0`, scene stereo hints (`width_hint`,
  `azimuth_hint`) must remain evidence-backed/deterministic, and any optional
  side wrap beyond L/R must stay confidence-gated and perspective-gated.
- Keep render-many surround similarity gating deterministic: compare stereo
  renders against downmix(rendered surround/immersive), and if gates fail, allow
  only a single bounded backoff retry (surround/height/wide channels) before
  final pass/fail logging.
- Keep default safe-render fallback back-compatible and user-helpful: exhausted
  surround similarity fallback must preserve written artifacts, receipts, QA
  reports, and preview outputs when they already exist, and the failure must
  remain explicit in receipt/QA metadata instead of escalating to a non-zero
  exit unless a separate strict policy explicitly requires it.
- Keep safe-render zero-output behavior fail-safe: emit
  `ISSUE.RENDER.NO_OUTPUTS` and return non-zero by default unless
  `--allow-empty-outputs` is explicitly set.
- Keep offline plugin marketplace discovery install-safe via bundled
  `ontology/plugin_index.yaml` and deterministic CLI/GUI listing paths.
- Keep offline plugin hub installs deterministic and install-safe by sourcing
  plugin assets from packaged data (no repo-root assumptions) and writing stable
  manifest/module outputs in one-click install flows.
- Keep stems artifact progression deterministic: `stems_map` (role identity) and
  `bus_plan` (bus-path identity) must preserve stable sorting and schema-valid
  contracts across repeated runs.
- Keep role ontology + classifier coverage additive for uncommon/rare
  instruments (world strings/winds/brass/percussion/keys/guitars) and ensure
  those roles stay wired through template and placement routing with
  deterministic regression coverage.
- Keep `fixtures/stems_small/` regression fixtures aligned with
  `fixtures/expected_bus_plan.json`, `fixtures/expected_scene.json`, and
  `tests/test_stems_small_regression.py` hash expectations.
- Keep scene intent scaffolding deterministic when built from stems artifacts:
  `mmo scene build --map ... --bus ...` must emit stable object-vs-bed
  classification with conservative low-confidence fallback behavior.
- Keep scene-build locks deterministic and precedence-safe:
  `mmo scene build --locks ...` must apply per-stem overrides with one
  centralized precedence rule:
  `locks > explicit scene fields > explicit CLI flags > plugin/template suggestions > inference defaults`,
  including scene perspective plus role/bus/placement
  (`azimuth_deg`/`width`/`depth`) and surround/height send caps, and emit stable
  `locked|explicit|suggested|inferred` provenance receipts in scene metadata.
- Keep GUI scene-lock editing deterministic and project-local:
  `scene.locks.inspect/save` should round-trip stable stem/object ordering,
  persist `scene_locks.yaml`, preserve non-UI override fields, and update
  `drafts/scene.draft.json` so corrected intent can be re-rendered immediately.
- Keep compare and preset-preview listening fairness explicit:
  `compare_report.json` must carry deterministic `loudness_match` metadata when
  sibling `render_qa.json` artifacts exist, the Tauri compare screen
  should default to that fair-listen compensation while disclosing method +
  amount, desktop preview/compare playback must stay artifact-backed with only
  bounded transport controls (`play/pause/stop` + A/B switch) and no extra
  real-time DSP beyond the disclosed compare gain, and any preset-preview
  compensation must stay bounded, explainable, and evaluation-only unless the
  user explicitly commits it.
- Keep Desktop GUI post-analyze scene preview deterministic and read-only:
  `_mmo_gui/scene.json` + `_mmo_gui/scene_lint.json` should be regenerated from
  `stems_map`/`bus_plan` with stable ordering, and the Scene tab should display
  perspective, object-vs-bed context, and warning-level lint issues without
  mutating scene artifacts.
- Keep the isolated Tauri desktop scaffold install-safe: `gui/desktop-tauri`
  should remain self-contained, Vite-based, and free of repo-root path
  assumptions.
- Treat Tauri as the desktop app path: parity requirements live in
  `docs/gui_parity.md`, and `mmo-gui` (CustomTkinter) is a deprecated legacy
  compatibility shell outside that parity contract.
- Keep the Tauri desktop app sidecar-driven and offline: stage the frozen `mmo`
  CLI via the repo's binary builder, bundle it through `externalBin`, avoid a
  production dependency on `gui/server.mjs`, and keep desktop workflow actions
  invoking the packaged sidecar directly via Tauri shell `execute`/`spawn` with
  bundled data/plugin path resolution.
- Keep the frozen CLI sidecar contract pinned to
  `src/mmo/_frozen_cli_entrypoint.py` plus `mmo.cli:main`; do not point
  packaged sidecar builds back at `src/mmo/__main__.py`, which exists to
  preserve legitimate `python -m mmo` behavior.
- Keep desktop Tauri CI building release binaries on Linux, macOS, and Windows:
  frontend lint/test steps should stay install-safe, and artifact uploads should
  come from `gui/desktop-tauri/src-tauri/target/release/`.
- Keep GitHub Actions JavaScript actions on Node 24-ready majors where upstream
  provides them; fix runtime deprecations by upgrading action versions, not by
  relying on insecure or temporary runner override env vars.
- Keep GUI/Tauri runtime expectations explicit and aligned across docs + CI: use
  Node 24 LTS for local/frontend work, pin GitHub-hosted runner images instead
  of relying on `*-latest`, and keep the Tauri Rust toolchain pinned rather than
  floating on the ambient `stable` channel.
- Keep the temporary
  `gui/desktop-tauri/src-tauri/vendor/glib-0.18.5` override documented and
  minimal: published Tauri Linux GTK crates still resolve
  `gtk 0.18.2 -> glib 0.18.5`, so keep only the security + current-Rust
  compile-clean backports there and remove the override once published
  dependencies move past `glib 0.18.5`. Do not fix future breakage by pinning
  older Rust or globally suppressing warnings.
- Keep scene QA lint deterministic and explainable: `mmo scene lint` must emit
  stable issue ordering/report payloads and cover missing stem IDs/refs/files,
  duplicate object/bus refs, placement range violations, lock-role/bus/layout
  conflicts (including per-stem bus lock conflicts), low-confidence critical
  anchors, and immersive-perspective bed/ambient + template-evidence warnings.
- Keep explicit-scene safe-render preflight lint-first: when `--scene` is
  provided, safe-render must run scene lint before render stages, and
  `--scene-strict` must fail fast on lint errors.
- Keep dual-LFE (x.2) export contracts explicit: preserve canonical SPK channel
  order in render/recall artifacts, use conservative WAV mask strategy, and
  surface validation guidance for toolchains that may drop `LFE2`.
- Keep missing-LFE behavior deterministic and policy-driven: passthrough when
  source LFE exists, derive from low-passed LR when absent, run the documented
  phase-max check, and emit structured LFE receipts in plan/report artifacts.
- Keep export metadata round-trip deterministic: apply explicit ffmpeg metadata
  args by container policy and always emit `metadata_receipt` embedded/skipped
  key summaries in render/export artifacts.
- Keep `render_report` schema back-compat centralized: every producer must
  populate the default `fallback_attempts` / `fallback_final` shape when richer
  fallback reporting is absent instead of weakening the schema.
- Keep true no-op plugin-chain WAV runs byte-stable: when every stage resolves
  to exact dry/bypass behavior and no conversion is required, preserve source
  WAV bytes while still emitting explainable report and event-log metadata.
