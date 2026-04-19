<!-- markdownlint-disable-file MD013 -->

# Safe Fix Plan

This plan covers the first safe remediation batch from
`docs/review/remediation-backlog.md`.

It only includes items that are clearly evidenced, not approval-gated, and
small enough to review as docs-only work.

## Current protected-area batch

## 14. Shell-facing scan stdout shared-safe profile and default

- Exact files to change:
  `src/mmo/tools/scan_session.py`,
  `src/mmo/cli.py`,
  `src/mmo/cli_commands/_analysis.py`,
  `src/mmo/cli_commands/_project.py`,
  `tests/test_scan_smoke.py`,
  `tests/test_validation_wav_codec.py`,
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/remediation-pass.md`,
  `docs/review/evidence-gap-check.md`,
  `docs/unknowns/evidence-gap-pass.md`,
  `docs/user_guide.md`,
  `docs/manual/04-the-main-workflows.md`
- Why this change is safe now:
  the focused caller audit found no repo-owned GUI, browser, CI, or release
  consumer for raw scan stdout. Direct stdout pressure is almost entirely tests,
  while normal repo-owned scan flows already use `--out`, direct module calls,
  or in-memory handling.
- What behavior must remain unchanged:
  full report JSON written under `--out`, explicit `--format json` behavior,
  `--dry-run` and `--summary` text output, `build_report()` payload shape for
  in-memory callers, `analyze_stems.py` file-backed handoff, and project build
  GUI scan handoff through the full local report file
- Tests or checks to run:
  `tools/run_pytest.sh -q tests/test_scan_smoke.py tests/test_validation_wav_codec.py tests/test_scan_ffmpeg_basic.py tests/test_scan_ffprobe_layout.py tests/test_scan_truth_weighting_multiformat.py tests/test_truth_meters_optional_deps.py tests/test_cli_scan_lfe_audit.py tests/test_cli_project_build_gui.py`,
  `python3 tools/validate_contracts.py`,
  one local shell `mmo scan` shared-safe sample,
  one local shell `mmo scan --format json` sample,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/review/remediation-backlog.md docs/unknowns/remediation-pass.md docs/review/evidence-gap-check.md docs/unknowns/evidence-gap-pass.md docs/user_guide.md docs/manual/04-the-main-workflows.md`,
  and `git diff --check -- src/mmo/tools/scan_session.py src/mmo/cli.py src/mmo/cli_commands/_analysis.py src/mmo/cli_commands/_project.py tests/test_scan_smoke.py tests/test_validation_wav_codec.py docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/review/remediation-backlog.md docs/unknowns/remediation-pass.md docs/review/evidence-gap-check.md docs/unknowns/evidence-gap-pass.md docs/user_guide.md docs/manual/04-the-main-workflows.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/remediation-pass.md`,
  `docs/review/evidence-gap-check.md`,
  `docs/unknowns/evidence-gap-pass.md`,
  `docs/user_guide.md`,
  `docs/manual/04-the-main-workflows.md`
- Rollback note:
  restore the scan stdout default to `json` if a shell-facing caller proves it
  relied on the old machine-local contract without passing `--format json`
- Observability note:
  keep the full report contract on `--out` and explicit `--format json`. Do
  not widen this batch into `analyze_stems.py`, file-backed report redaction,
  or agent-trace hardening.
- Change type:
  behavior-preserving code cleanup

## 13. Shell-facing `project.show` default

