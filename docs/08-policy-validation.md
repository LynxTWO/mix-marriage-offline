# Policy validation

This document defines deterministic validation rules for YAML policy files under `ontology/policies/`.

The goal is to fail fast on broken policy packs (missing files, bad IDs, layout/speaker mismatches, unsafe coefficients) before we run any audio analysis.

## Outputs

Validators emit **issues** using canonical IDs from `ontology/issues.yaml` (not ad-hoc strings). Policy validation issues are all `ISSUE.VALIDATION.*`.

- **error**: repository/policy integrity is broken; block downmix rendering.
- **warn**: allowed but suspicious; proceed but report.

## File resolution

- **Registry files** (example: `ontology/policies/downmix.yaml`) are loaded by explicit path.
- **Policy pack file paths inside a registry** are resolved **relative to the directory containing that registry file**.

Example:
- Registry: `ontology/policies/downmix.yaml`
- Registry entry: `file: "downmix_policies/standard_foldown_v0.yaml"`
- Resolved pack file: `ontology/policies/downmix_policies/standard_foldown_v0.yaml`

## Downmix registry validation rules

The downmix registry lives at `ontology/policies/downmix.yaml`.

### Required structure

**DMX.REG.001 (error)**
- Registry must parse as YAML.
- Root must contain `downmix`.
- On failure: `ISSUE.VALIDATION.POLICY_PARSE_ERROR`.

**DMX.REG.002 (error)**
- `downmix` must contain:
  - `_meta`
  - `policies` (map)
  - `default_policy_by_source_layout` (map)
  - `conversions` (list)
- On failure: `ISSUE.VALIDATION.POLICY_SCHEMA_INVALID`.

### Policy entries

For each `downmix.policies[POLICY.DOWNMIX.*]` entry:

**DMX.REG.010 (error)**
- Key must start with `POLICY.DOWNMIX.`.

**DMX.REG.011 (error)**
- `file` must be present and resolve to an existing file.
- On failure: `ISSUE.VALIDATION.POLICY_FILE_MISSING` with `EVID.FILE.PATH`.

**DMX.REG.012 (error)**
- Policy pack must parse as YAML and contain `downmix_policy_pack`.
- On failure: `ISSUE.VALIDATION.POLICY_PARSE_ERROR`.

**DMX.REG.013 (error)**
- `downmix_policy_pack.policy_id` must equal the policy registry key.
- On failure: `ISSUE.VALIDATION.DOWNMIX_POLICY_ID_MISMATCH`.

**DMX.REG.014 (error)**
- `supports_source_layouts` and `supports_target_layouts` must be lists of `LAYOUT.*`.
- Each referenced layout must exist in `ontology/layouts.yaml`.
- On failure: `ISSUE.VALIDATION.DOWNMIX_LAYOUT_UNKNOWN`.

### Default policy map

**DMX.REG.020 (error)**
- Every key in `default_policy_by_source_layout` must be a valid `LAYOUT.*`.
- Every value must exist in `downmix.policies`.
- On invalid layout: `ISSUE.VALIDATION.DOWNMIX_LAYOUT_UNKNOWN`.
- On unknown policy id: use `ISSUE.VALIDATION.DOWNMIX_POLICY_ID_MISMATCH` until a dedicated issue exists.

### Conversions

Each item in `downmix.conversions` must contain:
- `source_layout_id` (LAYOUT.*)
- `target_layout_id` (LAYOUT.*)
- `policy_id` (POLICY.DOWNMIX.*)
- `matrix_id` (string)

**DMX.REG.030 (error)**
- Layout IDs must exist in `ontology/layouts.yaml`.
- On failure: `ISSUE.VALIDATION.DOWNMIX_LAYOUT_UNKNOWN`.

**DMX.REG.031 (error)**
- `policy_id` must exist in `downmix.policies`.

**DMX.REG.032 (error)**
- The referenced pack file must contain `matrix_id`.
- On failure: `ISSUE.VALIDATION.DOWNMIX_MATRIX_ID_MISSING`.

**DMX.REG.033 (error)**
- The referenced matrix must declare `source_layout_id` and `target_layout_id` equal to the conversion.
- On failure: `ISSUE.VALIDATION.DOWNMIX_LAYOUT_SPEAKER_MISMATCH` (closest current ID; a dedicated “matrix layout mismatch” issue could be added later).

