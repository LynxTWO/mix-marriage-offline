# Repository Guidelines

## Cross-platform rule (Linux, Windows, macOS)

All changes must remain install-safe and cross-platform:

- No repo-root assumptions for data or tool execution.
- Use `mmo.resources` + packaged data for schemas/ontology/presets.
- Avoid OS-specific paths and shell behaviors.
- Tests must pass on Windows/macOS/Linux in CI.

## Project Structure & Module Organization

- `docs/` contains design and contributor documentation (architecture, ontology,
  fixtures, validation rules).
- `ontology/` is the YAML source of truth for canonical IDs and vocabularies.
  - `ontology/policies/` holds policy registries and policy packs (for example
    downmix and gates).
- `schemas/` defines JSON Schemas for structured inputs/outputs.
- `fixtures/` contains deterministic fixture inputs and expected outputs used to
  validate policies and rules.
- `tools/` provides developer scripts for validation and fixtures.
- `tests/` holds automated tests (kept minimal early, expected to expand with
  new rules and fixtures).

## Build, Test, and Development Commands

- `python tools/validate_policies.py` validates policy registries and referenced
  policy packs.
- `python tools/run_policy_fixtures.py` runs policy fixtures and compares
  against expected `ISSUE.VALIDATION.*` IDs.

## Environment Preflight

Before implementing or validating a change, confirm:
- active branch and working directory
- correct Python interpreter / virtualenv for this repo
- whether `pytest` and required extras are installed in that environment
- exact test command that will be used for verification
- whether `PYTHONPATH=src` or repo runners are required in this host environment

## Coding Style & Naming Conventions

- YAML/JSON: use consistent ordering, stable IDs, and explicit units.
- IDs are uppercase dot-delimited (e.g., `ISSUE.VALIDATION.MISSING_PACK`), and
  must remain stable once published.
- Scripts should be simple, deterministic, and output clear error messages for
  CI use.

## Testing Guidelines

- Prefer deterministic, fixture-driven checks for policy validation and schema
  compliance.
- Keep fixtures reproducible; add or update expectations when behavior changes
  intentionally.
- When adding a new rule or policy, add a matching fixture and a minimal test
  that proves it.
- Run targeted tests for the changed contract first, then adjacent regressions, then broader smoke tests if needed.
- A test command that did not actually execute in the correct environment does not count as validation.
- If validation is blocked by environment issues, report the exact blocker and do not present the change as fully verified.

## Change Discipline

- Stable IDs only: do not rename or repurpose existing IDs; add new IDs instead.
- Update manifests/registries whenever new IDs or policy packs are added.
- Each PR/commit should include a brief, GitHub-ready change summary:
  - one-line imperative title,
  - 3�6 bullets describing what changed and why,
  - short list of files touched.
- Prefer one shared resolver or contract implementation per concept; do not add parallel desktop-only, CLI-only, or render-only logic unless the divergence is intentional and documented.
- Verify the reported gap before implementing a fix. If the behavior already exists, improve visibility or coverage instead of duplicating enforcement.

## Pull Request Notes

- Keep changes small and focused; avoid sweeping refactors.
- Call out any ontology or schema changes explicitly and link related fixtures.
- Do not treat artifact existence as proof of success. If output validity matters, expose explicit machine-readable status and failure reasons.
- Preserve diagnostic artifacts when useful, but keep diagnostics separate from successful deliverables.

## Living Docs Convention

- `PROJECT_WHEN_COMPLETE.md` is the progress/status log and definition-of-done
  tracker; update checklist items as work lands.
- `CHANGELOG.md` is release-facing change summary; keep `Unreleased` current for
  user-visible or contract-relevant changes.
- `GEMINI.md` is AI/operator guidance; keep it aligned with current repo
  workflows and non-negotiables.
- These files are intentionally tracked in git and should be updated alongside
  relevant code changes.
