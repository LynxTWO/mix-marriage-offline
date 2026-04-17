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

## 2. GUI stderr forwarding

- Exact area and files:
  `gui/lib/mmo_cli_runner.mjs`,
  `gui/lib/rpc_process_client.mjs`
- Protected-area category:
  GUI RPC and local subprocess bridge
- Why the risk matters:
  both helpers forward raw subprocess stderr into browser-visible errors. A
  failing CLI or RPC call can include project paths, artifact paths, and other
  machine-local context.
- Current evidence:
  `docs/security/logging-audit.md` marked both helpers as conditional leaks in
  protected GUI bridge paths. The backlog and logging unknowns still treat this
  as approval-gated, not soft evidence.
- Smallest safe edit after approval:
  replace raw stderr forwarding with an allowlisted summary such as exit code,
  candidate label, `stderr_present`, and bounded line count or first-line
  status
- What could break:
  tests or local debugging flows that currently assert or rely on the full
  stderr text
- Verification plan:
  `cd gui && npm test`, with attention to
  `gui/tests/mmo_cli_runner.test.mjs` and
  `gui/tests/rpc_process_client.test.mjs`, plus one manual failing dev-shell
  path
- Rollback plan:
  revert the allowlist change and restore raw stderr forwarding if the new
  summary shape breaks the intended GUI failure flow
- What human decision is required:
  approve narrowing the surfaced error contract in the local GUI and deciding
  whether any richer detail should survive behind an explicit local-debug path
- Which unknowns still block the edit, if any:
  `docs/unknowns/logging-audit.md` still notes that the worst-case stderr
  payload depends on runtime failures, but that does not block a redaction
  direction

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

## 4. Packaged smoke receipts and release workflow console output

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
