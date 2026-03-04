# GEMINI: Repo context preamble (MMO)

You are working in the Mix Marriage Offline (MMO) repository.

Read these first (source of truth):
1) PROJECT_WHEN_COMPLETE.md (finish line and Definition of Done)
2) AGENTS.md (repo workflow, commands, constraints)
3) docs/ (architecture + contracts)
4) ontology/ and schemas/ (canonical IDs and strict validation)

Non-negotiables:
- Offline-first, deterministic behavior, explainability, bounded authority.
- Objective Core contracts cannot be broken by plugins.
- Layout safety and downmix QA gates must be preserved.
- Keep GUI dashboard rendering deterministic (frame + surface snapshot signatures).
- Route runtime progress/cancel/live-log wiring through `mmo.core.progress`
  and keep ETA/runtime diagnostics out of deterministic persisted artifacts.
- Keep `fixtures/public_session/report.7_1_4.json` and
  `tests/test_full_determinism.py` in sync for full-pipeline byte-stability checks.
- Keep watch-folder automation deterministic: debounce event bursts, detect
  changed stem sets by signature, and launch install-safe `python -m mmo run`
  render-many batches.
- Keep watch-folder visual queue telemetry deterministic (stable ordering,
  explicit state transitions, and install-safe CLI wiring).
- Keep safe-render baseline mixdown deterministic: supported
  2.0/5.1/7.1/7.1.4/9.1.6 targets must still emit conservative WAV masters
  when recommendations are not render-eligible.
- Keep scene-driven placement mixdown deterministic when enabled: one
  layout-agnostic scene should render conservative
  2.0/5.1/7.1/7.1.4/7.1.6/9.1.6 outputs with front-only object routing and
  subtle confidence-gated/capped bed surround-height sends.
- Preserve stereo imaging in placement render paths: stereo stems should not
  collapse to mono in `LAYOUT.2_0`, scene stereo hints (`width_hint`,
  `azimuth_hint`) must remain evidence-backed/deterministic, and any optional
  side wrap beyond L/R must stay confidence-gated and perspective-gated.
- Keep render-many surround similarity gating deterministic: compare stereo
  renders against downmix(rendered surround/immersive), and if gates fail,
  allow only a single bounded backoff retry (surround/height/wide channels)
  before final pass/fail logging.
- Keep safe-render zero-output behavior fail-safe: emit
  `ISSUE.RENDER.NO_OUTPUTS` and return non-zero by default unless
  `--allow-empty-outputs` is explicitly set.
- Keep offline plugin marketplace discovery install-safe via bundled
  `ontology/plugin_index.yaml` and deterministic CLI/GUI listing paths.
- Keep offline plugin hub installs deterministic and install-safe by sourcing
  plugin assets from packaged data (no repo-root assumptions) and writing
  stable manifest/module outputs in one-click install flows.
- Keep stems artifact progression deterministic: `stems_map` (role identity)
  and `bus_plan` (bus-path identity) must preserve stable sorting and
  schema-valid contracts across repeated runs.
- Keep `fixtures/stems_small/` regression fixtures aligned with
  `fixtures/expected_bus_plan.json`, `fixtures/expected_scene.json`, and
  `tests/test_stems_small_regression.py` hash expectations.
- Keep scene intent scaffolding deterministic when built from stems artifacts:
  `mmo scene build --map ... --bus ...` must emit stable object-vs-bed
  classification with conservative low-confidence fallback behavior.
- Keep scene-build locks deterministic and precedence-safe:
  `mmo scene build --locks ...` must apply per-stem overrides with
  `locks > explicit metadata > inference`, including role/bus/placement
  (`azimuth_deg`/`width`/`depth`) and surround/height send caps, and emit
  stable locked-vs-inferred provenance receipts in scene metadata.
- Keep dual-LFE (x.2) export contracts explicit: preserve canonical SPK channel
  order in render/recall artifacts, use conservative WAV mask strategy, and
  surface validation guidance for toolchains that may drop `LFE2`.
- Keep missing-LFE behavior deterministic and policy-driven: passthrough when
  source LFE exists, derive from low-passed LR when absent, run the documented
  phase-max check, and emit structured LFE receipts in plan/report artifacts.
- Keep export metadata round-trip deterministic: apply explicit ffmpeg metadata
  args by container policy and always emit `metadata_receipt` embedded/skipped
  key summaries in render/export artifacts.
