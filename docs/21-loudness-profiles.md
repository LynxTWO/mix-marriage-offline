# 21) Loudness Profiles

## Why this exists

`LOUD.*` loudness profiles are render contracts. A render run selects one
`loudness_profile_id`, and MMO writes a deterministic receipt to preflight and
render report artifacts:

- target loudness
- tolerance window (or `null` when not defined by the source guidance)
- true-peak ceiling
- metering `method_id`
- compliance mode and warnings

This keeps loudness intent data-driven and versionable without code edits for
every profile addition.

## Compliance vs informational profiles

Profiles declare `compliance_mode`:

- `compliance`: intended as a delivery-facing loudness target.
- `informational`: advisory guidance only (for example playback normalization).

Profiles can also declare `best_effort: true` when the external guidance cites
older meter revisions while MMO meters with `BS.1770-5`.

## Unsupported method guardrail

If a profile references a loudness method that is registered but not yet
implemented (for example dialog-gated placeholders), MMO:

- records the selected profile in receipts,
- emits an explicit warning (`not implemented yet`),
- does not hard-fail render planning/report generation.

If a profile is unknown, request validation fails with a deterministic error
listing known profile IDs.

## Registry locations

- Source of truth: `ontology/loudness_profiles.yaml`
- Schema: `schemas/loudness_profiles.schema.json`
- Packaged mirror:
  - `src/mmo/data/ontology/loudness_profiles.yaml`
  - `src/mmo/data/schemas/loudness_profiles.schema.json`

## Add/update workflow (no code changes needed for profile values)

1. Edit `ontology/loudness_profiles.yaml`.
2. Validate against `schemas/loudness_profiles.schema.json`.
3. Keep profile IDs sorted for deterministic loading.
4. Run `python tools/sync_packaged_data_mirror.py`.
5. Run `python tools/validate_contracts.py` and tests.

Only add new `LOUD.*` IDs; do not rename published IDs.
