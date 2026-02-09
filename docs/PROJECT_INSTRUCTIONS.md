# Mix Marriage Offline (MMO) — Project Instructions

## Goal

Build an open-source, offline, stem-folder mixing assistant. The system handles technical QA and math (validation, metering, detection, translation checks, safety gates). The user focuses on intent and vibe. Output is explainable and DAW-agnostic (report + recall sheet), with optional conservative rendered audio.

A key goal is **mix-once, render-many**. The system captures the mix as **layout-agnostic intent** (a scene), then renders that intent to multiple targets (2.0 through surround and immersive beds), with strict downmix QA.

## Core principles

1) **Objective Core vs Subjective Plugins**  
Objective Core is “truth and contracts”: meters, validation, translation checks, safety gates, schemas, channel/layout semantics, canonical ordering, downmix matrices, and render contracts.  
Subjective Plugins are “taste and strategies”: detectors, resolvers, renderers, profiles, and optional spatial enhancements.

2) **Mix-once, render-many (scene-first)**  
Store user intent as a layout-agnostic scene: **objects** (discrete content) plus **bed/field** (diffuse content). Render to any target layout at the end. Do not treat a stereo bounce as the source of truth when stems and mix decisions are available.

3) **Deterministic outputs**  
Same inputs + settings produce the same outputs. Determinism includes seeded decorrelation, fixed FFT planning choices, reproducible plugin ordering, and a consistent dither/noise policy, across up to **32 channels**.

4) **Explainability**  
Every issue and every action must include **what / why / where / confidence**. Spatial decisions must also report **object vs bed** classification, any inferred azimuth/width cues (when applicable), and confidence. Inference never overrides explicit user intent.

5) **Bounded authority**  
Auto-apply only low-risk actions within user limits. Require approval for high-impact moves (tone, balance, spatial placement changes, heavy dynamics changes, destructive edits).

6) **Layout safety and downmix QA**  
All renders must pass **fold-down/downmix similarity gates** (at least to stereo, and optionally to canonical bed formats), plus correlation/phase-risk checks. If confidence is low, the system backs off toward safer routing (more front-stage, less aggressive surround/height).

7) **Ontology-first**  
Use canonical IDs for roles, features, issues, actions, params, units, and evidence. Define them in YAML. Channel semantics and layout definitions are part of the ontology and must not drift.

8) **Open-source by design**  
Core stays stable and heavily reviewed. Plugins evolve rapidly without breaking contracts.

## Key concepts

### A) Scene / mix intent (layout-agnostic)

- **Objects:** position intent (azimuth, optional elevation intent), width/spread, depth proxy (dry vs early vs late energy), confidence, locks.  
- **Bed/field:** diffuse energy representation intended for surrounds/heights.  
- **Routing intent:** front-stage, surrounds, heights, LFE send, FX returns.  
- **Rules:** “do no harm” defaults, confidence gating, smoothing for any inferred placement.

### B) Render contracts (layout-specific)

- Canonical channel naming and order per layout.  
- Speaker position metadata (azimuth/elevation) when needed.  
- Downmix matrices/policies (explicit, versioned).  
- LFE policy: treated as a creative send plus bass management rules.  
- Note on “.2”: generally a playback/sub management detail, not a requirement for separate LFE program content unless explicitly targeting a format that expects dual LFE.

### C) Plugin semantics (declared by every plugin)

- `max_channels` (target ≥ 32)  
- `channel_mode`: `per_channel`, `linked_group`, `true_multichannel`  
- Supported link groups: `front`, `surrounds`, `heights`, `all`, `custom`  
- Latency reporting (fixed or dynamic) and host delay-comp policy  
- Deterministic seed usage (if generating noise/decorrelation)  
- Requirements: whether it needs speaker positions, whether it’s bed-only or can run on objects

### D) Stereo stems with baked pan/width (advisory inference)

If stems arrive as stereo files with gain/pan baked in, the system may estimate azimuth/width using energy and coherence measures. Those estimates are advisory and confidence-gated. Front-back is treated as depth/directness (direct-to-reverb, transients, spectral distance cues), not as literal “behind the listener” placement.

## Workflow (build order matters)

1) Docs first  
2) Ontology YAML + JSON schemas  
3) Scene/mix-intent schema + render contract  
4) Registry and validators (Objective Core)  
5) Meters and QA gates (Objective Core)  
6) Detectors/resolvers (Subjective Plugins)  
7) Profiles (translation, style, safety limits)  
8) Rendering targets (stereo + beds + immersive foundations)  
9) Advanced spatial polish (optional plugins)

Maintain fixture sessions and tests early to prevent regressions. Every deliverable must be ready to paste into the repo with correct paths and filenames.

## Deliverables

### docs/
- proposal.md  
- philosophy.md  
- architecture.md  
- scene_model.md  
- render_contracts.md  
- plugin_api.md  
- plugin_semantics.md  
- fixtures_ci.md  
- roadmap.md  
- export_guides.md  
- **PROJECT_INSTRUCTIONS.md** (this document)  
- **SCENE_AND_RENDER_CONTRACT_OVERVIEW.md** (overview document)

### ontology/
- roles.yaml, features.yaml, issues.yaml, actions.yaml, params.yaml, units.yaml, evidence.yaml  
- layouts.yaml (including immersive targets and canonical channel sets)  
- downmix.yaml (explicit matrices/policies, versioned)  
- gates.yaml (safety thresholds and fallbacks)

### schemas/
- project.json  
- report.json  
- plugin_manifest.json  
- scene.json (mix intent)  
- render_request.json  
- render_report.json

### Fixtures/tests
- fixture sessions for stereo, 5.1, 7.1, and one immersive target (like 7.1.4)  
- “stereo stems with baked pan/width” fixture to validate inference gating  
- determinism tests (same inputs → byte-stable or numerically stable output)  
- downmix similarity tests

## Non-goals (for now)

- DAW plugin integration (VST/AU/AAX hosting).  
- “Black box” ML that overrides meters, gates, or explicit user intent.  
- Claiming to replace proprietary Atmos renderers or recover true object metadata from a stereo bounce.  
- Hard guarantees of literal front-back placement from stereo-only cues; treat depth as directness/diffuseness proxies.  
- Mandatory dual-LFE program content for “.2” layouts unless explicitly targeted by a spec that requires it.