- Exact files to change:
  `src/mmo/cli.py`,
  `tests/test_cli_project_show.py`,
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/review/remediation-backlog.md`,
  `docs/manual/12-projects-sessions-and-artifacts.md`
- Why this change is safe now:
  the focused caller audit found no in-repo browser or desktop caller for the
  CLI default, only docs and CLI tests, and the prior batch already proved the
  shell and RPC routes can diverge cleanly with RPC pinned to explicit `json`
- What behavior must remain unchanged:
  RPC `project.show` payload shape, explicit `--format json` behavior for CLI
  project show, artifact allowlist order, deterministic output for unchanged
  formats, and browser hydration from `absolute_path` receipts
- Tests or checks to run:
  `tools/run_pytest.sh -q tests/test_cli_project_show.py tests/test_cli_gui_rpc.py`,
  `python3 tools/validate_contracts.py`,
  one local shell `project show` default-output sample,
  one local `mmo gui rpc` `project.show` sample,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/review/remediation-backlog.md docs/manual/12-projects-sessions-and-artifacts.md`,
  and `git diff --check -- src/mmo/cli.py tests/test_cli_project_show.py docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/review/remediation-backlog.md docs/manual/12-projects-sessions-and-artifacts.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/review/remediation-backlog.md`,
  `docs/manual/12-projects-sessions-and-artifacts.md`
- Rollback note:
  restore the CLI default to `json` if a shell-facing caller proves it relied
  on the old machine-local path contract without passing `--format json`
- Observability note:
  keep the browser and RPC route explicit on `json`. Do not widen this batch
  into scan-output redaction or GUI contract changes.
- Change type:
  behavior-preserving code cleanup

## 12. Shell-facing `project.save` and `project.load` defaults

- Exact files to change:
  `src/mmo/cli.py`,
  `tests/test_cli_project_load_save.py`,
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/review/remediation-backlog.md`,
  `docs/manual/12-projects-sessions-and-artifacts.md`,
  `docs/user_guide.md`
- Why this change is safe now:
  the focused caller audit found no in-repo app consumer for the CLI defaults,
  only tests and docs, and the prior batch already added explicit `json` and
  `json-shared` profiles so the shell-facing default can narrow without
  removing the full local path contract
- What behavior must remain unchanged:
  RPC default `json` payloads, explicit `--format json` behavior for CLI save
  and load, session write and restore semantics, receipt counts, and the
  project-relative `written` paths that load reports
- Tests or checks to run:
  `tools/run_pytest.sh -q tests/test_cli_project_load_save.py tests/test_cli_gui_rpc.py`,
  `python3 tools/validate_contracts.py`,
  one local shell `project save` default-output sample,
  one local shell `project load` default-output sample,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/review/remediation-backlog.md docs/manual/12-projects-sessions-and-artifacts.md docs/user_guide.md`,
  and `git diff --check -- src/mmo/cli.py tests/test_cli_project_load_save.py docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/review/remediation-backlog.md docs/manual/12-projects-sessions-and-artifacts.md docs/user_guide.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/review/remediation-backlog.md`,
  `docs/manual/12-projects-sessions-and-artifacts.md`,
  `docs/user_guide.md`
- Rollback note:
  restore the CLI default to `json` if a shell-facing caller proves it relied
  on the old machine-local path contract without passing `--format json`
- Observability note:
  keep this boundary limited to CLI defaults. Do not widen it into RPC default
  changes or scan-output redaction.
- Change type:
  behavior-preserving code cleanup

## 11. `project.save` and `project.load` shared-log-safe JSON profile

- Exact files to change:
  `src/mmo/cli.py`,
  `src/mmo/cli_commands/_project.py`,
  `src/mmo/cli_commands/_gui_rpc.py`,
  `tests/test_cli_project_load_save.py`,
  `tests/test_cli_gui_rpc.py`,
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/review/remediation-backlog.md`,
  `docs/manual/12-projects-sessions-and-artifacts.md`
- Why this change is safe now:
  the focused consumer review found no browser or desktop caller for
  `project.save` or `project.load`, only CLI and RPC contract tests, and an
  additive shared-log-safe format can narrow shell-facing path fields without
  changing the existing local `json` contract
- What behavior must remain unchanged:
  default `project save` and `project load` JSON shape, GUI RPC default result
  shape, session write and restore behavior, `project_session.json` defaults,
  receipt counts, and the relative `written` paths that load already reports
- Tests or checks to run:
  `tools/run_pytest.sh -q tests/test_cli_project_load_save.py tests/test_cli_gui_rpc.py -k "project_save_and_load or project_save_writes_session_payload or project_load_restores_artifacts or rpc_discover"`,
  `python3 tools/validate_contracts.py`,
  one local shell `project save --format json-shared` sample,
  one local shell `project load --format json-shared` sample,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/review/remediation-backlog.md docs/manual/12-projects-sessions-and-artifacts.md`,
  and `git diff --check -- src/mmo/cli.py src/mmo/cli_commands/_project.py src/mmo/cli_commands/_gui_rpc.py tests/test_cli_project_load_save.py tests/test_cli_gui_rpc.py docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/review/remediation-backlog.md docs/manual/12-projects-sessions-and-artifacts.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/review/remediation-backlog.md`,
  `docs/manual/12-projects-sessions-and-artifacts.md`
