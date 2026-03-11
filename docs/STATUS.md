# Project Status

Last updated: 2026-03-11

This is the single-page milestone checklist for current delivery phases.

## Legend
- `[x]` done
- `[ ]` not done

## Contribution Rule
PRs must keep status tracking current: update `docs/STATUS.md` and `docs/milestones.yaml` when milestone state actually changes, and update `CHANGELOG.md` under `## [Unreleased]` when user-facing behavior changes.

## Roadmap Pointer
- Near-term completion work lives in `docs/06-roadmap.md#now`.
- Post-complete track lives in `docs/06-roadmap.md#later`.

## MVP-CLI
State: `in_progress`

Definition of done:
- [x] CLI entrypoint and command routing are stable (`python -m mmo`).
- [x] Core validation contracts run in CI.
- [x] Deterministic fixture workflows exist for baseline behavior.
- [ ] End-to-end golden-path project walkthrough is fully CI-covered.

## MVP-GUI
State: `in_progress`

Definition of done:
- [x] GUI contract docs and wireframes are documented.
- [x] GUI delivery names one primary plan (Tauri) and one fallback plan
  (CustomTkinter) until parity.
- [x] `docs/gui_parity.md` defines required Tauri screens/behaviors and is
  validated in CI.
- [x] Tauri desktop scaffold builds in CI and uploads per-OS binaries.
- [ ] GUI shell can load/write the same project artifacts as CLI.
- [ ] GUI actions map 1:1 to existing deterministic contracts.
- [ ] Cross-platform desktop smoke tests are green.

## DSP Phase 1
State: `planned`

Definition of done:
- [x] Core DSP/render primitives exist.
- [ ] Phase 1 meter/gate pack is finalized.
- [ ] Phase 1 resolver pack has fixture coverage.
- [x] Repeat runs produce byte-stable outputs for covered fixtures.

## Status System
State: `done`

Definition of done:
- [x] `CHANGELOG.md` follows Keep a Changelog style with dated entries.
- [x] `docs/milestones.yaml` defines machine-readable milestone state.
- [x] `tools/validate_milestones.py` is part of contract validation.

## CI Test Notes
- Default CI pytest jobs run with xdist.
- CI keeps a serial pytest job to detect order dependencies.
- Serial-only xdist tests: none currently.
- GitHub Actions workflow pins now use Node 24-ready majors for the main
  checkout, Python, Node, and artifact actions where upstream publishes them;
  the Pages-specific actions remain on their latest upstream majors.
- GitHub-hosted runner labels are pinned to `ubuntu-24.04`, `windows-2025`, and
  `macos-15`, while GUI/Tauri dev paths now target Node 24 LTS and Rust 1.94.0.
