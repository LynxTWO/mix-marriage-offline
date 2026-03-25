# Roadmap

This roadmap is split into two tracks:

- `NOW`: current stabilization work that keeps the shipped surface truthful,
  explainable, and aligned with `PROJECT_WHEN_COMPLETE.md`.
- `LATER`: post-stabilization enhancements that do not block the completion
  gate.

## NOW

The `1.0.0` tag exists and the packaged public surface is shipped. Current
`NOW` work is conservative stabilization: docs truthfulness, semantic-contract
clarity, workflow polish, and other changes that keep the release surface
honest without redesigning it. No stop-ship public blockers are open at the
moment.

### Release Surface And Truthfulness

- Goal: keep the shipped surface truthful and verifiable after the tag, not
  just truthful enough to reach the tag.
- Completion gate: source-tree pytest is not enough; Windows/macOS/Linux
  packaged desktop artifacts must launch and pass bundled-sidecar smoke in CI
  and release builds before v1 can be considered complete.
- Open blockers: no stop-ship blockers currently; follow-on work is contract
  clarity and stabilization, not a reopened release gate

### Tauri Workflow Parity

- Goal: keep the shipped Tauri desktop app aligned with the artifact-backed
  workflow contract, not just a buildable shell.
- Canonical checklist: [gui_parity.md](gui_parity.md)
- Open blockers: no required parity blockers currently; continue workflow and
  wording polish without creating desktop-only semantics

### DSP And Plugin Contract Closure

- Goal: close the remaining public-contract gaps in the DSP and plugin boundary.
- Open blockers: no stop-ship blockers currently; keep tightening semantic
  clarity as plugin and render contracts evolve

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
