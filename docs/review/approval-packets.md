<!-- markdownlint-disable-file MD013 -->

# Approval Packets

These packets prepare the current approval-gated remediation items for human
review. This pass does not edit application code.

## 1. Project and scan output boundary

- Exact area and files:
  `src/mmo/cli_commands/_project.py`,
  `src/mmo/cli_commands/_gui_rpc.py`,
  `gui/server.mjs`,
  `gui/web/app.js`,
  `src/mmo/tools/scan_session.py`,
  `src/mmo/cli_commands/_analysis.py`,
  `src/mmo/tools/analyze_stems.py`,
  `src/mmo/core/variants.py`,
  `src/mmo/core/session.py`,
  `src/mmo/core/media_tags.py`
- Protected-area category:
  local project and session control-plane output boundary with GUI RPC,
  artifact, and state reach
- Why the risk matters:
  `project show`, `project save`, `project load`, and scan output emit
  machine-readable data that includes absolute project paths, session paths,
  stem paths, hashes, and media-tag-derived content. The new evidence shows
  `project.show` is not only shell output. The GUI RPC path parses that JSON
  and sends it to the local browser shell. The scan path is different. Its
  data class is still high risk, but most repo-owned consumers keep it
  file-backed or in memory instead of surfacing raw JSON stdout to the browser.
- Current evidence:
  `docs/security/logging-audit.md` marked the project and scan output surfaces
  as sensitive and approval-gated. The refreshed evidence pass confirmed that
  `_project.py` prints `project_dir` and per-artifact `absolute_path`.
  `_gui_rpc.py`, `gui/server.mjs`, and `gui/web/app.js` prove a real local
  browser-visible `project.show` consumer, and `docs/13-gui-handshake.md`
  documents that flow. `scan_session.py` still emits path-bearing JSON and
  stderr progress, but `_analysis.py`, `analyze_stems.py`, `variants.py`,
  `docs/user_guide.md`, and `docs/manual/04-the-main-workflows.md` show the
  normal repo-owned scan path is `--out` file output, direct module use, or
  in-memory test parsing. `.github/ISSUE_TEMPLATE/bug_report.yml` is one
  repo-owned shared channel because it asks for exact commands, artifact paths,
  and machine-readable behavior while also requiring scrubbing of private
  paths. Workflow inspection found no repo-owned upload path for project JSON,
  scan JSON, or agent trace artifacts. Phase 1 is now implemented on this
  branch: `project show --format json-shared` drops `project_dir` and
  per-artifact `absolute_path`, while the GUI and RPC path stays on the local
  `json` contract. Phase 2 is now implemented on this branch too:
  `project save --format json-shared` and `project load --format json-shared`
  keep the current local `json` contract, drop `project_dir`, and replace
  path fields with project-relative or basename-only refs in the shared
  profile. Phase 3 is now implemented on this branch too: the shell-facing CLI
  default for `project save` and `project load` now uses `json-shared`, while
  RPC keeps the full local `json` default. Focused CLI and RPC tests now cover
  both defaults and both explicit profiles. Phase 4 is now implemented on this
  branch too: shell-facing `project show` now defaults to `json-shared`, while
  GUI and RPC keep the explicit local `json` path contract. Phase 5 is now
  implemented on this branch too: `scan_session` and `mmo scan` now support
  `--format json-shared`, shell stdout defaults to the shared-safe profile,
  and `--out` plus explicit `--format json` keep the full local report
  contract.
- Smallest safe edit after approval:
  completed phase 1 on this branch by adding `project show --format
  json-shared`, completed phase 2 by adding shared-log-safe save and load
  profiles, and completed phase 3 by making the shell-facing save or load CLI
  default shared-safe while leaving RPC local. Phase 4 now narrows the
  shell-facing `project show` default the same way while leaving GUI and RPC
  local. Phase 5 adds the same shell-safe split for scan stdout while leaving
  file-backed `--out` reports and explicit `--format json` local. The next
  safe edit is now narrower than this packet: decide whether the explicit
  local project or scan JSON contracts should narrow further, or stay
  documented as intentional local-only paths.
