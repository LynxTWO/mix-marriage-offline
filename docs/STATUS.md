# Project Status

Last updated: 2026-03-16

This is the single-page milestone checklist for current delivery phases.

## Legend

- `[x]` done
- `[ ]` not done

## Contribution Rule

PRs must keep status tracking current: update `docs/STATUS.md` and
`docs/milestones.yaml` when milestone state actually changes, and update
`CHANGELOG.md` under `## [Unreleased]` when user-facing behavior changes.

## Roadmap Pointer

- Near-term completion work lives in `docs/06-roadmap.md#now`.
- Post-complete track lives in `docs/06-roadmap.md#later`.

## MVP-CLI

State: `done`

Definition of done:

- [x] CLI entrypoint and command routing are stable (`python -m mmo`).
- [x] Core validation contracts run in CI.
- [x] Cross-OS golden fixture workflows cover the baseline
      `classify -> bus-plan -> scene -> safe-render --render-many` path and the
      focused plugin-mode audio contract path.
- [x] Deterministic compare, project/session, and render-many workflows are
      user-facing CLI capabilities.

## MVP-GUI

State: `done`

Definition of done:

- [x] GUI contract docs and wireframes are documented.
- [x] GUI delivery names Tauri as the desktop app path and removes the retired
      CustomTkinter path from source, packaging, CI, and release workflows.
- [x] `docs/gui_parity.md` defines required Tauri screens/behaviors and is
      validated in CI.
- [x] Tauri desktop app builds in CI and uploads per-OS binaries.
- [x] The Tauri app can drive doctor/prepare/validate/analyze/render through the
      packaged sidecar.
- [x] The Tauri app exposes Scene, Results, and Compare as
      artifact-backed workflow screens with the same files/contracts the CLI
      writes.
- [x] The Tauri app supports the required scene-lock editing behavior.
- [x] Compare is loudness-matched by default and discloses the compensation
      used.
- [x] Cross-platform packaged desktop smoke tests are green.

## DSP Phase 1

State: `done`

Definition of done:

- [x] Core DSP/render primitives exist.
- [x] 32-channel, golden-fixture, plugin-mode audio, and fallback-sequence
      regression coverage exist.
- [x] Export finalization policy is documented as a stable public contract.
- [x] The stage graph is documented and fixed.
- [x] Typed plugin buffers and determinism purity guarantees are enforced
      end-to-end.
- [x] Multichannel safety-class declarations and bypass/restrict behavior are
      fully enforced with evidence, receipt rows, and regression coverage.

## Release Surface

State: `in_progress`

Definition of done:

- [x] `README.md`, `docs/README.md`, installer-facing docs, and release-copy
      sources match shipped capabilities and current limitations.
- [x] Windows, macOS, and Linux Tauri release bundles receive packaged-app
      smoke checks.
- [x] Standalone CLI binaries build on Windows, macOS, and Linux without a
      legacy Python GUI dependency.
- [ ] Human fresh-install signoff on release-candidate packaged artifacts is
      complete across Windows, macOS, and Linux.

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
- PR CI and release CI now build packaged Tauri desktop bundles on Windows,
  macOS, and Linux, launch the packaged app, and verify the bundled sidecar
  doctor plus validate/analyze/scene/render against a tiny fixture.
- Release-candidate hardening now includes a docs reality pass and clearer
  musician-facing failure guidance, but the final manual fresh-install signoff
  on packaged artifacts remains the last release-surface blocker before a v1
  tag.
