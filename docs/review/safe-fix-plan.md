<!-- markdownlint-disable-file MD013 -->

# Safe Fix Plan

This plan covers the first safe remediation batch from
`docs/review/remediation-backlog.md`.

It only includes items that are clearly evidenced, not approval-gated, and
small enough to review as docs-only work.

## Current protected-area batch

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