- What could break:
  the GUI RPC hydration path, browser shell state, CLI callers, shell scripts,
  test fixtures, or support flows that assume the current project JSON shape.
  The implemented phase-1 through phase-4 changes keep the full local path
  contract available through explicit `json` or RPC. Phase 5 keeps the full
  scan report contract on `--out` and explicit `--format json`, so the main
  break risk now sits in shell callers that assumed raw scan stdout by
  default, or in any future attempt to narrow the explicit local contracts.
- Verification plan:
  phase 1 ran `tools/run_pytest.sh -q tests/test_cli_project_show.py tests/test_cli_gui_rpc.py`
  and `python3 tools/validate_contracts.py`. Phases 2 and 3 ran
  `tools/run_pytest.sh -q tests/test_cli_project_load_save.py tests/test_cli_gui_rpc.py`
  and `python3 tools/validate_contracts.py`. Phase 4 ran
  `tools/run_pytest.sh -q tests/test_cli_project_show.py tests/test_cli_gui_rpc.py`
  and `python3 tools/validate_contracts.py`. Phase 5 ran
  `tools/run_pytest.sh -q tests/test_scan_smoke.py tests/test_validation_wav_codec.py tests/test_scan_ffmpeg_basic.py tests/test_scan_ffprobe_layout.py tests/test_scan_truth_weighting_multiformat.py tests/test_truth_meters_optional_deps.py tests/test_cli_scan_lfe_audit.py tests/test_cli_project_build_gui.py`
  and `python3 tools/validate_contracts.py`. The project-output work also has one local shell
  `project.show --format json-shared` sample, one local `mmo gui rpc`
  `project.show` sample, one local shell `project show` default-output sample,
  one local shell `project save --format json-shared` sample, one local shell
  `project load --format json-shared` sample, one local shell `project save`
  default-output sample, one local shell `project load` default-output sample,
  one local shell `mmo scan` default-output sample, and one local shell
  `mmo scan --format json` sample.
- Rollback plan:
  phases 1 through 5 can revert the shared-safe profiles or the CLI defaults
  without changing the existing RPC contract or the file-backed scan contract.
- What human decision is required:
  phases 1 through 5 are complete. The next approval decision is whether the
  repo should stop at the current shell boundary, or start a narrower packet
  for the explicit local `json` project and scan paths.
- Which unknowns still block the edit, if any:
  `docs/unknowns/remediation-pass.md` and
  `docs/unknowns/evidence-gap-pass.md` still record missing proof about
  out-of-repo support, CI log, and issue-thread habits for the explicit local
  contracts and any shared human handling of these outputs

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

## 3. Render live-progress path output (implemented on this branch)

- Exact area and files:
  `src/mmo/cli_commands/_renderers.py`,
  `tests/test_cli_safe_render.py`
- Protected-area category:
  render, QA, and output-stage logging on an audio-changing path
- Why the risk matters:
  `[MMO-LIVE]` stderr output currently carries raw `where` values such as
  report, output, receipt, and QA paths. That is machine-local path data on a
  protected render path.
- Current evidence:
  `docs/security/logging-audit.md` marked the live-progress path as a
  conditional leak in a protected render surface, and the backlog treated it as
  approval-gated. The desktop sidecar only parses `where` as `string[]`, the
  desktop UI renders it as display text, and the existing safe-render
  live-progress test only required `where` to exist. This branch now narrows
  the path-bearing entries in `_renderers.py` to target IDs, stable labels, and
  workspace-relative refs instead of absolute paths.
- Smallest safe edit after approval:
  completed on this branch by keeping `where` on target IDs, stable artifact
  labels, and workspace-relative refs where the render workspace already owns
  the path context
- What could break:
  log consumers, manual triage habits, or tests that assumed `where` always
  carried full absolute paths
- Verification plan:
  this branch ran
  `tools/run_pytest.sh -q tests/test_cli_safe_render.py -k "live_progress or cancel_file_stops_safe_render_with_exit_130"`,
  `python3 tools/validate_contracts.py`,
  one local dry-run `safe-render --live-progress` stderr sample,
  and one local full-render `safe-render --live-progress` stderr sample