- Rollback note:
  revert the new `json-shared` format plumbing for save and load if a caller
  proves it needs one format only or the new shared-safe profile causes
  confusion in local tooling
- Observability note:
  keep the new profile additive. Do not widen this batch into default `json`
  changes or scan-output redaction.
- Change type:
  behavior-preserving code cleanup

## 10. Project session receipt allowlist trim

- Exact files to change:
  `src/mmo/core/config.py`,
  `tests/test_project_session.py`,
  `docs/review/safe-fix-plan.md`
- Why this change is safe now:
  the current project render wrapper writes scaffold receipts under
  `renders/`, the system map and user docs already describe the current
  scaffold names, and the only in-repo references to the old dotted
  safe-render receipt names are fallback labels outside the project-session
  save or load flow
- What behavior must remain unchanged:
  session schema version, default `project_session.json` path, `--force`
  overwrite rules, current `renders/` receipt capture, and project-session
  load semantics for already-saved session files
- Tests or checks to run:
  `tools/run_pytest.sh -q tests/test_project_session.py tests/test_cli_project_load_save.py`,
  `python3 tools/validate_contracts.py`,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md`,
  and `git diff --check -- src/mmo/core/config.py tests/test_project_session.py docs/review/safe-fix-plan.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`
- Rollback note:
  restore the dotted receipt names to `_PROJECT_DEFAULT_RECEIPT_PATHS` if a
  current project flow proves it still writes those root-level artifacts and
  expects session export to preserve them
- Observability note:
  none; this is a session-export contract trim, not a log or telemetry change
- Change type:
  behavior-preserving code cleanup
- Compatibility trim note:
  this batch intentionally removes dead compatibility baggage from session
  export instead of preserving legacy dotted safe-render receipt names that the
  current project scaffold no longer writes

## 9. Safe-render live-progress `where` redaction

- Exact files to change:
  `src/mmo/cli_commands/_renderers.py`,
  `tests/test_cli_safe_render.py`,
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/unknowns/logging-audit.md`,
  `docs/review/remediation-backlog.md`
- Why this change is safe now:
  the approval packet already narrowed this protected batch to `safe-render`
  live-progress `where` values, the current tests only require the `where`
  field to exist, and the desktop live-progress surfaces treat `where` as
  display text instead of a path lookup contract
- What behavior must remain unchanged:
  `safe-render` stage order, recommendation and render behavior, live-progress
  JSON shape outside the path values, stderr emission on `--live-progress`, and
  the current desktop handling of live-progress events
- Tests or checks to run:
  `tools/run_pytest.sh -q tests/test_cli_safe_render.py -k "live_progress or cancel_file_stops_safe_render_with_exit_130"`,
  `python3 tools/validate_contracts.py`,
  one local dry-run `safe-render --live-progress` stderr sample,
  one local full-render `safe-render --live-progress` stderr sample,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/unknowns/logging-audit.md docs/review/remediation-backlog.md`,
  and `git diff --check -- src/mmo/cli_commands/_renderers.py tests/test_cli_safe_render.py docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/unknowns/logging-audit.md docs/review/remediation-backlog.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/unknowns/logging-audit.md`,
  `docs/review/remediation-backlog.md`
- Rollback note:
  revert the bounded `where` helper and restore the prior absolute-path payload
  if a live-progress consumer proves it needs the old path contract
- Observability note:
  keep `where` on stable labels or workspace-relative refs. Do not widen this
  batch into generic stderr changes or unrelated render receipt fields.
- Change type:
  behavior-preserving code cleanup
- Compatibility trim note:
  this batch does not remove extra backward-compatibility logic. The reviewed
  live-progress slice did not prove a dead compatibility branch that was safe
  to trim.

## 8. `project.show` shared-log-safe JSON profile

- Exact files to change:
  `src/mmo/cli.py`,
  `src/mmo/cli_commands/_project.py`,
  `tests/test_cli_project_show.py`,
  `tests/test_cli_gui_rpc.py`,
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/unknowns/logging-audit.md`,
  `docs/review/remediation-backlog.md`,
  `docs/manual/12-projects-sessions-and-artifacts.md`,
  `docs/13-gui-handshake.md`
