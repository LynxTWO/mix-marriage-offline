# Changelog
All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
### Added
- Placeholder for in-progress changes.
- Clarified living-doc roles: `PROJECT_WHEN_COMPLETE.md` (progress/status), `CHANGELOG.md` (release summary), and `GEMINI.md` (AI/operator guidance).
- Added local-only ignore rules for temp/build artifacts (`.mmo_tmp`, `mmo_tmp`, `.tmp_pip`, pip temp caches, `.venv_wsl`, `build`).

## [2026-02-17]
### Added
- Added a repo-native status and milestones system with `docs/STATUS.md` and `docs/milestones.yaml`.
- Added `tools/validate_milestones.py` with deterministic output for machine validation.
- Added validator tests for happy-path and deterministic error ordering.

### Changed
- Updated `tools/validate_contracts.py` to run `DOCS.MILESTONES`.
