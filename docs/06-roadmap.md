# Roadmap

This roadmap is split into two tracks:

- `NOW`: work required to reach `PROJECT_WHEN_COMPLETE.md`.
- `LATER`: post-complete enhancements that do not block the completion gate.

## NOW

Top priorities:

- Tauri desktop app + parity checklist
- Plugin audio contract completion
- Fallback sequencer + LFE approvals
- Golden fixtures and tests

PR placeholder convention used below:

- Replace `OWNER/REPO` and `TBD` when opening a real PR.
- Placeholder: [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)

### Tauri Desktop App Parity Checklist

- Goal: deliver a cross-platform Tauri desktop workflow that is parity-safe with CLI contracts and design guidance.
- Open checklist references:
- [PWC: loudness-compensated preview/A-B plus disclosed compensation](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: feature-driven presets without loudness jump surprises](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: GUI workflow parity with CLI](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: GUI design-system alignment](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: numeric controls support direct text entry](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: drag controls support fine-adjust modifier](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: units always visible with consistent rounding/display](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: A/B compare loudness compensation by default](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: control family coverage (knob/fader/toggle/etc.)](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: metering coverage (peak/RMS/true-peak/LUFS/multichannel)](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: visualizer coverage (waveform/spectrum/spectrogram/EQ)](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: dynamics/spatial views (GR/phase/vectorscope/transfer)](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: explainability overlays and change summary](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: macro controls with disclosed parameter mapping](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: mood/texture selector strategies](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: safe mode toggle for bounded creativity](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: reference matcher plus track/bus ranking guidance](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: A/B/C/D morphing controls](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: optional history scrub/timeline view](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: optional soundstage plus masking views](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: GUI layout validator CI coverage](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: global GUI scale / responsive scaling](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)

### Plugin Audio Contract Completion

- Goal: finish plugin/runtime contracts so channel semantics, determinism, and bounded-authority behavior are explicit and enforceable.
- Open checklist references:
- [PWC: plugin routing uses `ProcessContext.channel_order`](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: plugins cannot override explicit user intent](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: support at least 32 channels end-to-end](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: processing decisions must be approved/disclosed/undoable as required](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: typed plugin buffers with explicit channel semantics](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: plugin determinism purity constraints](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: medium/high-impact changes emitted as recommendations](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: object-vs-bed routing changes treated as high-impact](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: plugins declare multichannel/layout safety class](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: enforced fallback when plugin multichannel safety is not guaranteed](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)

### Fallback Sequencer and LFE Approvals

- Goal: complete the fallback sequence and explicit LFE approval path with deterministic reporting and safety re-checks.
- Open checklist references:
- [PWC: corrective-filter recommendations require approval and re-QA/backoff](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: explicit LFE stems are never silently retuned to mains](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: deterministic export finalization policy](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: explicit sample-rate handling policy](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: stable documented stage graph](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: per-stage evidence plus timing in render report](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: documented fallback strategy when gates fail](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: non-silent failure reporting with fallback attempts](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: rendered-file metadata traceability](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)

### Golden Fixtures and Tests

- Goal: close remaining CI and fixture-based completeness gates.
- Open checklist references:
- [PWC: ontology change policy is additive or version-bumped with migrations](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: golden fixtures prove required contracts](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: golden-audio test matrix coverage](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)
- [PWC: regression test for failed downmix-gate fallback sequence](../PROJECT_WHEN_COMPLETE.md) - [PR: TBD](https://github.com/OWNER/REPO/pull/TBD)

## LATER

Post-complete work that should not block `PROJECT_WHEN_COMPLETE.md`:

- advanced spatial polish and psychoacoustic refinement beyond deterministic safety baselines
- fancy UI extras and experimental visualization layers that exceed parity requirements
- DAW hosting and deeper integration surfaces beyond current offline contract needs
- additional exploratory workflows that trade strict scope for creative expansion
