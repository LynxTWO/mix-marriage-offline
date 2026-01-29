# MMO Ontology

The MMO ontology is the project’s **shared vocabulary**.

It defines the canonical IDs that appear in:
- plugin outputs (detectors, resolvers, renderers)
- reports and recall sheets
- fixture expectations and regression tests
- compiled registries and validation errors

If an ID does not exist in the ontology YAML, it is **not valid**.

---

## Core idea

**Truth meters in the core. Taste in the plugins.**

The ontology supports this by making the language stable and testable:
- **Features** are measured values (meters, stats).
- **Issues** are detected technical problems with evidence.
- **Actions** are DAW-agnostic operations (recommendations).
- **Params** specify action settings with explicit units.
- **Evidence** keys standardize “what/why/where” proof.

The core loads these YAML files into a registry and uses them to validate everything coming from plugins and exporters.

---

## Folder structure

```
ontology/
  README.md

  ontology.yaml        # master include + ontology version
  units.yaml           # UNIT.* definitions (dB, Hz, LUFS, ms, etc.)

  roles.yaml           # ROLE.* stem roles (kick, lead vocal, bus, etc.)
  features.yaml        # FEATURE.* measured meters and signal stats
  issues.yaml          # ISSUE.* detected problems (with evidence hints)
  actions.yaml         # ACTION.* DAW-agnostic operations + required params
  params.yaml          # PARAM.* action parameters + units + constraints
  evidence.yaml        # EVID.* evidence keys for explainability

  speakers.yaml        # SPK.* semantic speakers (azimuth/elevation defaults)
  layouts.yaml         # LAYOUT.* channel layouts + canonical ordering

  policies/            # swappable rule packs (handled in a separate step)
    gates.yaml
    downmix.yaml
    downmix_policies/
      *.yaml
```

Policies are **separate by design**: the ontology defines *what* things are, policies define *how strict* we are (thresholds, fold-down coefficients, scoring rules).

---

## Versioning rules

The ontology has its own semantic version, stored in `ontology/ontology.yaml`.

- **PATCH**: labels/typos/notes (no ID changes)
- **MINOR**: add new IDs or optional fields (backward compatible)
- **MAJOR**: breaking changes (avoid; prefer deprecations)

### Stability promise
- **Never rename** or remove IDs silently.
- Deprecate instead:
  - `deprecated: true`
  - `replaced_by: NEW.ID`

This is what keeps plugins and fixtures from breaking unexpectedly.

---

## What each YAML file is responsible for

### `ontology.yaml`
- Declares `ontology_version`.
- Lists included files (and later, policy packs).

### `units.yaml`
- Canonical units used everywhere (features + params).
- Example: `UNIT.DBTP`, `UNIT.LUFS`, `UNIT.HZ`.

### `roles.yaml`
- Canonical stem roles and role inference hints (keywords/regex).
- Used for virtual bus building (DRUMS/VOCALS/MUSIC/MIX).

### `features.yaml`
- Canonical measured meters and stats.
- Must be deterministic and unit-labeled (ex: LUFS, true peak, band energy).

### `issues.yaml`
- Canonical technical problems (not taste labels).
- Includes evidence expectations and common fix hints.

### `actions.yaml`
- Canonical operations MMO can recommend (DAW-agnostic).
- Defines:
  - required params (`PARAM.*`)
  - risk defaults
  - auto-apply eligibility tags
  - scope and granularity constraints

### `params.yaml`
- Canonical parameter keys and units (EQ freq/Q/gain, thresholds, times).
- Includes constraints and recommended ranges.

### `evidence.yaml`
- Canonical evidence keys (time ranges, freq ranges, meters, counts, etc.).
- Used by detectors and resolvers to prove “what/why/where”.

### `speakers.yaml` and `layouts.yaml`
- **Surround foundation**.
- Speakers define semantic channels (L, R, C, LFE, heights) with defaults.
- Layouts define channel counts and canonical ordering, referencing `SPK.*`.

---

## How the core uses the ontology

At runtime, the core should:
1. Load all ontology YAML into a registry.
2. Validate:
   - ID uniqueness and format
   - required fields (`label`, `description` where applicable)
   - cross-references (actions → params, layouts → speakers, units exist)
3. Enforce ontology + schema validation on plugin output:
   - unknown IDs rejected
   - missing required params rejected
   - wrong units rejected

This is how MMO stays explainable and safe while still letting plugins evolve quickly.

---

## How plugins should use the ontology

Plugins must output canonical IDs:
- `FEATURE.*` in feature manifests (core-produced, plugins consume)
- `ISSUE.*` from detectors
- `ACTION.*` + `PARAM.*` from resolvers
- `EVID.*` everywhere evidence is required

Plugins should **not invent new strings** at runtime. If an ID is missing, it belongs in the ontology first.

---

## Contributor workflow for ontology changes

When adding a new entry:

1. Pick the correct file (`issues.yaml`, `features.yaml`, etc.).
2. Add a new canonical ID using uppercase dot notation.
3. Provide at least:
   - `label`
   - `description`
4. If adding an `ACTION.*`:
   - ensure required `PARAM.*` exist
   - ensure params declare correct `UNIT.*`
5. If adding surround items:
   - speakers must be `SPK.*`
   - layouts must reference existing speakers only
6. Add or update a fixture expectation if the change affects detection or reporting.

---

## Validation checklist

Before merging ontology changes:
- IDs are unique and match the category prefix (`ROLE.`, `FEATURE.`, etc.).
- Every referenced ID exists (params, units, speakers, layouts).
- Numeric values have units (avoid unitless unless truly unitless).
- Actions list all required params.
- Layout channel counts match the channel order length.
- Deprecations include `replaced_by` when appropriate.

---

## Notes on policies

Policies live in `ontology/policies/` and are meant to be swappable:
- safety gates and thresholds (`gates.yaml`)
- downmix policy registry (`downmix.yaml`)
- concrete downmix coefficient sets (`downmix_policies/*.yaml`)

These are intentionally not part of the “stable ID surface” like roles/issues/actions. They are the tuning layer.
