<!-- markdownlint-disable-file MD013 -->

# Approval Packets

These packets prepare the current approval-gated remediation items for human
review. This pass does not edit application code.

## 1. Project and scan output boundary

- Exact area and files:
  `src/mmo/cli_commands/_project.py`,
  `src/mmo/tools/scan_session.py`,
  `src/mmo/core/session.py`,
  `src/mmo/core/media_tags.py`
- Protected-area category:
  local project and session control-plane output boundary with artifact and
  state reach
- Why the risk matters:
  `project show`, `project save`, `project load`, and scan output emit
  machine-readable data that includes absolute project paths, session paths,
  stem paths, hashes, and media-tag-derived content. Those are local product
  outputs, but they become telemetry when wrappers, CI, or support capture
  stdout.
- Current evidence:
  `docs/security/logging-audit.md` marked the project and scan output surfaces
  as sensitive and approval-gated. The output-boundary evidence pass confirmed
  that `_project.py` prints `project_dir` and per-artifact `absolute_path`, and
  `scan_session.py` emits path-bearing JSON and stderr progress.
- Smallest safe edit after approval:
  start with one output family and split machine-readable local output from a
  shared-log-safe summary surface before touching every JSON-emitting command
- What could break:
  CLI callers, shell scripts, test fixtures, or support flows that assume the
  current JSON shape
- Verification plan:
  `tools/run_pytest.sh -q tests/test_cli_project_load_save.py tests/test_cli_project_show.py tests/test_scan_smoke.py tests/test_cli_scan_lfe_audit.py`
  and `python3 tools/validate_contracts.py`, plus review of a captured stdout
  sample after the change
- Rollback plan:
  revert the output-contract change and restore the prior JSON shape if callers
  or fixtures break
- What human decision is required:
  approve whether the repo should introduce a split between machine-readable
  local output and shared-log-safe output, and whether a compatibility flag or
  phased rollout is needed
- Which unknowns still block the edit, if any:
  `docs/unknowns/remediation-pass.md` still records missing proof about which
  shared channels capture or forbid these outputs

## 2. GUI stderr forwarding (implemented on this branch)

- Exact area and files:
  `gui/lib/mmo_cli_runner.mjs`,
  `gui/lib/rpc_process_client.mjs`
- Protected-area category:
  GUI RPC and local subprocess bridge
- Why the risk matters:
  before this branch, both helpers forwarded raw subprocess stderr into
  browser-visible errors. A failing CLI or RPC call can include project paths,
  artifact paths, and other machine-local context.
- Current evidence:
  `docs/security/logging-audit.md` originally marked both helpers as
  conditional leaks in protected GUI bridge paths. The current branch now uses
  allowlisted summaries with public candidate labels, exit or error metadata,
  and `stderr_present` or `stderr_lines` counts. `cd gui && npm test` covers
  the new contract in `gui/tests/mmo_cli_runner.test.mjs` and
  `gui/tests/rpc_process_client.test.mjs`.
- Smallest safe edit after approval:
  completed on this branch by replacing raw stderr forwarding with allowlisted
  summary fields and basename-only candidate labels
- What could break:
  tests or local debugging flows that currently assert or rely on the full
  stderr text
- Verification plan:
  `cd gui && npm test`, with attention to
  `gui/tests/mmo_cli_runner.test.mjs` and
  `gui/tests/rpc_process_client.test.mjs`, plus one manual failing dev-shell
  path to confirm the browser surface still shows only the allowlisted summary
- Rollback plan:
  revert the allowlist change and restore raw stderr forwarding if the new
  summary shape breaks the intended GUI failure flow
- What human decision is required:
  completed for this branch. The approved direction was to narrow the surfaced
  error contract in the local GUI without adding a separate raw-stderr bypass.
- Which unknowns still block the edit, if any:
  no code blocker remains. `docs/unknowns/logging-audit.md` keeps a runtime
  spot-check note for one failing dev-shell path.

## 3. Render live-progress path output

- Exact area and files:
  `src/mmo/cli_commands/_renderers.py`,
  `src/mmo/core/progress.py`
- Protected-area category:
  render, QA, and output-stage logging on an audio-changing path
- Why the risk matters:
  `[MMO-LIVE]` stderr output currently carries raw `where` values such as
  report, output, receipt, and QA paths. That is machine-local path data on a
  protected render path.
