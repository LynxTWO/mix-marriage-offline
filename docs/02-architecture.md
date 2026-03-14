# docs/02-architecture.md

## Mix Marriage Offline Architecture

### Offline stems in. Deterministic artifacts out. One scene, many deliveries

---

## 1) System overview

Mix Marriage Offline (MMO) is a standalone, offline toolchain for stem-folder
analysis, scene-first delivery, and explainable compare/render workflows.

As shipped today, MMO produces and consumes a family of deterministic artifacts:

- `report.json` for analysis output
- `scene.json` for layout-agnostic mix intent
- `render_plan.json` for target/job expansion
- `render_report.json` and `render_manifest.json` for executed delivery runs
- `receipt.json` and `render_qa.json` for audit and QA trails
- `compare_report.json` for revision comparison

The CLI, the packaged Tauri desktop app, and the fallback CustomTkinter GUI all
work against those same contracts.

---

## 2) Design constraints

- Offline first. No cloud dependency.
- Cross-platform install safety for Linux, Windows, and macOS.
- Deterministic outputs given identical inputs and settings.
- Explainability is mandatory for issues, gates, receipts, and compare diffs.
- Plugin extensibility must not weaken core contracts.
- Internal processing stays canonical even when I/O ordering standards differ.

---

## 3) Inputs and assumptions

### 3.1 Stem/session inputs

- Stems start at `0:00`.
- Sample rate and bit depth should be consistent inside a session.
- Roles and layouts are inferred or assigned explicitly.
- FFmpeg/ffprobe are expected for core decode, metadata, and QA workflows.

### 3.2 Layout-aware inputs

MMO accepts stereo, surround, immersive, and headphone-target workflows.

Current first-class target families include:

- stereo and front-stage layouts
- surround layouts through `7.1`
- immersive layouts through `9.1.6`
- first-class `LAYOUT.BINAURAL` / `TARGET.HEADPHONES.BINAURAL`

At the I/O boundary MMO supports five channel-ordering standards: `SMPTE`,
`FILM`, `LOGIC_PRO`, `VST3`, and `AAF`.

---

## 4) Core artifact model

### 4.1 Analysis artifacts

- `report.json`
- optional report PDF
- recall CSV/TXT exports

### 4.2 Scene and render artifacts

- `scene.json`
- `render_plan.json`
- `render_report.json`
- `render_manifest.json`
- `receipt.json`
- optional `deliverables_index.json` and `listen_pack.json`

### 4.3 Compare artifacts

- `compare_report.json`
- optional compare PDF
- optional fair-listen `loudness_match` context from sibling `render_qa.json`

---

## 5) Canonical DSP stage graph

MMO uses one canonical DSP stage graph. The names below are normative even when
specific CLI commands or reports expose a narrower subset of the pipeline.

1. **Input normalization and alignment**
   - Purpose: decode inputs, normalize channel-order semantics to internal
     canonical `SMPTE`, and apply only conservative boundary operations such as
     explicit resampling or alignment fixes.
   - Audio mutation: **boundary-only**. This stage may change representation
     (sample rate, channel ordering, alignment) but must not make taste-driven
     tonal, balance, or spatial decisions.
   - Primary artifacts: validation output in `report.json`, resampling receipts,
     and pre-render stage notes.
2. **Analysis / metering**
   - Purpose: measure features, meters, and evidence used for validation and
     later decisions.
   - Audio mutation: **advisory only**. This stage never changes samples.
   - Primary artifacts: `report.json` issues, evidence, feature rows, and
     recommendations inputs.
3. **Scene inference**
   - Purpose: derive or refine layout-agnostic intent, confidence, and target
     recommendations.
   - Audio mutation: **advisory only**. It writes intent and confidence, not
     audio.
   - Primary artifacts: `scene.json`, render-intent blocks, target-selection
     context, and recommendation state.
4. **Pre-render corrective pass**
   - Purpose: apply bounded-authority corrective DSP before the final render.
   - Audio mutation: **yes**. This is the first stage allowed to mutate program
     audio, and only within declared low-risk or approved authority.
   - Primary artifacts: DSP hook receipts/events and renderer receipts tied to
     `pre_bus_stem`, `bus`, and `post_master` boundaries.
5. **Render pass**
   - Purpose: convert scene intent into a target layout using routing, downmix,
     placement, and other renderer-declared behavior.
   - Audio mutation: **yes**. This stage owns the target-layout render.
   - Primary artifacts: output audio files, `render_manifest.json`,
     `apply_manifest.json`, and render job output rows.
6. **Post-render QA**
   - Purpose: measure rendered outputs, apply gates, compare downmix
     similarity/correlation risk, and decide whether to accept, retry, or fail.
   - Audio mutation: **advisory only**. QA measures audio and can trigger a
     re-render or failure, but it does not silently rewrite the measured file.
   - Primary artifacts: `render_qa.json`, fallback attempts/final state,
     `qa_gates`, and explainable failure receipts.
7. **Export pass**
   - Purpose: finalize the delivery boundary: container/codec selection,
     integer PCM quantization, deterministic dither policy, and export receipts.
   - Audio mutation: **boundary-only**. This stage may change representation at
     final serialization time, but no earlier stage may silently dither,
     quantize, or noise-shape.
   - Primary artifacts: output files plus `export_finalization_receipt` in
     manifests and reports.