- Why this change is safe now:
  the refreshed approval packet narrows the first project-output remediation to
  the `project.show` family only, the GUI and RPC consumer path is now proven,
  and an additive shared-log-safe JSON profile can reduce shell-facing path
  exposure without breaking the existing local machine-readable contract
- What behavior must remain unchanged:
  existing `project show --format json` payload shape, GUI RPC hydration,
  browser-side artifact resolution from `absolute_path`, project-show artifact
  allowlist order, deterministic output for unchanged formats, and all
  `project save` or `project load` behavior
- Tests or checks to run:
  `tools/run_pytest.sh -q tests/test_cli_project_show.py tests/test_cli_gui_rpc.py`,
  `python3 tools/validate_contracts.py`,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/unknowns/logging-audit.md docs/review/remediation-backlog.md docs/manual/12-projects-sessions-and-artifacts.md docs/13-gui-handshake.md`,
  and `git diff --check -- src/mmo/cli.py src/mmo/cli_commands/_project.py tests/test_cli_project_show.py tests/test_cli_gui_rpc.py docs/review/safe-fix-plan.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/unknowns/logging-audit.md docs/review/remediation-backlog.md docs/manual/12-projects-sessions-and-artifacts.md docs/13-gui-handshake.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/unknowns/logging-audit.md`,
  `docs/review/remediation-backlog.md`,
  `docs/manual/12-projects-sessions-and-artifacts.md`,
  `docs/13-gui-handshake.md`
- Rollback note:
  revert the new shared-log-safe profile and restore the prior project-show
  format list if callers, docs, or tests show that the new profile causes
  confusion or accidental contract drift
- Observability note:
  this is an output-boundary hardening change. The touched logging-audit and
  backlog docs must keep the existing default `json` format and the new
  shared-log-safe profile distinct so the repo does not overclaim closure
- Change type:
  behavior-preserving code cleanup

## 7. Bundled subjective-bypass trust boundary

- Exact files to change:
  `src/mmo/dsp/plugins/registry.py`,
  `src/mmo/plugins/subjective/__init__.py`,
  `src/mmo/plugins/subjective/binaural_preview_v0.py`,
  `docs/review/safe-fix-plan.md`,
  `docs/review/bundled-subjective-bypass-audit.md`,
  `docs/review/bundled-plugin-review.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/architecture/repo-slices.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/bundled-plugin-review.md`,
  `docs/unknowns/critical-paths.md`
- Why this change is safe now:
  the user approved the next protected bundled-plugin batch explicitly, the
  selected subjective-bypass files already have read-only review evidence, and
  this batch adds comment-only notes without changing plugin IDs, render flow,
  or manifest-loader behavior
- What behavior must remain unchanged:
  subjective plugin registry IDs and order, binaural preview selection,
  headphone preview render behavior, preview metadata shape, and the existing
  separation between manifest-loaded plugins and the DSP-side subjective pack
- Tests or checks to run:
  `tools/run_pytest.sh -q tests/test_subjective_plugins.py tests/test_subjective_binaural_preview.py tests/test_cli_safe_render.py -k binaural`,
  `python3 tools/validate_contracts.py`,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/review/bundled-subjective-bypass-audit.md docs/review/bundled-plugin-review.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/architecture/repo-slices.md docs/review/remediation-backlog.md docs/unknowns/bundled-plugin-review.md docs/unknowns/critical-paths.md`,
  and `git diff --check -- src/mmo/dsp/plugins/registry.py src/mmo/plugins/subjective/__init__.py src/mmo/plugins/subjective/binaural_preview_v0.py docs/review/safe-fix-plan.md docs/review/bundled-subjective-bypass-audit.md docs/review/bundled-plugin-review.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/architecture/repo-slices.md docs/review/remediation-backlog.md docs/unknowns/bundled-plugin-review.md docs/unknowns/critical-paths.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`,
  `docs/review/bundled-subjective-bypass-audit.md`,
  `docs/review/bundled-plugin-review.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/architecture/repo-slices.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/bundled-plugin-review.md`,
  `docs/unknowns/critical-paths.md`