- Current evidence:
  `docs/security/logging-audit.md` marked the live-progress path as a
  conditional leak in a protected render surface, and the backlog still treats
  it as approval-gated.
- Smallest safe edit after approval:
  replace absolute `where` path values with artifact labels or stable
  project-relative identifiers where full paths are not required
- What could break:
  log consumers, manual triage habits, or tests that expect the current
  `where` fields to contain full paths
- Verification plan:
  `tools/run_pytest.sh -q tests/test_cli_safe_render.py tests/test_safe_render_live_progress.py`
  and `python3 tools/validate_contracts.py`, plus inspection of a fresh
  `[MMO-LIVE]` stderr sample
- Rollback plan:
  revert to the previous `where` payload if log consumers or tests require the
  full path contract
- What human decision is required:
  approve narrowing render live-progress output on a protected render path and
  choosing whether artifact labels are enough for operator diagnostics
- Which unknowns still block the edit, if any:
  no strong repo-local blocker is recorded, but out-of-repo log consumers are
  still unproven

## 4. Bundled-plugin loader and market trust-boundary comments (implemented on this branch)

- Exact area and files:
  `src/mmo/core/plugin_loader.py`,
  `src/mmo/core/plugin_market.py`
- Protected-area category:
  plugin loaders, execution boundaries, and marketplace install flow
- Why the risk matters:
  these files decide which plugin roots are authoritative, when bundled
  fallback is allowed to contribute entries, how offline market installs resolve
  source files, and where writable installs are allowed to land
- Current evidence:
  `docs/review/bundled-plugin-review.md` mapped the split across repo manifests,
  packaged fallback manifests, shipped implementation modules, offline market
  assets, and the subjective-pack bypass. This batch narrows to the two files
  that define loader and market authority boundaries directly.
- Smallest safe edit after approval:
  add comment-only trust-boundary notes that explain root precedence, fallback
  behavior, per-root validation, index-as-locator behavior, manifest authority,
  and writable-target-only install scope
- What could break:
  no runtime behavior should change. The real risk is stale or overstated
  comments if the wording outruns the code.
- Verification plan:
  `tools/run_pytest.sh -q tests/test_plugin_loader.py tests/test_plugin_market.py`,
  `python3 tools/validate_contracts.py`,
  and review of the comment text against `docs/review/bundled-plugin-trust-boundary-audit.md`
- Rollback plan:
  revert the new comments and related docs if later review finds they no longer
  match the code or they overstate slice coverage
- What human decision is required:
  completed for this branch. Approval covered the first bundled-plugin comment
  batch beginning with loader and market authority files.
- Which unknowns still block the edit, if any:
  no code blocker remained for these two files. Wider slice unknowns still live
  in `docs/unknowns/bundled-plugin-review.md` for later renderer,
  corrective-plugin, and subjective-pack follow-up work.

## 5. Bundled shipped-renderer comments (implemented on this branch)

- Exact area and files:
  `src/mmo/plugins/renderers/mixdown_renderer.py`,
  `src/mmo/plugins/renderers/placement_mixdown_renderer.py`,
  `src/mmo/plugins/renderers/safe_renderer.py`
- Protected-area category:
  shipped renderers on audio-changing and approval-audit paths
- Why the risk matters:
  these files define the baseline reference render, the scene-driven placement
  render with stereo-reference QA, and the approval receipt renderer that
  records recommendation disposition without writing audio
- Current evidence:
  `docs/review/bundled-plugin-review.md` identified these renderer files as the
  next highest-value shipped implementation boundary after loader and market
  authority notes. This batch stays comment-only and only clarifies existing
  render and approval invariants.
- Smallest safe edit after approval:
  add comment-only notes that explain recommendation non-authority in baseline
  mixdown, stereo-reference QA dependence in placement rendering, and the
  safe renderer's fail-closed approval rule
- What could break:
  no runtime behavior should change. The real risk is stale or overstated
  comments if the wording outruns the code.
- Verification plan:
  `tools/run_pytest.sh -q tests/test_mixdown_renderer_multiformat.py tests/test_placement_mixdown_renderer.py tests/test_corrective_plugins.py tests/test_cli_safe_render.py`,
  `python3 tools/validate_contracts.py`,
  and review of the comment text against `docs/review/bundled-renderer-comment-audit.md`