### 5.1 What is advisory-only vs mutating

The contract is intentionally strict:

- Stages 2, 3, and 6 are advisory only. They may emit evidence, confidence,
  gates, or failure decisions, but they do not modify sample data.
- Stages 4 and 5 are the only stages allowed to make audible musical changes.
- Stages 1 and 7 are boundary stages. They may change representation for
  technical correctness or final delivery, but they are not a loophole for
  hidden mix decisions.

### 5.2 How current render reports map to the canonical graph

`render_report.json` currently exposes deterministic stage rows that focus on
render execution rather than the entire end-to-end pipeline:

- `planning` is an orchestration/reporting stage, not one of the seven
  canonical DSP stages.
- `resampling` is the current render-report surface for canonical stage 1 when
  rate conversion is requested or disclosed.
- `dsp_hooks` covers the mutating corrective/render boundary used by current
  renderer execution and hook receipts (canonical stages 4 and part of 5).
- `qa_gates` is the render-report surface for canonical stage 6.
- `export_finalize` is the render-report surface for canonical stage 7.

Canonical stages 2 and 3 are primarily recorded in `report.json`, `scene.json`,
and render-plan/request context rather than as `render_report.stage_id` values.

## 6) High-level workflow around the stage graph

1. **Validate and analyze**
   - inspect files, formats, metadata, durations, layouts, and checksums
   - measure meters/features and emit evidence
2. **Build intent**
   - optionally derive `scene.json`
   - optionally apply scene templates, locks, and target selection logic
3. **Plan delivery**
   - expand one scene into one or many render jobs in `render_plan.json`
4. **Execute render stages**
   - run canonical stages 1 and 4 through 7 as needed for each job
   - enforce approvals, gates, QA, fallback sequencing, and output contracts
5. **Compare and export supporting artifacts**
   - compare revisions, export PDFs/CSVs, and write receipt/audit artifacts

---

## 7) Scene and render contracts

The architectural center of MMO is no longer just "analyze a stem folder." It is
the scene/render contract chain.

### 7.1 Scene

`scene.json` stores layout-agnostic intent. It captures choices that should
survive across render targets and channel-order variants.

### 7.2 Render plan

`render_plan.json` expands one scene into concrete jobs for selected targets and
contexts. This is where mix-once/render-many becomes explicit.

### 7.3 Render execution

`safe-render`, `render-run`, and related project workflows execute against the
same plan/contract concepts and write explainable artifacts for what happened.

### 7.4 Ordering standards

MMO processes internally using canonical `SMPTE` ordering. It remaps at the
boundary for `FILM`, `LOGIC_PRO`, `VST3`, and `AAF` when the selected
target/layout declares those variants.

---

## 8) Plugins and safety gates

MMO supports detector, resolver, and renderer plugins.

What plugins can do:

- add issue detection
- add strategy/recommendation logic
- add bounded render behavior

What plugins cannot do:

- redefine core artifact schemas
- bypass safety gates
- silently change layout or ordering meaning

Core gates enforce:

- explicit approvals for higher-impact actions
- "never clip by default" behavior
- deterministic receipts and failure reporting
- required parameter/evidence completeness

---

## 9) Compare, QA, and audit

Compare is a first-class part of the architecture.

`mmo compare` can compare two reports or two report folders and write a
deterministic `compare_report.json`.

When sibling render QA artifacts exist, compare also records evaluation-only
`loudness_match` context so CLI and GUI comparison surfaces can disclose
fair-listen compensation instead of hiding it.

Safe-render and render-run also write audit-friendly receipts and QA artifacts
so delivery decisions remain explainable after the audio files are exported.

---

## 10) CLI and automation surface

MMO's shipped CLI surface is broader than a minimal planned CLI.

Current user-facing command groups include:

- `scan`, `analyze`, `run`, `safe-render`, `compare`
- `project`, `scene`, `render-plan`, `render-run`, `render-report`
- `watch`, `variants`, `deliverables`, `translation`, `downmix`
- `plugin`, `plugins`, `targets`, `roles`, `ontology`, `env`

That surface exists so the same contracts can serve:

- one-shot musician workflows
- deterministic batch/watch workflows
- project/session persistence
- desktop sidecar execution

---

## 11) Desktop paths

MMO currently ships two GUI paths:

- Primary path: packaged Tauri desktop app
- Fallback path: legacy CustomTkinter `mmo-gui`

Tauri already covers the artifact-backed workflow sequence:
`Validate -> Analyze -> Scene -> Render -> Results -> Compare`.

Still in progress:

- scene-lock editing parity in Tauri
- complete packaged desktop smoke coverage on all release targets

---

## 12) Reproducibility and audit trail

Reproducibility remains a hard requirement.

MMO artifacts can carry:

- engine version
- ontology version
- plugin versions and hashes
- settings/policies
- checksums and trace metadata
- selected layout and ordering standard
- fallback/approval decisions

That trail is what makes cross-machine regression testing and release delivery
review possible.

---

## 13) Current implementation focus

This repo is not "foundation only" anymore. The current focus is finishing the
remaining public-surface gaps around:

- release-copy accuracy and install/runtime guidance
- Tauri parity for scene-lock editing
- packaged desktop smoke coverage
- continued deterministic regression expansion for render and compare flows