- Rollback note:
  revert the new subjective-bypass comments and matching audit notes if later
  review finds they no longer match the code or they overstate slice closure
- Observability note:
  none; this batch does not change runtime output or telemetry
- Change type:
  comment-only

## 6. Bundled corrective detector and resolver boundaries

- Exact files to change:
  `src/mmo/plugins/detectors/lfe_corrective_detector.py`,
  `src/mmo/plugins/resolvers/lfe_corrective_resolver.py`,
  `docs/review/safe-fix-plan.md`,
  `docs/review/bundled-corrective-plugin-audit.md`,
  `docs/review/bundled-plugin-review.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/architecture/repo-slices.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/critical-paths.md`
- Why this change is safe now:
  the user approved the next protected bundled-plugin batch explicitly, the
  selected detector and resolver files already have read-only review evidence,
  and this batch adds comment-only notes without changing detection thresholds,
  recommendation payloads, or approval flow
- What behavior must remain unchanged:
  `ISSUE.LFE.*` detection thresholds, emitted issue IDs, corrective filter
  payload choices, `requires_approval` semantics, explicit-LFE no-silent-reroute
  behavior, and safe-render QA rerun behavior after an approved filter
- Tests or checks to run:
  `tools/run_pytest.sh -q tests/test_corrective_plugins.py tests/test_lfe_corrective_approval.py`,
  `python3 tools/validate_contracts.py`,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/review/bundled-corrective-plugin-audit.md docs/review/bundled-plugin-review.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/architecture/repo-slices.md docs/review/remediation-backlog.md docs/unknowns/critical-paths.md`,
  and `git diff --check -- src/mmo/plugins/detectors/lfe_corrective_detector.py src/mmo/plugins/resolvers/lfe_corrective_resolver.py docs/review/safe-fix-plan.md docs/review/bundled-corrective-plugin-audit.md docs/review/bundled-plugin-review.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/architecture/repo-slices.md docs/review/remediation-backlog.md docs/unknowns/critical-paths.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`,
  `docs/review/bundled-corrective-plugin-audit.md`,
  `docs/review/bundled-plugin-review.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/architecture/repo-slices.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/critical-paths.md`
- Rollback note:
  revert the new corrective-plugin comments and matching audit notes if later
  review finds they no longer match the code or they imply that approval or QA
  safeguards moved
- Observability note:
  none; this batch does not change runtime output or telemetry
- Change type:
  comment-only

## 5. Bundled shipped-renderer invariants

- Exact files to change:
  `src/mmo/plugins/renderers/mixdown_renderer.py`,
  `src/mmo/plugins/renderers/placement_mixdown_renderer.py`,
  `src/mmo/plugins/renderers/safe_renderer.py`,
  `docs/review/safe-fix-plan.md`,
  `docs/review/bundled-renderer-comment-audit.md`,
  `docs/review/bundled-plugin-review.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/architecture/repo-slices.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/critical-paths.md`
- Why this change is safe now:
  the user approved the next protected batch explicitly, the selected
  renderer files already have read-only audit evidence, and this batch adds
  comment-only notes without changing any DSP, QA, or approval logic
- What behavior must remain unchanged:
  baseline mixdown output behavior, placement render intent and fallback
  behavior, stereo-reference QA behavior, safe-renderer classification rules,
  manifest output ordering, and existing artifact contracts
- Tests or checks to run:
  `tools/run_pytest.sh -q tests/test_mixdown_renderer_multiformat.py tests/test_placement_mixdown_renderer.py tests/test_corrective_plugins.py tests/test_cli_safe_render.py`,
  `python3 tools/validate_contracts.py`,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/review/bundled-renderer-comment-audit.md docs/review/bundled-plugin-review.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/architecture/repo-slices.md docs/review/remediation-backlog.md docs/unknowns/critical-paths.md`,
  and `git diff --check -- src/mmo/plugins/renderers/mixdown_renderer.py src/mmo/plugins/renderers/placement_mixdown_renderer.py src/mmo/plugins/renderers/safe_renderer.py docs/review/safe-fix-plan.md docs/review/bundled-renderer-comment-audit.md docs/review/bundled-plugin-review.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/architecture/repo-slices.md docs/review/remediation-backlog.md docs/unknowns/critical-paths.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`,
  `docs/review/bundled-renderer-comment-audit.md`,
  `docs/review/bundled-plugin-review.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/architecture/repo-slices.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/critical-paths.md`
