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

At the I/O boundary MMO supports five channel-ordering standards:
`SMPTE`, `FILM`, `LOGIC_PRO`, `VST3`, and `AAF`.

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

## 5) High-level pipeline

1. **Validate**
   - inspect files, formats, metadata, durations, layouts, and checksums
2. **Analyze**
   - measure meters and features
   - detect issues and emit evidence
   - resolve recommendations under bounded-authority rules
3. **Build intent**
   - optionally derive `scene.json`
   - optionally apply scene templates, locks, and target selection logic
4. **Plan delivery**
   - expand one scene into one or many render jobs in `render_plan.json`
5. **Render**
   - execute safe-render or render-run paths
   - enforce approvals, gates, QA, fallback sequencing, and output contracts
6. **Compare and export**
   - compare revisions, export PDFs/CSVs, and write receipt/audit artifacts

---

## 6) Scene and render contracts

The architectural center of MMO is no longer just "analyze a stem folder."
It is the scene/render contract chain.

### 6.1 Scene

`scene.json` stores layout-agnostic intent.
It captures choices that should survive across render targets and channel-order
variants.

### 6.2 Render plan

`render_plan.json` expands one scene into concrete jobs for selected targets and
contexts.
This is where mix-once/render-many becomes explicit.

### 6.3 Render execution

`safe-render`, `render-run`, and related project workflows execute against the
same plan/contract concepts and write explainable artifacts for what happened.

### 6.4 Ordering standards

MMO processes internally using canonical `SMPTE` ordering.
It remaps at the boundary for `FILM`, `LOGIC_PRO`, `VST3`, and `AAF` when the
selected target/layout declares those variants.

---

## 7) Plugins and safety gates

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

## 8) Compare, QA, and audit

Compare is a first-class part of the architecture.

`mmo compare` can compare two reports or two report folders and write a
deterministic `compare_report.json`.

When sibling render QA artifacts exist, compare also records
evaluation-only `loudness_match` context so CLI and GUI comparison surfaces can
disclose fair-listen compensation instead of hiding it.

Safe-render and render-run also write audit-friendly receipts and QA artifacts
so delivery decisions remain explainable after the audio files are exported.

---

## 9) CLI and automation surface

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

## 10) Desktop paths

MMO currently ships two GUI paths:

- Primary path: packaged Tauri desktop app
- Fallback path: legacy CustomTkinter `mmo-gui`

Tauri already covers the artifact-backed workflow sequence:
`Validate -> Analyze -> Scene -> Render -> Results -> Compare`.

Still in progress:

- scene-lock editing parity in Tauri
- complete packaged desktop smoke coverage on all release targets

---

## 11) Reproducibility and audit trail

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

## 12) Current implementation focus

This repo is not "foundation only" anymore.
The current focus is finishing the remaining public-surface gaps around:

- release-copy accuracy and install/runtime guidance
- Tauri parity for scene-lock editing
- packaged desktop smoke coverage
- continued deterministic regression expansion for render and compare flows
