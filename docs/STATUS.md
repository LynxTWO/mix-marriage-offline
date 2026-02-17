# Project Status

Last updated: 2026-02-17

This is the single-page milestone checklist for current delivery phases.

## Legend
- `[x]` done
- `[ ]` not done

## MVP-CLI
State: `in_progress`

Definition of done:
- [x] CLI entrypoint and command routing are stable (`python -m mmo`).
- [x] Core validation contracts run in CI.
- [x] Deterministic fixture workflows exist for baseline behavior.
- [ ] End-to-end golden-path project walkthrough is fully CI-covered.

## MVP-GUI
State: `planned`

Definition of done:
- [x] GUI contract docs and wireframes are documented.
- [ ] GUI shell can load/write the same project artifacts as CLI.
- [ ] GUI actions map 1:1 to existing deterministic contracts.
- [ ] Cross-platform desktop smoke tests are green.

## DSP Phase 1
State: `planned`

Definition of done:
- [x] Core DSP/render primitives exist.
- [ ] Phase 1 meter/gate pack is finalized.
- [ ] Phase 1 resolver pack has fixture coverage.
- [ ] Repeat runs produce byte-stable outputs for covered fixtures.

## Status System
State: `done`

Definition of done:
- [x] `CHANGELOG.md` follows Keep a Changelog style with dated entries.
- [x] `docs/milestones.yaml` defines machine-readable milestone state.
- [x] `tools/validate_milestones.py` is part of contract validation.
