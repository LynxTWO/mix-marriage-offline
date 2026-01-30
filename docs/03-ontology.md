# docs/03-ontology.md

## MMO Ontology
### A shared, canonical vocabulary for plugins, reports, and reproducibility.

---

## 1) Why an ontology exists
Open-source projects break when contributors can’t agree on terms.

MMO avoids that by defining a single, canonical vocabulary (the “ontology”) that every plugin and report uses:
- track roles
- channel layouts and speakers
- measured features
- detected issues
- recommended actions
- action parameters
- units
- evidence fields
- gate outcome reasons

Contributors can name internal variables however they like.  
But anything leaving a plugin must use **canonical ontology IDs**.

This is the key to:
- interoperability between plugins
- consistent reports and recall sheets
- stable regression tests (fixtures)
- reproducibility across machines and versions

---

## 2) Source of truth
**YAML is the source of truth.**

All canonical IDs and definitions live in `ontology/*.yaml` and `ontology/policies/*.yaml`.

Code should not invent new IDs at runtime.  
If an ID doesn’t exist in YAML, it is not valid.

---

## 3) ID conventions (canonical keys)
### 3.1 Format
Canonical IDs are uppercase, dot-separated:

- `ROLE.DRUM.KICK`
- `FEATURE.LOUDNESS.LUFS_I`
- `ISSUE.SPECTRAL.HARSHNESS`
- `ACTION.EQ.BELL_CUT`
- `PARAM.EQ.FREQ_HZ`
- `UNIT.DBTP`
- `LAYOUT.7_1_4`
- `SPK.TFR`
- `REASON.CLIP_RISK`

### 3.2 Rules
- IDs are stable. Once released, **do not rename** an ID.
- Labels and descriptions can improve over time without breaking compatibility.
- Avoid overloaded words. Prefer specificity (`HARSHNESS` vs `BRIGHT`).
- IDs must be unique globally within their category.

### 3.3 Human readability
Every ontology entry should include:
- `label` (human-friendly)
- `description` (plain language)
- optionally `notes` and `examples`

---

## 4) Versioning and compatibility
### 4.1 Ontology version
The ontology has its own semantic version: `ontology_version: X.Y.Z`

- **PATCH**: typos, description improvements, non-breaking metadata
- **MINOR**: add new IDs or optional fields (backward compatible)
- **MAJOR**: breaking changes (avoid; prefer deprecations)

### 4.2 Deprecation policy
Never silently remove or rename IDs.

Instead:
- mark the old ID as `deprecated: true`
- add `replaced_by: NEW.ID`
- keep support for at least one major version cycle

---

## 5) Ontology file map
The ontology is split for reviewability and low merge-conflict risk.

Minimum set:

- `ontology/ontology.yaml`  
  Declares `ontology_version` and includes references to the other YAML files.

- `ontology/units.yaml`  
  Canonical units: Hz, dB, dBTP, LUFS, ms, samples, percent, degrees, meters, etc.

- `ontology/speakers.yaml`  
  Speaker definitions with metadata (azimuth/elevation), for surround reasoning.

- `ontology/layouts.yaml`  
  Channel layouts (2.0, 2.1, 5.1, 7.1, 7.1.4, etc.) and channel groups.

- `ontology/roles.yaml`  
  Track/stem roles used for auto-bus creation and context.

- `ontology/features.yaml`  
  Measured feature IDs (meters + signal stats).

- `ontology/issues.yaml`  
  Detected problem IDs with definitions and typical evidence.

- `ontology/actions.yaml`  
  Action IDs with required parameters and constraints.

- `ontology/params.yaml`  
  Parameter keys and units (e.g., EQ freq/Q/gain).

- `ontology/evidence.yaml`  
  Evidence keys used to justify issues and actions (time ranges, freq ranges, stems involved).

- `ontology/reasons.yaml`
  Canonical `REASON.*` codes used by gates to explain plan rejections/downgrades.

Policies (swappable by design):
- `ontology/policies/gates.yaml`  
  Non-negotiable safety rules and default thresholds.

- `ontology/policies/downmix.yaml` and `ontology/policies/downmix_policies/*.yaml`  
  Downmix profile references and fold-down policy definitions.

---

## 6) What the ontology does (and does not do)
### 6.1 The ontology DOES
- define what IDs are valid
- provide labels and descriptions for UI and reports
- define required parameters for actions
- define units for parameters and features
- define layouts and speaker metadata for surround checks
- enable strict validation and reproducibility

### 6.2 The ontology DOES NOT
- implement DSP algorithms
- decide severity scoring logic
- decide “best” strategy for fixes
- encode proprietary renderer behavior

Those belong in plugins and policies, constrained by gates.

---

## 7) Validation rules (enforced by the core)
At runtime, the core loads the ontology and enforces:

1) **ID validity**
   - unknown IDs are rejected

2) **Required fields**
   - entries must include at least `label` and `description` (exceptions allowed for units)

3) **Action parameter requirements**
   - an action must include all required params listed in `actions.yaml`

4) **Unit correctness**
   - parameters and features must use the declared units

5) **Layout consistency**
   - layouts reference valid speaker IDs
   - channel groups reference speakers that exist in that layout

This validation is what makes the plugin ecosystem safe to expand.

---

## 8) Adding a new ontology entry (contributor workflow)
When adding a new feature/issue/action:

1) Choose the correct category file (`features.yaml`, `issues.yaml`, etc.)
2) Add a new canonical ID following the naming rules
3) Provide:
   - label
   - description
   - any relevant default bands, hints, or notes
4) If it’s an action:
   - define required params (in `actions.yaml`)
   - ensure params exist (in `params.yaml`)
5) Update fixtures/tests if the change affects detection logic or reports

---

## 9) Examples
### 9.1 Feature example
A measured loudness feature:

- ID: `FEATURE.LOUDNESS.LUFS_I`
- Label: Integrated Loudness
- Unit: `UNIT.LUFS`
- Description: Integrated loudness over the full program.

### 9.2 Issue example
A harshness issue:

- ID: `ISSUE.SPECTRAL.HARSHNESS`
- Evidence typically includes:
  - time range (where it spikes)
  - frequency range (often 2–5 kHz)
  - stems involved (vocal, cymbals, guitars)
- Severity is determined by plugin logic, not ontology.

### 9.3 Action example
An EQ notch:

- ID: `ACTION.EQ.BELL_CUT`
- Required params:
  - `PARAM.EQ.FREQ_HZ`
  - `PARAM.EQ.Q`
  - `PARAM.EQ.GAIN_DB`

---

## 10) Practical guidance (keep it sane)
- Prefer adding new IDs over renaming old ones.
- Keep the ontology descriptive, not prescriptive.
- Use policies for thresholds and fold-down coefficients, not the core ontology.
- When unsure, add `notes` and mark entries as `experimental: true` until proven.

---

## 11) What’s next
After this doc, we implement the ontology YAML skeletons and a registry loader that:
- loads all YAML files
- validates IDs and required fields
- provides lookup helpers (labels/descriptions/required params/units)
- outputs a compiled registry manifest for debugging