### Composition paths

**DMX.REG.040 (error)**
- If `composition_paths` is present, each `steps[*].matrix_id` must exist in its referenced policy pack.
- `steps` must form a contiguous chain: each step's `target_layout_id` equals the next step's `source_layout_id`.
- The first step source equals the composition path source; final step target equals composition path target.
- On missing matrices: `ISSUE.VALIDATION.DOWNMIX_MATRIX_ID_MISSING`.
- On layout chain mismatch: `ISSUE.VALIDATION.DOWNMIX_LAYOUT_SPEAKER_MISMATCH`.

## Downmix pack validation rules

Downmix packs live under `ontology/policies/downmix_policies/`.

### Required structure

**DMX.PACK.001 (error)**
- Pack must parse as YAML.
- Root key must be `downmix_policy_pack`.
- On failure: `ISSUE.VALIDATION.POLICY_PARSE_ERROR`.

**DMX.PACK.002 (error)**
- `downmix_policy_pack` must include:
  - `policy_id`
  - `pack_version` (semver string)
  - `matrices` (map)

### Matrix structure

For each `downmix_policy_pack.matrices[MATRIX_ID]`:

**DMX.PACK.010 (error)**
- `source_layout_id` and `target_layout_id` must exist in `ontology/layouts.yaml`.
- On failure: `ISSUE.VALIDATION.DOWNMIX_LAYOUT_UNKNOWN`.

**DMX.PACK.011 (error)**
- `coefficients` must be a map:
  - key: target speaker id `SPK.*`
  - value: map of source speaker id `SPK.*` to numeric linear gain

**DMX.PACK.012 (error)**
- Every target speaker key must exist in `ontology/speakers.yaml`.
- Every source speaker key must exist in `ontology/speakers.yaml`.
- On failure: `ISSUE.VALIDATION.DOWNMIX_SPEAKER_UNKNOWN`.

**DMX.PACK.013 (error)**
- Target speaker keys must match the target layout's `channel_order` **exactly** (same set).
  - Missing any target channel is an error (silent channel).
  - Extra target speakers not in the layout is an error.
- On failure: `ISSUE.VALIDATION.DOWNMIX_LAYOUT_SPEAKER_MISMATCH`.

**DMX.PACK.014 (error)**
- Any referenced **source** speaker must be part of the source layout's `channel_order`.
- On failure: `ISSUE.VALIDATION.DOWNMIX_LAYOUT_SPEAKER_MISMATCH`.

### Coefficient sanity

Coefficients are **linear gain** values.

**DMX.COEFF.001 (error)**
- Every coefficient must be a finite number.
- Reject non-numeric values, NaN, and infinity.
- On failure: `ISSUE.VALIDATION.DOWNMIX_COEFFICIENT_INVALID`.

**DMX.COEFF.002 (error)**
- Hard limit: `abs(coef) <= 4.0`.
- On failure: `ISSUE.VALIDATION.DOWNMIX_COEFFICIENT_INVALID`.

**DMX.COEFF.003 (warn)**
- Soft limit (translation sanity): if `abs(coef) > 2.0`, warn.
- On failure: `ISSUE.VALIDATION.DOWNMIX_COEFFICIENT_HIGH`.

**DMX.COEFF.004 (warn)**
- For each target channel, compute `sum_abs = sum(abs(coef))` across all sources feeding that target.
- If `sum_abs > 2.5`, warn (risk of unexpected level).
- If `sum_abs > 4.0`, error.

## Fixture format for policy validation

Policy-validation fixtures live under `fixtures/policies/`.

Each fixture YAML uses this minimal shape:

- `fixture_id` (string)
- `fixture_type` (string, must be `policy_validation`)
- `inputs.registry_file` (string path)
- `expected.issue_counts.error` and `expected.issue_counts.warn`
- `expected.must_include` (list of `{issue_id, severity_label, count_min}`)

The unit test runner should:
1. Load the fixture.
2. Run the policy validator on `inputs.registry_file`.
3. Assert the expected issue counts and required issue IDs.

