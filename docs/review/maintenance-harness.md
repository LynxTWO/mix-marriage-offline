<!-- markdownlint-disable-file MD013 -->

# Maintenance Harness

This note records the anti-dark-code maintenance assets added after the first
repo-wide mapping and review passes.

## Assets Updated

- `.github/pull_request_template.md`
- `docs/contributing/ai-workflow.md`
- `docs/README.md`
- `tools/validate_maintenance_harness.py`
- `tools/validate_contracts.py`
- `tests/test_validate_maintenance_harness.py`

## Hard Gates

These checks run automatically through `python tools/validate_contracts.py`.

- Required maintenance assets must exist.
- The PR template must keep the plain change record fields and the required
  checklist items.
- The contributor workflow and maintenance note must keep their required
  sections.
- `docs/README.md` must link the contributor workflow.
- The narrow obvious sensitive-logging rule must pass.

The logging rule is intentionally small. It only looks for same-line logging
calls with obvious sensitive markers. It is an early-drift check, not proof
that repo logging is safe.

## Reviewer Checks Only

These still depend on human review.

- Whether a touched area needed approval under `AGENTS.md`
- Whether a risky slice changed enough to move the coverage ledger
- Whether a new unknown should be written down
- Whether a hidden control-plane path or support tool was touched
- Whether anti-dark-code comments drifted from the code
- Whether a release-path, rollback, or observability note now needs an update

## Doc Triggers

Require a doc update when a change touches:

- architecture or trust boundaries
- protected areas
- support tooling or release control planes
- critical flows or hidden runtime entrypoints
- logging, telemetry, traces, or machine-readable outputs with sensitive data

Use the smallest practical source of truth. Typical choices are the system map,
coverage ledger, a review note, a runbook, or an unknowns file.

## Protected Areas Requiring Approval

The harness follows `AGENTS.md`. Approval is still required before edits that
touch auth, access control, secrets, crypto, plugin execution boundaries,
audio-changing render or export paths, cleanup or packaged-data behavior,
schema or ontology removals, concurrency risks, GUI RPC, Tauri sidecars,
release tooling, or privileged support tooling.

## Logging And Telemetry Checks

The automated check looks for obvious same-line mistakes such as:

- `print(...password...)`
- `logger.error(...access_token...)`
- `console.error(...cookie...)`

The harness does not cover:

- stderr forwarding
- machine-readable JSON stdout
- NDJSON trace uploads
- shared receipts or artifact attachments
- analytics, crash reporting, or trace SDK behavior outside the repo

Use `docs/security/logging-audit.md` for those paths.

## Remaining Human-Review Limits

- GitHub does not hard-enforce PR template completion in this repo.
- Release signing, Pages deploy, and installer behavior still cross out-of-repo
  boundaries.
- `.claude/agents` mirror drift still depends on the sync path and human
  review.
- The harness keeps low-risk edits light. It does not force ledger churn for
  every small change.

## Future Harness Support

Future passes may need tighter support for:

- bundled plugin implementation review
- support-tool and release-control-plane approval routing
- machine-readable output and trace escape review
- any new runtime, control-plane path, or protected area added later
