# docs/02-architecture.md

## Mix Marriage Offline Architecture
### Offline stems in. Truth-first analysis. Explainable actions out.

---

## 1) System overview
Mix Marriage Offline (MMO) is a standalone, offline tool that consumes a folder of exported stems and produces:
- validated session metadata
- measured features (meters and signal stats)
- detected issues (with evidence)
- proposed actions (with risk levels and constraints)
- exports (PDF + JSON report, CSV recall sheet)
- optional safe rendered stem variants

MMO is intentionally DAW-agnostic. The bridge back into any DAW is the **recall sheet** (and optional rendered stems).

---

## 2) Design constraints
- Offline first (no cloud dependency).
- No DAW integration required.
- Deterministic outputs given identical inputs/settings.
- Explainability is mandatory (issues and actions must carry evidence).
- Modular plugins for detectors, resolvers, and renderers.
- “Truth layer” (meters, validation, gates, schemas) is stable and heavily tested.

---

## 3) Inputs and assumptions
### 3.1 Stem folder rules
- All stems start at 0:00 (full-length stems with leading silence allowed).
- All stems share the same sample rate and bit depth.
- Stems are aligned and roughly equal length (within tolerance).
- Roles are inferred from naming convention or assigned in-app.

### 3.2 Surround and multichannel stems
- Stems may be mono, stereo, or multichannel (layout-aware).
- Channel layout is either inferred (from filename or container metadata) or assigned by the user.
- MMO can run layout-specific checks and downmix translation checks.

---

## 4) High-level pipeline
The core pipeline is linear and explicit:

1) **Validate**
   - scan folder, read metadata, check formats
   - confirm sample rate/bit depth consistency
   - confirm alignment and duration rules
   - compute file checksums for reproducibility

2) **Build session**
   - assign stem roles
   - build virtual buses (DRUMS/VOCALS/MUSIC/MIX)
   - determine channel layout(s)

3) **Measure**
   - compute trusted meters and features per stem and per bus
   - loudness (LUFS), true peak (dBTP), crest factor
   - spectral bands and tilt, stereo correlation, M/S energy (where applicable)
   - surround group energy balance (front/surround/height/LFE) where applicable

4) **Detect**
   - detectors convert features into **issues**
   - issues include severity (0–100), confidence, and evidence

5) **Resolve**
   - resolvers turn issues into **actions** (or action options)
   - multiple strategies are encouraged (tradeoffs made explicit)

6) **Gate**
   - safety gates enforce bounded authority and user limits
   - unsafe actions are rejected or downgraded to “suggest only”

7) **Export**
   - PDF report + JSON report + CSV recall sheet
   - project file (session + settings + results)

8) **(Optional) Render**
   - apply gated actions to produce conservative stem variants
   - preserve sample alignment and length
   - never clip by default

---

## 5) Core data model (conceptual)
MMO uses a small set of canonical objects, validated by schemas and ontology IDs.

### 5.1 Session
- session_id
- created_at
- engine_version, ontology_version
- settings (intent sliders, limits, policies)
- stems[] and buses[]
- features[], issues[], recommendations[]
- translation_results[]
- plugin_manifest (versions/hashes)
- input_checksums (per file)

### 5.2 Stem
- stem_id
- file_path, checksum
- role_id (ontology)
- channel_layout_id (ontology)
- channels[] (speaker mapping where relevant)
- duration, sample_rate, bit_depth

### 5.3 Bus
- bus_id (DRUMS/VOCALS/MUSIC/MIX)
- member_stem_ids[]
- channel_layout_id

### 5.4 Feature
- feature_id (ontology)
- scope: stem_id or bus_id
- value + unit
- optional per-band or per-channel-group breakdown
- computation metadata (algorithm version)

### 5.5 Issue
- issue_id (ontology)
- scope: stem/bus/session
- severity 0–100
- confidence: low/medium/high
- evidence:
  - time_range_s
  - freq_range_hz
  - stems_involved[]
  - channel_groups_involved[] (surround)
  - supporting feature references

### 5.6 Action
- action_id (ontology)
- target (stem/bus/channel group)
- params (ontology param keys + values + units)
- risk level
- requires_approval flag
- expected_effect and tradeoffs

### 5.7 ActionPlan
- ordered list of actions
- gating results (allowed/rejected reasons)
- provenance (which resolver produced it)

---

## 6) Ontology and registries
MMO uses YAML as the source of truth for canonical names and IDs:
- roles, features, issues, actions, params, units, evidence fields
- speakers, layouts, downmix policies
- safety gates and policy references

At runtime, `registry` loads the YAML and exposes:
- ID validation (reject unknown IDs)
- required parameter enforcement for actions
- unit validation
- layout/channel group relationships

Plugins must output ontology IDs, not ad-hoc strings.

---

## 7) Plugin architecture
MMO supports three plugin types:

### 7.1 Detector plugins
Input:
- session + measured features (stems/buses/layout)
Output:
- issues[] with evidence, severity, confidence

Examples:
- resonance detector
- mud/harshness detector
- mono collapse risk detector
- downmix intelligibility loss detector (surround)

### 7.2 Resolver plugins
Input:
- session + issues[] + intent/limits
Output:
- action options (recommendations) + rationale

Examples:
- conservative EQ resolver (suggest notches)
- masking strategy resolver (suggest dynamic EQ vs subtractive EQ)
- surround focus resolver (suggest center/front balance strategies)

### 7.3 Renderer plugins (optional)
Input:
- session + gated action plan
Output:
- rendered stem variants (WAV) + render manifest

Default renderer behavior is conservative and safe.

---

## 8) Safety gates
Safety gates live in the core, not in plugins.

Gates enforce:
- user limits (max EQ change, max compression ratio, etc.)
- “never clip by default”
- “mix-bus changes require explicit enable”
- “every action must be explainable and parameterized”
- “reject incomplete evidence or missing required params”

Plugins can propose anything, but the core decides what is allowed.

---

## 9) Translation checks
Translation checks are implemented as policy-driven simulations, then measured again.

Examples:
- stereo and mono collapse checks
- phone profile (band-limit + mono emphasis)
- earbuds profile (presence and fatigue risk)
- car-like curve profile
- surround downmix profiles (5.1 → 2.0, 7.1.4 → 5.1/2.0)

Outputs:
- translation score (0–100) per profile
- top risks + evidence
- suggested mitigations

---

## 10) CLI and automation (planned)
A minimal CLI keeps the tool scriptable.

Examples:
- `mmo scan <folder>`
- `mmo analyze <folder> --intent preset.json`
- `mmo export <project.mmo_project.json>`
- `mmo render <project.mmo_project.json>`

The CLI output should always include paths to exported artifacts.

---

## 11) Reproducibility and audit trail
Every run produces a manifest:
- stem checksums
- ontology + engine versions
- plugin versions/hashes
- settings and policies
- analysis timestamps

This makes results comparable across machines and over time.

---

## 12) What’s next (implementation order)
1) Ontology YAML + registry loader + validators
2) Meter truth layer (LUFS, true peak, crest factor)
3) Basic features (spectral bands, correlation)
4) First detectors (resonance, mud/harshness)
5) First resolver (conservative EQ suggestions)
6) Exporters (JSON + CSV first, PDF later)
7) Fixtures + CI regression tests
8) Translation profiles
9) Optional safe rendering
10) Surround foundation (layouts + downmix QA)

