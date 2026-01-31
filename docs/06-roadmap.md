# Roadmap

This roadmap is a practical build plan for MMO. It is not a promise of dates. The priority is a stable, deterministic core first, then fast-evolving plugins.

## Guiding rules
- Core is deterministic: same inputs and settings produce the same outputs.
- Core is strict: schemas and ontology IDs are enforced at every boundary.
- Plugins can be creative, but gates are final.
- Every result must be explainable: what, why, where, confidence.

## Milestones

### v0.1 Foundation
Goal: agree on vocabulary and contracts before writing “mixing logic”.

Definition of done:
- Ontology YAMLs exist for roles, features, issues, actions, params, units, evidence, layouts, speakers.
- Policy validation exists for downmix and safety gates.
- Fixtures and CI run deterministically.

Deliverables:
- `ontology/` YAML source of truth
- `ontology/policies/` downmix registry + packs
- `tools/validate_policies.py` and `tools/run_policy_fixtures.py`
- `schemas/validation_result.schema.json`

### v0.2 Schema contracts
Goal: lock down I/O so implementation cannot drift.

Definition of done:
- JSON schemas exist for:
  - project input
  - plugin manifest
  - report output
- All schemas are strict (no unknown fields by default) and use ontology IDs.
- Docs reference schemas as the canonical contract.

Deliverables:
- `schemas/project.schema.json`
- `schemas/plugin.schema.json`
- `schemas/report.schema.json`

### v0.3 Session ingest and validation
Goal: load a stem folder into a session object with reproducible checksums.

Definition of done:
- Stem folder ingest produces:
  - file list, durations, channel counts
  - SHA-256 hashes for reproducibility
  - consistent stem ordering rules
- Validation catches common export failures:
  - mismatched length
  - missing tails
  - inconsistent sample rate or channel layouts
- Output is a validated “session manifest” JSON.

Deliverables:
- Core ingest module
- Session manifest JSON output
- Fixtures for bad exports (fail fast)

### v0.4 Truth meters
Goal: compute trusted, testable meters that every plugin can rely on.

Definition of done:
- Per stem and mix-sum meters:
  - peak (dBFS)
  - true peak (dBTP)
  - loudness (LUFS-I) and LRA where available
  - crest factor
- All meters have:
  - evidence objects with units
  - versioned algorithm metadata
  - deterministic outputs

Deliverables:
- Meter implementations (core)
- Tests with fixture audio
- Report JSON includes meter evidence

### v0.5 First detectors and resolvers
Goal: demonstrate the full loop: features -> issues -> actions -> gated plan.

Definition of done:
- At least one detector that emits issues with evidence.
- At least one resolver that emits action recommendations with parameters.
- Gates block unsafe actions by default.
- Output includes a recall sheet that a human can apply in any DAW.

Deliverables:
- Reference detector: resonance or mud/harshness
- Reference resolver: conservative EQ suggestions
- Gated action plan output
- Recall sheet exporter (CSV or TXT)

### v0.6 Translation checks
Goal: measure “will this survive real life” without guesswork.

Definition of done:
- Translation profiles simulated and re-measured:
  - mono collapse
  - phone-like band limiting
  - earbuds fatigue risk
  - car-like curve
  - downmix translation (surround to stereo/mono)
- Translation results include scores and evidence.

Deliverables:
- Translation profile definitions
- Translation results in report JSON

### v0.7 Optional safe rendering
Goal: render conservative stem variants inside strict limits.

Definition of done:
- Rendering is opt-in.
- Default is “never clip” and “no mix bus processing”.
- Render manifests include applied actions and output checksums.

Deliverables:
- Safe renderer plugin reference implementation
- Render manifest schema coverage
- Render fixtures

### v1.0 Stable core
Goal: freeze the core contracts so the ecosystem can grow safely.

Definition of done:
- Public schema contracts are stable.
- Ontology versioning and deprecation rules exist.
- Plugins can evolve without breaking the core.

## Ongoing work tracks

### Fixtures and regression protection
- Every new detector or resolver should land with a fixture.
- Fixes must add a test so regressions cannot return.

### Ontology governance
- Additions require:
  - clear label and description
  - consistent naming and patterns
  - minimal duplication
- Deprecations must include a replacement plan.

### Safety and bounded authority
- Auto-apply stays conservative.
- Approval-required actions remain approval-required unless a policy explicitly allows them.

## Contribution sizing
Good first contributions:
- export guides and DAW checklists
- small ontology additions with examples
- new fixtures that catch real export failures

Bigger contributions:
- meter implementations with tests
- plugin host and schema validation in runtime
- translation profile work