- Rollback note:
  revert the new renderer comments and matching audit notes if later review
  finds they no longer match the code or they imply broader slice closure than
  the repo evidence supports
- Observability note:
  none; this batch does not change runtime output or telemetry
- Change type:
  comment-only

## 4. Bundled-plugin loader and market trust-boundary comments

- Exact files to change:
  `src/mmo/core/plugin_loader.py`,
  `src/mmo/core/plugin_market.py`,
  `docs/review/safe-fix-plan.md`,
  `docs/review/bundled-plugin-trust-boundary-audit.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/architecture/repo-slices.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/critical-paths.md`
- Why this change is safe now:
  the user approved this protected comment batch explicitly, the selected
  functions already have read-only audit evidence, and the batch only adds
  explanatory comments plus matching audit notes
- What behavior must remain unchanged:
  plugin root precedence, bundled fallback behavior, per-root validation order,
  duplicate-ID failure behavior, market source resolution, manifest authority
  before install, writable install target selection, and idempotent reinstall
  semantics
- Tests or checks to run:
  `tools/run_pytest.sh -q tests/test_plugin_loader.py tests/test_plugin_market.py`,
  `python3 tools/validate_contracts.py`,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/review/bundled-plugin-trust-boundary-audit.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/architecture/repo-slices.md docs/review/remediation-backlog.md docs/unknowns/critical-paths.md`,
  and `git diff --check -- src/mmo/core/plugin_loader.py src/mmo/core/plugin_market.py docs/review/safe-fix-plan.md docs/review/bundled-plugin-trust-boundary-audit.md docs/review/approval-packets.md docs/architecture/coverage-ledger.md docs/architecture/repo-slices.md docs/review/remediation-backlog.md docs/unknowns/critical-paths.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`,
  `docs/review/bundled-plugin-trust-boundary-audit.md`,
  `docs/review/approval-packets.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/architecture/repo-slices.md`,
  `docs/review/remediation-backlog.md`,
  `docs/unknowns/critical-paths.md`
- Rollback note:
  revert the new comments and audit notes if later review finds any comment
  overstated the authority boundary or no longer matches the code
- Observability note:
  none; this batch does not change runtime output or telemetry
- Change type:
  comment-only

## 3. GUI stderr redaction in the local dev-shell bridge

- Exact files to change:
  `gui/lib/mmo_cli_runner.mjs`,
  `gui/lib/rpc_process_client.mjs`,
  `gui/tests/mmo_cli_runner.test.mjs`,
  `gui/tests/rpc_process_client.test.mjs`,
  `docs/review/safe-fix-plan.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/unknowns/logging-audit.md`
- Why this change is safe now:
  the approval packet is already written, the risky surface is narrow, and the
  change only replaces raw stderr and path-rich candidate labels with a short
  allowlist summary
- What behavior must remain unchanged:
  CLI fallback order, RPC startup and request flow, browser-visible failure
  detection, local dev-shell routing, and the existing success-path JSON
  contracts
- Tests or checks to run:
  `cd gui && npm test`,
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/unknowns/logging-audit.md`,
  `git diff --check -- gui/lib/mmo_cli_runner.mjs gui/lib/rpc_process_client.mjs gui/tests/mmo_cli_runner.test.mjs gui/tests/rpc_process_client.test.mjs docs/review/safe-fix-plan.md docs/architecture/coverage-ledger.md docs/security/logging-audit.md docs/unknowns/logging-audit.md`
