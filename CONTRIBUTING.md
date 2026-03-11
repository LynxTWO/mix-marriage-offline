# Contributing to Mix Marriage Offline (MMO)

Thanks for helping build an offline, deterministic mixing assistant.

If you contribute with AI tools, that is fine. The human submitting the PR is still responsible for correctness, safety, determinism, and license hygiene.

## Before you start

- Read the docs index: `docs/README.md`.
- Follow the milestone tracking rule: PRs that move work must update `docs/STATUS.md` and `docs/milestones.yaml`.
- Follow the PR checklist in `.github/pull_request_template.md`.

## Project rules that matter

1) Determinism is a contract.

- Same inputs + settings must produce the same outputs.
- Avoid timestamps, random IDs, environment-dependent ordering, and locale-specific formatting.

1) Schemas and ontology are not optional.

- If you change any payload shape, update the JSON schema in the same PR.
- Prefer strict schemas and stable ordering in outputs.

1) Bounded authority stays conservative.

- Recommendations can be broad.
- Auto-apply must remain low-risk unless a policy explicitly allows more.

## Development setup

### Python (core/CLI)

- Python 3.12+ recommended.
- Install in editable mode:
  - `python -m pip install -e ".[dev,truth,pdf]"`

### Node (GUI tests)

- Node 24 LTS recommended (`.nvmrc` pins the repo to major `24`).
- In `gui/`:
  - `npm ci`
  - `npm test`

## Validation and tests

Run these before opening a PR:

- `python tools/validate_contracts.py`
- Tests:
  - Linux/macOS: `MMO_PYTEST_N=auto tools/run_pytest.sh -q`
  - Windows: `.\tools\run_pytest.ps1 -q`

If you cannot run something due to your environment, say exactly what you ran and what you could not run in the PR description.

## What to work on

Good first contributions:

- Docs fixes and export guides.
- New fixtures that catch real-world stem export failures.
- Ontology additions with clear IDs, descriptions, and examples.
- Small validators that improve error messages and ordering.

Bigger contributions:

- New meters with tests and fixture coverage.
- Downmix QA improvements and gate tuning.
- Plugin packs that declare semantics clearly and pass contract validation.

## Submitting a PR

- Keep PRs small and scoped.
- Include a short change summary and the validation commands you ran.
- Update `CHANGELOG.md` under `## [Unreleased]` if user-facing behavior changed.
- If you add files, ensure licensing and attribution are clear.

## Code of Conduct

By participating, you agree to the project Code of Conduct in `CODE_OF_CONDUCT.md`.
