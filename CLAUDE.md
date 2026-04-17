# CLAUDE.md - MMO Compatibility Notes

`AGENTS.md` is the authoritative steering file for AI-assisted work in this
repo.

Claude sessions must follow `AGENTS.md` for:

- product principles and standing promises
- working modes and approval gates
- coverage-ledger rules
- unknown and evidence handling
- writing rules for comments, commits, docs, and PRs
- sensitive-data handling
- PR close-out expectations

If this file and `AGENTS.md` disagree, follow `AGENTS.md`.

## Read first

1. `PROJECT_WHEN_COMPLETE.md`
2. `AGENTS.md`
3. `docs/README.md`
4. `docs/semantic_contracts.md`

Use this file only for Claude-specific local workflow notes that are not worth
duplicating in `AGENTS.md`.

## Local Claude agent sync

Canonical Claude agent specs live in `docs/claude_agents/`.
The local `.claude/agents/` directory is a synced workspace copy.

Authority, edits, and review start from `AGENTS.md` and `docs/claude_agents/`.
Do not treat `.claude/agents/` as a primary steering or coverage-review
surface.

Refresh it with:

- `python tools/sync_claude_agents.py`

Run the sync after cloning or pulling when agent definitions matter.

## Allowlist-only cleanup

Do not do sweep deletions based on patterns, hashes, or name length.
Only these repo-local temp directories are safe cleanup targets:

- `.tmp_pytest/`
- `.tmp_codex/`
- `.tmp_claude/`
- `sandbox_tmp/`
- `.pytest_cache/`
- `pytest-cache-files-*` at repo root

Do not delete anything else unless the change is explicit and approved.

## Repo-safe validation runners

Confirm environment truth before coding or validating:

- active branch
- working directory
- interpreter or virtualenv
- whether the shell exposes `python`, `python3`, or only repo runners
- whether `pytest` and extras are installed
- exact validation command

Preferred pytest runners:

- `tools/run_pytest.sh -q`
- `tools/run_pytest.ps1 -q`
- `tools/run_pytest.cmd -q`

These runners set `PYTHONPATH=src` and repo-local temp roots.
Use `python tools/validate_contracts.py` as the main contract gate.

If the environment blocks full validation, report the exact blocker and do not
claim the change is fully verified.

## Packaged desktop and sidecar expectations

Keep packaged desktop behavior install-safe:

- no repo-root assumptions for runtime data
- bundled data must resolve through packaged paths
- the Tauri desktop app should use the packaged CLI sidecar, not a dev server
- preserve the frozen CLI sidecar contract based on
  `src/mmo/_frozen_cli_entrypoint.py` plus `mmo.cli:main`
- keep sidecar packaging, smoke checks, and bundled plugin resolution explicit
  and explainable

## Git safety reminders

Before committing:

- run `git status --porcelain`
- confirm only intended files are changed
- confirm nothing under `corpus/` or `private/` is staged
- stop if `.git/index.lock` exists and resolve the lock first

Keep changes focused. Do not quietly mix docs, cleanup, and behavior changes in
one review unless `AGENTS.md` clearly permits that pass.