- Docs to update:
  `docs/review/safe-fix-plan.md`,
  `docs/architecture/coverage-ledger.md`,
  `docs/security/logging-audit.md`,
  `docs/unknowns/logging-audit.md`
- Rollback note:
  revert the summary-only error contract if the GUI bridge loses required local
  debugging signal or the test suite proves callers still rely on raw stderr
- Observability note:
  this is a redaction change on a logging-sensitive bridge. Recheck the local
  GUI slice in the logging audit after the edit so the docs match the code.
- Change type:
  behavior-preserving code cleanup

## 1. Dedicated bundled-plugin follow-up slice

- Exact files to change:
  `docs/architecture/repo-slices.md`,
  `docs/architecture/coverage-ledger.md`
- Why this change is safe now:
  it only narrows coverage claims and planning language that the current repo
  evidence already supports
- What behavior must remain unchanged:
  plugin discovery order, bundled plugin runtime behavior, packaged plugin data
  resolution, plugin validation behavior, and any loader or marketplace logic
- Tests or checks to run:
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md docs/architecture/repo-slices.md docs/architecture/coverage-ledger.md`
  and `git diff --check -- docs/review/safe-fix-plan.md docs/architecture/repo-slices.md docs/architecture/coverage-ledger.md`
- Docs to update:
  `docs/architecture/repo-slices.md`,
  `docs/architecture/coverage-ledger.md`
- Rollback note:
  revert the slice split and ledger wording if a later pass reviews bundled
  implementations together with shared plugin contracts
- Observability note:
  none; this is a coverage-truth fix, not a logging or telemetry change

## 2. Stronger `.claude/agents/` mirror guidance

- Exact files to change:
  `CLAUDE.md`,
  `docs/contributing/ai-workflow.md`,
  `docs/review/maintenance-harness.md`,
  `docs/unknowns/maintenance-harness.md`,
  `docs/unknowns/scenario-stress-test.md`
- Why this change is safe now:
  the repo already names the canonical source and sync path, so this batch only
  makes the reviewer rule explicit
- What behavior must remain unchanged:
  `tools/sync_claude_agents.py` copy behavior, the allowlisted file set,
  `.claude/agents/` contents, and maintenance-harness validator behavior
- Tests or checks to run:
  `npx --yes markdownlint-cli docs/review/safe-fix-plan.md CLAUDE.md docs/contributing/ai-workflow.md docs/review/maintenance-harness.md docs/unknowns/maintenance-harness.md docs/unknowns/scenario-stress-test.md`,
  `python3 tools/validate_contracts.py`,
  `tools/run_pytest.sh -q tests/test_validate_maintenance_harness.py tests/test_validate_contracts.py`,
  and `git diff --check -- docs/review/safe-fix-plan.md CLAUDE.md docs/contributing/ai-workflow.md docs/review/maintenance-harness.md docs/unknowns/maintenance-harness.md docs/unknowns/scenario-stress-test.md`
- Docs to update:
  `CLAUDE.md`,
  `docs/contributing/ai-workflow.md`,
  `docs/review/maintenance-harness.md`,
  `docs/unknowns/maintenance-harness.md`,
  `docs/unknowns/scenario-stress-test.md`
- Rollback note:
  revert the wording if the repo later removes the mirror or changes which path
  is canonical
- Observability note:
  none; this is steering clarity, not runtime instrumentation

## Not selected in this batch

- `tools/agent/*` path hardening stays out of scope here.
- The current stamp and trace artifact shape is persisted, documented, and
  validated by existing tests and docs.
- Any hardening there should be planned as a later, narrower artifact-contract
  pass instead of being folded into this first safe-fix batch.
