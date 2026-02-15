# CLAUDE.md — Mix Marriage Offline (MMO)

This repo is **Mix Marriage Offline (MMO)**: an offline, deterministic stem-folder mixing assistant.
The system does objective analysis + safe, explainable planning. Humans own intent and taste.

Primary goals:
- Deterministic outputs (same inputs/settings => same outputs).
- Explainability everywhere (what/why/where/confidence).
- Strict schemas (JSON schema, `additionalProperties: false`).
- Bounded authority (no “surprise” destructive actions).
- Offline-first (no network assumptions in core flows).

## Cross-platform + distributable install contract (Linux, Windows, macOS)

MMO must run correctly in these two modes:
1) Repo checkout (dev): running from the git workspace.
2) Installed package (users): running from a wheel/sdist install where repo-root folders are not available.

Rules:
- Never assume a repo-root path for loading schemas/ontology/presets/tools.
  Use a single resolver (e.g., `mmo.resources`) and packaged data via `importlib.resources`, with env overrides.
- No OS-specific path assumptions:
  - Use `pathlib` for filesystem paths.
  - Do not hardcode `/`-absolute paths, drive letters, or shell-specific locations.
  - Tests must not assert raw path separators.
- Do not shell out to repo scripts by filesystem path.
  Prefer `python -m mmo.tools.<module>` for internal tools and keep CLIs install-safe.
- External dependencies (FFmpeg, etc.) are optional unless explicitly required by a feature.
  Detect capabilities, gate features, and emit clear “how to enable” messages.
- CI must test a matrix: ubuntu-latest, windows-latest, macos-latest, and the supported Python range.
- Encoding: always read/write text as UTF-8 unless a file format requires otherwise.

## Repo map (high level)
- `src/mmo/core/` deterministic core logic (planners, registries, classifiers, reports).
- `src/mmo/cli.py` CLI entrypoints; outputs must be stable (ordering, formatting).
- `ontology/` canonical IDs + registries (roles, lexicons, translation profiles, etc).
- `schemas/` JSON schemas; keep strict; update contracts + tests together.
- `tools/` developer tools (validators, corpus scanners, pytest runners).
- `tests/` deterministic tests; prefer fixtures; assert stable stdout/stderr.

## Non-negotiables
1) Determinism:
- Stable sorting for IDs, rows, and JSON keys where relevant.
- No timestamps, random IDs, or environment-dependent output.
- When output is JSON: use stable serialization (e.g., `indent=2, sort_keys=True` where appropriate).

2) Schema discipline:
- If you add/change a payload, update schema + validate + tests in the same PR.
- Prefer strict schemas with `additionalProperties: false`.

3) Temp + artifact hygiene (Windows + OneDrive safe)
DO NOT do “sweep” deletions based on patterns or name length.
DO NOT delete arbitrary root folders.

Allowlist-only cleanup is required.
Only delete these repo-local temp dirs if they exist:
- `.tmp_pytest/`
- `.tmp_codex/`
- `.tmp_claude/` (new for Claude tooling)
- `sandbox_tmp/`
- `.pytest_cache/`
- `pytest-cache-files-*` (repo root only, if created by pytest)

Never delete or modify anything else unless it is an explicit PR change.

4) Never commit private/local data
These must remain untracked/ignored:
- `corpus/**`
- `private/**`
- `*.corpus.jsonl`
- `*.corpus.stats.json`
- `*.suggested.yaml` (if generated from private scans)

If you need to use local scan outputs, treat them as *inputs only* and do not stage them.

## Running tests safely (Windows)
Prefer the repo runners that force temp locations into the repo:
- `tools\run_pytest.cmd -q`
- `tools\run_pytest.cmd -q tests/test_tools_stem_corpus_scan.py`
- PowerShell alternative:
  `powershell -NoProfile -ExecutionPolicy Bypass -File tools\run_pytest.ps1 -q`

If pytest capture/tempfile fails in this host environment, you may run with `-s` for diagnosis:
- `tools\run_pytest.cmd -q -s <test_path>`

Always run:
- `python tools/validate_contracts.py`
…and for UI examples when touched:
- `python tools/validate_ui_examples.py`

## Git safety checks before commit
Before committing:
- `git status --porcelain` must show only intended changes.
- Confirm nothing under `corpus/` or `private/` is staged.
- If `.git/index.lock` exists, stop and fix the lock (often OneDrive or a crashed git process).

## PR finish requirements
Each PR must include:
- A GitHub-ready Change Summary (title + bullets + files touched).
- Validation commands actually run (and notes if the environment blocks full suite).
- Clean working tree at end (or a clear note about harmless untracked temp dirs).