# docs/00-proposal.md

## Mix Marriage Offline

An open-source, offline mixing assistant for deterministic analysis,
scene-first delivery, and explainable render workflows.

---

## 1) What this is

Mix Marriage Offline (MMO) is a standalone desktop and CLI tool that works with
exported stems from any DAW.

Today it ships:

- deterministic analysis reports with evidence
- DAW-agnostic recall/export artifacts
- scene intent and render-planning contracts
- compare workflows for revision-to-revision review
- bounded safe-render and mix-once/render-many delivery
- translation QA, downmix QA, and headphone preview flows
- offline plugin/discovery workflows that do not require a network service

This is not a DAW plugin.
This is not "AI that mixes your song for you."
It is a technical co-pilot that helps engineers stay repeatable, auditable,
and conservative when the work gets complicated.

---

## 2) Why this matters

Mixing is two jobs wearing one hat.

### Objective engineering

Gain staging, loudness safety, clipping, masking, resonance, translation,
layout mapping, and delivery correctness.

### Subjective art

Mood, texture, space, hierarchy, energy, and emotional story.

The point of MMO is not to replace taste.
The point is to make the technical side more deterministic so taste has more
room to breathe.

---

## 3) The problem we are solving

- Technical QA is repetitive and easy to do inconsistently.
- Surround and immersive delivery introduces layout, ordering, and downmix
  failure modes that are hard to keep straight by hand.
- Comparing revisions fairly gets harder when loudness, routing, or delivery
  format changes between runs.
- Many tools are either black boxes or tightly bound to one DAW.

The opportunity is a conservative, testable system that captures intent once,
then reuses that intent across analysis, rendering, comparison, and delivery.

---

## 4) Key principles

### 4.1 Objective core vs subjective strategy

The stable core handles contracts, metering, validation, ordering, gates, and
receipts.
Plugins are where fast-changing detectors, resolvers, and render strategies
live.

### 4.2 Bounded authority

MMO can recommend freely, but it only auto-applies within explicit limits.
Higher-impact changes stay approval-gated.

### 4.3 Explainability

Issues, actions, compare diffs, and render receipts must say what changed, why
it changed, and what evidence backed that decision.

### 4.4 Reproducibility

Given the same stems, config, plugins, and version, MMO should produce the same
artifacts and the same contract hashes.

### 4.5 Offline by default

The tool must work without a cloud service.
External tools like FFmpeg are explicit runtime dependencies, not hidden remote
services.

---

## 5) How MMO works today

1. Validate stems, metadata, layouts, and reproducibility inputs.
2. Measure trusted meters and signal features.
3. Detect issues and produce evidence-backed recommendations.
4. Optionally build scene intent and render plans from the analyzed session.
5. Run bounded safe-render or render-many delivery when requested.
6. Export deterministic artifacts for reports, receipts, QA, and compare.

The same core contracts are used by the CLI, the Tauri desktop app, and the
legacy fallback GUI.

---

## 6) What MMO outputs

### 6.1 Analysis artifacts

- `report.json`
- optional report PDF
- recall CSV/TXT exports

### 6.2 Scene and render artifacts

- `scene.json`
- `render_plan.json`
- `render_report.json`
- `render_manifest.json`
- `receipt.json`
- optional `deliverables_index.json` and `listen_pack.json`

### 6.3 Compare artifacts

- `compare_report.json`
- optional compare PDF
- fair-listen `loudness_match` disclosure when render QA companions exist

### 6.4 Audio deliverables

- conservative baseline renders for supported targets
- optional render-many batches from one scene
- optional deterministic headphone preview WAVs

---

## 7) Surround, immersive, and headphone support

This is not only a future direction anymore.
It is already part of the shipped product surface.

Current capabilities include:

- layout-aware analysis and rendering
- first-class render targets from stereo through `9.1.6`
- binaural/headphone delivery and preview flows
- downmix QA and rendered similarity gates
- five I/O ordering standards:
  `SMPTE`, `FILM`, `LOGIC_PRO`, `VST3`, and `AAF`

Important note:
Dolby Atmos still involves licensing and proprietary tooling.
MMO focuses on open, practical channel-based workflows, deterministic receipts,
and downmix/translation confidence rather than claiming to replace official
renderers.

---

## 8) What makes MMO different

- It is stem-aware and scene-aware, not just a final-file processor.
- It treats compare as a first-class workflow, not an afterthought.
- It treats delivery layout/order correctness as part of the product, not just
  user discipline.
- It is deterministic and test-driven instead of opaque.
- It is extensible without giving plugins authority over the core contracts.

---

## 9) Who this is for

- Mixers who want repeatable technical QA and delivery receipts
- Artists who want the technical layer handled conservatively
- Teams that need project/session artifacts and long-lived rerun workflows
- Developers and DSP contributors who want strict contracts and fixtures
- Surround-curious creators who want guardrails without proprietary lock-in

---

## 10) Current shipped capabilities

- deterministic analysis and export flows
- deterministic scene/render contracts
- compare workflow with artifact-backed fair-listen context
- render-many delivery from one scene to multiple targets
- supported stereo, surround, immersive, and binaural targets
- Tauri desktop workflow path plus legacy fallback GUI
- offline plugin marketplace, project/session persistence, and watch-folder
  automation

---

## 11) Still not complete yet

- Tauri scene-lock editing parity is still open.
- Cross-platform packaged desktop smoke coverage is still incomplete.
- The legacy fallback GUI remains available during that gap, but it is not the
  long-term primary path.
- MMO remains conservative about licensed Atmos-specific claims and workflows.

---

## 12) Where to go next

Read these next:

- `docs/00-quickstart.md`
- `docs/02-architecture.md`
- `docs/15-target-selection.md`
- `docs/18-channel-standards.md`
- `docs/manual/00-manual-overview.md`
