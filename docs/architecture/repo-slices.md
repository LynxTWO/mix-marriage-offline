# MMO Repo Slices

<!-- markdownlint-disable-file MD013 -->

Use this file to plan large-repo anti-dark-code passes without pretending the
whole repo was reviewed at once.

Order rule:

- highest-risk owned slices first
- generated, vendored, and asset-heavy areas get maps or manifests, not inline
  comment passes
- the long-term target is all applicable critical paths, not a fixed small
  subset

## 1. Backend render and authority paths already commented

- Slice name: `Backend render and authority paths already commented`
- Scope or repo paths: previously-commented parts of `src/mmo/core/`,
  `src/mmo/cli_commands/`, and `src/mmo/resources.py`
- Reason for the slice: this slice already covers the highest-risk backend
  trust boundaries around resource precedence, plugin authority, render stages,
  compare, project-session persistence, source resolution, and watch-folder
  behavior
- Risk class: critical
- Classification label: `owned-risky`
- Related runtime units or flows: CLI, project helpers, GUI RPC, validate ->
  analyze -> scene -> render -> compare, project save/load, plugin install,
  watch-folder automation
- Blockers: none currently recorded
- Exit criteria for this stage: architecture mapped, comment-only pass history
  present, and `docs/unknowns/critical-paths.md` still clear for these reviewed
  paths
- Next prompt to run: no immediate action; use a narrow follow-up audit only if
  behavior changes

## 2. Analysis and intake backend

- Slice name: `Analysis and intake backend`
- Scope or repo paths: remaining intake, detect, resolve, measure, policy, and
  report-shaping code in the uncovered parts of `src/mmo/core/`,
  `src/mmo/pipeline/`, and `src/mmo/meters/`
- Reason for the slice: this is the next darkest backend area and it determines
  how raw stems become stable report, routing, and planner facts
- Risk class: critical
- Classification label: `owned-risky`
- Related runtime units or flows: `scan`, `analyze`, `run`, stem discovery,
  report build, policy checks, routing inputs to later scene or render stages
- Blockers: none currently recorded
- Exit criteria for this stage: a map or comment pass explains the intake
  contract, trusted versus untrusted inputs, deterministic outputs, and key
  failure modes
- Next prompt to run: comment critical paths

## 3. DSP, render kernels, and exporters

- Slice name: `DSP, render kernels, and exporters`
- Scope or repo paths: `src/mmo/dsp/`, `src/mmo/exporters/`
- Reason for the slice: these modules own irreversible audio side effects,
  decode and render behavior, and exported evidence artifacts
- Risk class: critical
- Classification label: `owned-risky`
- Related runtime units or flows: render execution, downmix QA, export guides,
  report export, loudness and meter logic, `ffmpeg` and `ffprobe` driven paths
- Blockers: none currently recorded
- Exit criteria for this stage: trust boundaries, side effects, determinism,
  export contracts, and failure handling are documented well enough for safe
  review
- Next prompt to run: architecture map first if needed, then comment critical
  paths

## 4. Packaged contracts and registry authority

- Slice name: `Packaged contracts and registry authority`
- Scope or repo paths: `schemas/`, `ontology/`, `src/mmo/data/`
- Reason for the slice: these files define runtime meanings, contract IDs,
  packaged plugin bundles, and policy references
- Risk class: critical
- Classification label: `owned-risky`
- Related runtime units or flows: resource resolution, ontology validation,
  policy validation, plugin marketplace payloads, status and issue IDs
- Blockers: none currently recorded
- Exit criteria for this stage: contract ownership, mirroring, additive-change
  rules, and authority boundaries are documented without folklore
- Next prompt to run: architecture map or ontology-contract audit

## 5. Shared plugin contracts and authoring surfaces

- Slice name: `Shared plugin contracts and authoring surfaces`
- Scope or repo paths:
  `src/mmo/plugins/interfaces.py`,
  `src/mmo/plugins/runtime_contract.py`,
  `examples/plugin_authoring/`
- Reason for the slice: shared plugin interfaces, runtime guardrails, and
  authoring examples define how plugin code is expected to behave
- Risk class: high
- Classification label: `owned-risky`
- Related runtime units or flows: plugin contract ownership, plugin validation,
  authoring examples, and runtime guardrails for third-party or local plugin
  code
- Blockers: none currently recorded
- Exit criteria for this stage: shared interfaces, runtime guardrails, and
  authoring examples are explainable without guesswork
- Next prompt to run: no immediate action; revisit only if shared contracts or
  authoring guidance change

## 6. Bundled plugin implementations and packaged plugin data

- Slice name: `Bundled plugin implementations and packaged plugin data`
- Scope or repo paths: `plugins/`, `src/mmo/data/plugins/`,
  `src/mmo/plugins/`, `src/mmo/data/plugin_market/assets/plugins/`,
  `src/mmo/dsp/plugins/registry.py`, and `src/mmo/plugins/subjective/`
- Reason for the slice: bundled manifests, packaged fallback manifests,
  shipped implementation modules, offline market assets, and a subjective-pack
  bypass still shape render and UI behavior through a second path beyond the
  shared contracts already reviewed