- Rollback plan:
  revert the new comments and related docs if later review finds they no longer
  match the code or they imply broader slice closure than the repo supports
- What human decision is required:
  completed for this branch. Approval covered the next bundled-plugin comment
  batch on the selected shipped renderer files.
- Which unknowns still block the edit, if any:
  no code blocker remained for these renderer files. Wider slice unknowns still
  live in `docs/unknowns/bundled-plugin-review.md` for corrective plugins,
  market parity, checkout examples, and the subjective-pack bypass.

## 6. Bundled corrective detector and resolver comments (implemented on this branch)

- Exact area and files:
  `src/mmo/plugins/detectors/lfe_corrective_detector.py`,
  `src/mmo/plugins/resolvers/lfe_corrective_resolver.py`
- Protected-area category:
  approval-gated bundled plugin detectors and resolvers on an audio-changing
  corrective path
- Why the risk matters:
  these files decide when the repo emits `ISSUE.LFE.*` findings, which
  corrective filter candidates are described, and how the later safe-render
  flow records approval, rollback, and explicit-LFE no-silent-reroute notes
- Current evidence:
  `docs/review/bundled-plugin-review.md` and
  `docs/review/bundled-renderer-comment-audit.md` left the corrective detector
  and resolver pair as the next approval-sensitive boundary inside the bundled
  plugin slice. This batch stays comment-only and only clarifies the evidence
  scope, approval requirement, and non-executory resolver role already present
  in code and tests.
- Smallest safe edit after approval:
  add comment-only notes that explain explicit-LFE gating in the detector,
  additive issue emission, approval-only resolver output, and unchanged
  evidence carry-through into receipts
- What could break:
  no runtime behavior should change. The real risk is stale or overstated
  comments if the wording outruns the code or suggests that approval became
  optional.
- Verification plan:
  `tools/run_pytest.sh -q tests/test_corrective_plugins.py tests/test_lfe_corrective_approval.py`,
  `python3 tools/validate_contracts.py`,
  and review of the comment text against
  `docs/review/bundled-corrective-plugin-audit.md`
- Rollback plan:
  revert the new comments and related docs if later review finds they no longer
  match the code or they imply broader slice closure than the repo supports
- What human decision is required:
  completed for this branch. Approval covered the next bundled-plugin comment
  batch on the selected corrective detector and resolver files.
- Which unknowns still block the edit, if any:
  no code blocker remained for these two files. Wider slice unknowns still live
  in `docs/unknowns/bundled-plugin-review.md` for the subjective-pack bypass,
  checkout examples, and offline market parity.

## 7. Packaged smoke receipts and release workflow console output

- Exact area and files:
  `tools/smoke_packaged_desktop.py`,
  `.github/workflows/release.yml`
- Protected-area category:
  packaged desktop smoke, release tooling, and CI control plane
- Why the risk matters:
  the smoke harness emits path-rich JSON on success and raw installer stdout,
  stderr, and log tails on failure. The Windows release workflow also echoes
  install paths directly into CI logs.
- Current evidence:
  `docs/security/logging-audit.md` marked the smoke harness and Windows release
  console output as active leaks on protected support and control-plane paths.
  The publish-and-release evidence pass confirmed that the repo still cannot
  prove the full out-of-repo installer and signer boundary.
- Smallest safe edit after approval:
  narrow the smoke harness output to artifact kind, verdict, and bounded status
  summaries first, then remove raw install-path echoes from workflow console
  output while leaving full logs on disk or as opt-in artifacts only
- What could break:
  smoke-tool tests, release-triage habits, or CI expectations around current
  console output shape
- Verification plan:
  `python3 -m py_compile tools/smoke_packaged_desktop.py`,
  `tools/run_pytest.sh -q tests/test_packaged_desktop_smoke.py tests/test_packaged_smoke_goldens.py`,
  and `python3 tools/validate_contracts.py`, plus review of the workflow diff
  for console-output shape
- Rollback plan:
  revert the output narrowing if smoke tests or release triage lose required
  signal
- What human decision is required:
  approve narrowing release and smoke logs on a protected control-plane path
  and decide whether any full installer detail should remain available only as
  local or opt-in artifacts
- Which unknowns still block the edit, if any:
  `docs/unknowns/remediation-pass.md` still records missing repo-local proof of
  the Windows installer and signing boundary, and
  `docs/unknowns/logging-audit.md` still notes runtime-dependent installer
  output
