<!-- markdownlint-disable-file MD013 -->

# Safe Fix Plan

This plan covers the first safe remediation batch from
`docs/review/remediation-backlog.md`.

It only includes items that are clearly evidenced, not approval-gated, and
small enough to review as docs-only work.

## Current protected-area batch

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