- Risk class: high
- Classification label: `owned-risky`
- Related runtime units or flows: bundled renderer and resolver behavior,
  packaged fallback manifests, install-safe bundled fallback, offline market
  install assets, and subjective plugin behavior that bypasses the main loader
- Blockers: checkout examples, offline market parity, and the subjective-pack
  bypass still need explicit authority notes
- Exit criteria for this stage: bundled manifests, packaged fallback manifests,
  shipped plugin implementation behavior, market-install asset boundaries, and
  the subjective-pack exception are explainable without guesswork
- Next prompt to run: approval-aware comment pass or trust-boundary audit
  focused on plugin authority split, critical shipped renderers, approval-gated
  corrective plugins, and the subjective-pack bypass

## 7. Local dev shell and RPC bridge

- Slice name: `Local dev shell and RPC bridge`
- Scope or repo paths: `gui/server.mjs`, `gui/lib/`, `gui/web/`, `gui/tests/`
- Reason for the slice: this area combines local browser state, HTTP routing,
  RPC dispatch, CLI fallback launch, and artifact-read allowlists
- Risk class: high
- Classification label: `legacy-unclear`
- Related runtime units or flows: local dev shell, GUI RPC subprocess,
  `/api/rpc`, `/api/ui-bundle`, `/api/render-request`, `/api/render-artifact`,
  `/api/audio-stream`
- Blockers: no hard blockers, but current coverage is only entrypoint-deep
- Exit criteria for this stage: browser-side state, bridge ownership, trusted
  and untrusted inputs, and artifact-read boundaries are mapped clearly enough
  to support later comment or audit work
- Next prompt to run: frontend or bridge architecture map

## 8. Packaged desktop frontend

- Slice name: `Packaged desktop frontend`
- Scope or repo paths: `gui/desktop-tauri/src/`,
  `gui/desktop-tauri/layouts/`, `gui/desktop-tauri/tests/`
- Reason for the slice: this is the shipped GUI surface and it is only partly
  covered today
- Risk class: high
- Classification label: `legacy-unclear`
- Related runtime units or flows: packaged desktop screens, stage wiring,
  layout assets, screenshot tests, frontend-to-sidecar expectations
- Blockers: no hard blockers, but current coverage stops at manifests,
  documented entrypoints, and test presence
- Exit criteria for this stage: screen ownership, stage progression, layout
  asset role, and frontend assumptions about backend artifacts are documented
- Next prompt to run: architecture map

## 9. Desktop native shell and sidecar packaging

- Slice name: `Desktop native shell and sidecar packaging`
- Scope or repo paths: `gui/desktop-tauri/src-tauri/src/`, `Cargo.toml`,
  `tauri.conf.json`, packaged binary discovery, and desktop packaging scripts
- Reason for the slice: native command surfaces, sidecar packaging, and smoke
  hooks are high-risk and only partly mapped
- Risk class: high
- Classification label: `owned-risky`
- Related runtime units or flows: Tauri app launch, sidecar startup, packaged
  smoke, release bundles, desktop config handoff
- Blockers: no hard blockers, but native-shell details still need a dedicated
  map before comment work would be honest
- Exit criteria for this stage: native command surfaces, packaged binary
  discovery, smoke hooks, and release packaging assumptions are documented
- Next prompt to run: architecture map or trust-boundary audit

## 10. Validation, smoke, and release tooling

- Slice name: `Validation, smoke, and release tooling`
- Scope or repo paths: `tools/`, `Makefile`, `.github/workflows/`
- Reason for the slice: these paths define safe validation commands, smoke
  expectations, release packaging, and signing behavior
- Risk class: high
- Classification label: `owned-clear`
- Related runtime units or flows: contract validation, policy validation, repo
  pytest runners, packaged smoke, release artifact build, Pages deploy
- Blockers: none currently recorded
- Exit criteria for this stage: validation runners, smoke flows, release
  steps, and signing surfaces are mapped with no hidden operator assumptions
- Next prompt to run: ops or release audit

## 11. Evidence, fixtures, examples, and published outputs

- Slice name: `Evidence, fixtures, examples, and published outputs`
- Scope or repo paths: `tests/`, `fixtures/`, `examples/`, `benchmarks/`,
  `site/`
- Reason for the slice: these paths explain test evidence, examples, benchmark
  expectations, and the published site surface, but they are not the core
  runtime implementation
- Risk class: medium
- Classification label: mixed. `owned-clear` for tests and examples. `binary or
  asset-heavy` for large WAV or screenshot fixtures. `generated` for published
  outputs where appropriate.
- Related runtime units or flows: regression tests, packaged smoke evidence,
  plugin examples, UI screen examples, benchmark harness, GitHub Pages output
- Blockers: none currently recorded
- Exit criteria for this stage: these areas are classified honestly as
  evidence, examples, asset-heavy material, or published outputs instead of
  being mistaken for first-party runtime code
- Next prompt to run: evidence-quality pass only when needed
