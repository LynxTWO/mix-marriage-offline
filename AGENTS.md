# Repository Guidelines

## Project Structure & Module Organization
- `docs/` contains design and contributor documentation (architecture, ontology, fixtures, validation rules).
- `ontology/` is the YAML source of truth for canonical IDs and vocabularies.
  - `ontology/policies/` holds policy registries and policy packs (for example downmix and gates).
- `schemas/` defines JSON Schemas for structured inputs/outputs.
- `fixtures/` contains deterministic fixture inputs and expected outputs used to validate policies and rules.
- `tools/` provides developer scripts for validation and fixtures.
- `tests/` holds automated tests (kept minimal early, expected to expand with new rules and fixtures).

## Build, Test, and Development Commands
- `python tools/validate_policies.py` validates policy registries and referenced policy packs.
- `python tools/run_policy_fixtures.py` runs policy fixtures and compares against expected `ISSUE.VALIDATION.*` IDs.

## Coding Style & Naming Conventions
- YAML/JSON: use consistent ordering, stable IDs, and explicit units.
- IDs are uppercase dot-delimited (e.g., `ISSUE.VALIDATION.MISSING_PACK`), and must remain stable once published.
- Scripts should be simple, deterministic, and output clear error messages for CI use.

## Testing Guidelines
- Prefer deterministic, fixture-driven checks for policy validation and schema compliance.
- Keep fixtures reproducible; add or update expectations when behavior changes intentionally.
- When adding a new rule or policy, add a matching fixture and a minimal test that proves it.

## Change Discipline
- Stable IDs only: do not rename or repurpose existing IDs; add new IDs instead.
- Update manifests/registries whenever new IDs or policy packs are added.
- Each PR/commit should include a brief, GitHub-ready change summary:
  - one-line imperative title,
  - 3–6 bullets describing what changed and why,
  - short list of files touched.

## Pull Request Notes
- Keep changes small and focused; avoid sweeping refactors.
- Call out any ontology or schema changes explicitly and link related fixtures.