- Rollback plan:
  revert the bounded `where` helper if a live-progress consumer proves it needs
  the old absolute-path contract
- What human decision is required:
  completed for this branch. Approval covered narrowing the protected
  live-progress path without widening the change into receipt, QA, or generic
  stderr behavior.
- Which unknowns still block the edit, if any:
  no strong repo-local blocker remains for this path. The remaining log-sharing
  uncertainty is broader and still lives in the packaged smoke and project or
  scan output packets.

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

## 7. Bundled subjective-bypass comments (implemented on this branch)

- Exact area and files:
  `src/mmo/dsp/plugins/registry.py`,
  `src/mmo/plugins/subjective/__init__.py`,
  `src/mmo/plugins/subjective/binaural_preview_v0.py`
- Protected-area category:
  shipped plugin authority exception on a DSP and render-target path
- Why the risk matters:
  these files make the subjective pack first-class shipped behavior even though
  it does not flow through the manifest loader, bundled fallback manifests, or
  offline market install roots
- Current evidence:
  `docs/review/bundled-plugin-review.md` left the subjective pack as the last
  missing trust-boundary note inside the bundled-plugin slice. The registry
  tests, binaural preview tests, and CLI binaural checks already prove that
  this path resolves from the DSP registry and is called directly by the
  binaural target flow.
- Smallest safe edit after approval:
  add comment-only notes that explain the DSP-side allowlist in
  `registry.py`, restate the shipped exception in `subjective/__init__.py`, and
  document the direct preview-module call path in
  `binaural_preview_v0.py`
- What could break:
  no runtime behavior should change. The real risk is stale or overstated
  comments if the wording implies broader closure than the remaining evidence
  supports.
- Verification plan:
  `tools/run_pytest.sh -q tests/test_subjective_plugins.py tests/test_subjective_binaural_preview.py tests/test_cli_safe_render.py -k binaural`,
  `python3 tools/validate_contracts.py`,
  and review of the comment text against
  `docs/review/bundled-subjective-bypass-audit.md`
- Rollback plan:
  revert the new comments and related docs if later review finds they no longer
  match the code or they overstate bundled-plugin closure
- What human decision is required:
  completed for this branch. Approval covered the next bundled-plugin comment
  batch on the selected subjective-bypass files.
- Which unknowns still block the edit, if any:
  no code blocker remained for these files. Wider bundled-plugin evidence gaps
  still live in `docs/unknowns/bundled-plugin-review.md` for checkout examples
  and offline market parity.

## 8. Packaged smoke receipts and release workflow console output

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
  prove the full out-of-repo installer and signer boundary. This branch now
  narrows the printed smoke payloads, cleanup payloads, Windows failure
  receipts, and the Windows release workflow console labels to shared-safe
  summaries. The on-disk Windows install-state file still keeps the full local
  paths because cleanup and signature verification need that state artifact.
- Smallest safe edit after approval:
  completed on this branch by keeping smoke and workflow output on artifact
  labels, installer kind, signature status, and bounded line counts while
  leaving full installer logs and the Windows install-state JSON on disk only
- What could break:
  smoke-tool tests, release-triage habits, or CI expectations around the old
  path-rich console shape
- Verification plan:
  `python3 -m py_compile tools/smoke_packaged_desktop.py`,
  `tools/run_pytest.sh -q tests/test_packaged_desktop_smoke.py tests/test_packaged_smoke_goldens.py`,
  and `python3 tools/validate_contracts.py`, plus review of the workflow diff
  for console-output shape
- Rollback plan:
  revert the output narrowing if smoke tests or release triage lose required
  signal
- What human decision is required:
  completed for this branch. Approval covered narrowing the shared console
  copies while keeping full installer detail available only through the local
  install-state file and installer logs on disk.
- Which unknowns still block the edit, if any:
  no code blocker remained for the shared-output boundary. Wider release and
  installer-boundary unknowns still live in
  `docs/unknowns/remediation-pass.md` and
  `docs/unknowns/logging-audit.md`.
