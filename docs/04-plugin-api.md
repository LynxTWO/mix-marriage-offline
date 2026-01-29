# docs/04-plugin-api.md

## MMO Plugin API
### How detectors, resolvers, and renderers plug into the core safely.

---

## 1) Goals
The plugin system exists to:
- let the community improve detection and strategy without destabilizing the “truth layer”
- enable taste and workflow diversity (multiple strategies for the same problem)
- keep outputs consistent through **ontology IDs** and **schema validation**
- preserve reproducibility (plugin versions/hashes recorded in reports)

MMO plugins are not “random Python scripts.”  
They are modules that implement strict interfaces and return validated data structures.

---

## 2) Plugin types
MMO supports three plugin types:

### 2.1 Detector plugins
**Purpose:** convert measured features into **issues** (problem statements with evidence).

**Input:** Session + measured features  
**Output:** `issues[]`

Examples:
- resonance detector
- mud/harshness detector
- mono collapse risk detector
- surround downmix intelligibility loss detector

### 2.2 Resolver plugins
**Purpose:** convert issues into **actions** (recommendations), often with multiple strategy options.

**Input:** Session + issues + user intent/limits  
**Output:** `recommendations[]` (action options)

Examples:
- conservative EQ resolver
- masking strategy resolver (subtractive EQ vs dynamic EQ suggestion)
- surround focus resolver (center/front stage balance suggestions)

### 2.3 Renderer plugins (optional)
**Purpose:** apply a gated action plan to create **rendered stem variants**.

**Input:** Session + gated action plan  
**Output:** rendered WAVs + render manifest

Default behavior should be conservative and never clip by default.

---

## 3) What plugins must obey
### 3.1 Ontology-first
Plugins must use canonical IDs from the ontology YAML:
- roles, features, issues, actions, params, units, evidence fields
- layouts and speakers for surround

If an ID is not in the ontology, it is not valid.

### 3.2 Explainability requirements
Detectors must include evidence:
- time range (seconds)
- frequency range (Hz), when applicable
- stems involved
- confidence

Resolvers must include:
- explicit action parameters with units
- risk level
- expected effect and tradeoffs
- whether approval is required

### 3.3 Determinism
Given identical inputs and settings, plugin outputs should be stable.
Avoid randomness. If randomness is required, it must be seeded and logged.

### 3.4 Safety gates are final
Plugins can propose anything, but the core enforces gates.
Plugins must not attempt to “bypass” gates or weaken the schema.

---

## 4) Plugin packaging (recommended)
### 4.1 Directory layout (repo-local plugins)
A minimal plugin package:

```
plugins/
  detectors/
    resonance_detector.py
  resolvers/
    conservative_eq_resolver.py
  renderers/
    safe_renderer.py
```

Each plugin module provides:
- a `PLUGIN_META` dict or a `plugin.yaml` manifest (recommended)
- a class implementing the relevant interface

### 4.2 plugin.yaml (recommended manifest)
Each plugin should include a manifest for metadata and compatibility.

Example:

```yaml
plugin_id: "PLUGIN.DETECTOR.RESONANCE"
plugin_type: "detector"
name: "Resonance Detector"
version: "0.1.0"
author: "Your Name"
license: "Apache-2.0"
description: "Detects persistent narrow-band resonances and flags safe notch suggestions."
mmo_min_version: "0.1.0"
ontology_min_version: "0.1.0"
entrypoint: "plugins.detectors.resonance_detector:ResonanceDetector"
capabilities:
  - "ISSUE.SPECTRAL.RESONANCE"
```

MMO records plugin metadata (including version and file hash) in output manifests.

---

## 5) Data contracts (conceptual)
The core validates plugin outputs against schemas and ontology rules.

Plugins will generally consume and produce these objects:

### 5.1 Inputs
- `Session`: stems, buses, settings, layouts, checksums
- `Features`: measured meters and stats (already computed by core pipeline)

### 5.2 Outputs
- `Issue` objects (from detectors)
- `Recommendation` objects (from resolvers)
- `RenderManifest` objects (from renderers)

All outputs must:
- use ontology IDs
- include units
- include required fields

---

## 6) Interfaces (behavioral contract)
Below is the behavioral contract. The concrete Python types live in `src/mmo/plugins/interfaces.py`.

### 6.1 Detector interface
A detector must implement:

- `id()` → plugin_id string
- `run(session, features)` → list of Issue

Rules:
- do not modify session
- return zero or more issues
- each issue must include evidence and confidence

### 6.2 Resolver interface
A resolver must implement:

- `id()` → plugin_id string
- `run(session, issues)` → list of Recommendation

Rules:
- may return multiple recommendations per issue
- must include explicit action parameters and risk level
- should include multiple strategy options when meaningful

### 6.3 Renderer interface
A renderer must implement:

- `id()` → plugin_id string
- `render(session, gated_action_plan, output_dir)` → RenderManifest

Rules:
- output files must be sample-aligned and length-matched to inputs
- default behavior must prevent clipping unless user allows it
- render manifest must list all produced files and applied actions

---

## 7) Risk levels and approval flags (required)
Each recommendation must include:
- `risk`: low | medium | high
- `requires_approval`: true | false

Suggested defaults:
- any EQ move > 2 dB → medium/high, requires approval
- broadband tonal shifts → requires approval
- compression ratio > 3:1 → requires approval
- anything on MIX bus → requires approval (unless enabled)

The core gates may override or block actions even if a plugin marks them “low.”

---

## 8) Validation and error handling
### 8.1 Validation
Plugin outputs are validated in this order:
1) schema validation (required fields and types)
2) ontology validation (IDs and required params)
3) safety gate validation (limits and policies)

### 8.2 Errors
Plugins should fail gracefully:
- raise structured exceptions
- include actionable error messages
- never crash the entire pipeline if a single plugin fails (unless configured)

The core should mark the plugin as failed and continue with remaining plugins.

---

## 9) Compatibility and deprecation
Plugins must declare:
- minimum MMO version
- minimum ontology version

If an ontology ID is deprecated:
- plugins should transition to the replacement ID
- core may support aliases for a deprecation window

---

## 10) How to write a plugin (quick start)
1) Pick a type: detector, resolver, renderer.
2) Choose the ontology IDs you will emit.
3) Implement the interface class.
4) Add a `plugin.yaml` manifest.
5) Add at least one fixture test proving expected behavior.
6) Submit a PR with documentation and test results.

---

## 11) What’s next
After this doc:
- implement `schemas/plugin.schema.json`
- implement the plugin registry/loader (`src/mmo/plugins/host.py`)
- create one reference detector and resolver that pass schema + ontology validation

