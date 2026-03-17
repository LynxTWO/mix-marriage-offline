# Roadmap

This roadmap is split into two tracks:

- `NOW`: work required to reach `PROJECT_WHEN_COMPLETE.md`.
- `LATER`: post-complete enhancements that do not block the completion gate.

## NOW

Only true v1 completion blockers belong here. The remaining blocker is small
and explicit: final human fresh-install signoff on the release-candidate
desktop artifacts. Optional GUI maturity and preset polish items live in
`PROJECT_WHEN_COMPLETE.md` section 9 and in `LATER` below.

### Release Surface

- Goal: make the shipped surface truthful and verifiable before calling v1 done.
- Completion gate: source-tree pytest is not enough; Windows/macOS/Linux
  packaged desktop artifacts must launch and pass bundled-sidecar smoke in CI
  and release builds before v1 can be considered complete.
- Open blockers:
- automated packaged smoke is already green in CI and release workflows
- docs and common failure messages now match the shipped desktop workflow more
  closely
- remaining blocker: complete one human fresh-install walkthrough on the
  release-candidate packaged artifacts before tagging v1

### Tauri Workflow Parity

- Goal: keep the shipped Tauri desktop app aligned with the artifact-backed
  workflow contract, not just a buildable shell.
- Canonical checklist: [gui_parity.md](gui_parity.md)
- Open blockers:
- none currently

### DSP And Plugin Contract Closure

- Goal: close the remaining public-contract gaps in the DSP and plugin boundary.
- Open blockers:
- none currently

## LATER

Post-complete work that should not block `PROJECT_WHEN_COMPLETE.md`:

- follow-on preset surface polish beyond the shipped bounded report-driven
  preview safety contract
- extra compare visual polish: dynamics/spatial scopes, explainability overlays,
  richer "what changed" summaries
- artist-first preset surfaces: macro controls, mood/texture selectors,
  safe-mode polish
- reference matcher guidance, A/B/C/D morphing, history scrub, and
  soundstage/masking views
- advanced spatial polish and psychoacoustic refinement beyond deterministic
  safety baselines
- additional very-large-layout routing/polish work beyond current v1 targets
- DAW hosting and deeper integration surfaces beyond current offline contract
  needs
- additional exploratory workflows that trade strict scope for creative
  expansion
