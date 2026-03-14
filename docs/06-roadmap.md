# Roadmap

This roadmap is split into two tracks:

- `NOW`: work required to reach `PROJECT_WHEN_COMPLETE.md`.
- `LATER`: post-complete enhancements that do not block the completion gate.

## NOW

Only true v1 completion blockers belong here. Optional GUI maturity and preset
polish items live in `PROJECT_WHEN_COMPLETE.md` section 9 and in `LATER` below.

### Release Surface

- Goal: make the shipped surface truthful and verifiable before calling v1 done.
- Open blockers:
- [PWC: release-facing docs / README / release copy reflect shipped capabilities](../PROJECT_WHEN_COMPLETE.md)
- [PWC: packaged binary + installer smoke checks run on Windows/macOS/Linux](../PROJECT_WHEN_COMPLETE.md)

### Tauri Workflow Parity

- Goal: land the primary desktop app as a real artifact-backed workflow, not
  just a buildable shell.
- Canonical checklist: [gui_parity.md](gui_parity.md)
- Open blockers:
- [PWC: compare is a first-class user-facing workflow across CLI and GUI](../PROJECT_WHEN_COMPLETE.md)
- [PWC: primary Tauri GUI exposes validate -> analyze -> scene -> render -> results -> compare using CLI artifacts](../PROJECT_WHEN_COMPLETE.md)

### DSP And Plugin Contract Closure

- Goal: close the remaining public-contract gaps in the DSP and plugin boundary.
- Open blockers:
- [PWC: processing decisions stay user-requested, approval-gated, or confidence-gated](../PROJECT_WHEN_COMPLETE.md)
- [PWC: typed plugin buffers with explicit channel semantics](../PROJECT_WHEN_COMPLETE.md)
- [PWC: plugin determinism purity constraints](../PROJECT_WHEN_COMPLETE.md)
- [PWC: plugins declare multichannel/layout safety class](../PROJECT_WHEN_COMPLETE.md)
- [PWC: engine restricts or bypasses unsafe multichannel plugins with evidence](../PROJECT_WHEN_COMPLETE.md)

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
