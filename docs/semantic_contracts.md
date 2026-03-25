# Semantic Contracts

This is the short ownership map for contributors. Use it when a field, ID, or
surface looks repetitive and you need to know what is canonical, what is
metadata, and what is intentionally mirrored.

## Canonical IDs and ownership

- `stem_id` is the canonical cross-pipeline stem identity for classify,
  bus-plan, scene, analyze, and render.
- `source_file_id` is traceability metadata. It may appear in artifacts, but it
  is not the cross-pipeline join key.
- Canonical ontology IDs live in `ontology/*.yaml`. New `ISSUE.*` IDs are owned
  by `ontology/issues.yaml` and must be registered there before they appear in
  code, tests, or UI fixtures.

## Status and issue authority

- Backend status vocabularies are owned by `src/mmo/core/statuses.py` and kept
  in schema sync through `schemas/statuses.schema.json`.
- CLI and desktop labels map from backend semantics. UI and CLI do not invent
  new status meanings inline.
- Schemas document and validate shared semantics, but UI/CLI still map from the
  backend-owned meanings rather than defining those meanings themselves.

## Plugin manifest semantics

- `capabilities` is the runtime and host execution contract: topology, layout
  safety, determinism, purity, and invocation constraints.
- `declares` is semantic purpose metadata: ontology relationships such as
  emitted issues, consumed issues, suggested actions, related features, problem
  domains, and target scopes.
- `behavior_contract` is the bounded audible-change promise: loudness, peak,
  phase/image, compensation, and any rationale for looser bounds.
- Built-in and example plugins often declare `max_channels: 32` to mean session
  compatibility. Lawful execution is still constrained by `channel_mode`,
  `supported_group_sizes`, `supported_link_groups`, `scene_scope`, and
  layout-safety fields.

## Render artifact ownership and intentional mirroring

- Repeated-looking render fields are not automatically legacy clutter.
- In render plans, `request` is the request echo, `resolved` and
  `resolved_layouts` are planner resolution outputs, and job fields such as
  `target_id`, `resolved_target_id`, and `target_layout_id` carry execution and
  compatibility context.
- In render receipts and manifests, summaries such as `deliverables_summary`,
  `deliverable_summary_rows`, `result_summary`, `scene_binding_summary`, and
  `preflight_summary` may intentionally exist in both artifacts so UI, CLI,
  smoke, fixtures, and diagnostics can consume stable summaries independently.
- Do not delete a mirrored surface just because another artifact carries
  similar information. Remove a field only when it is provably dead.

## Current stabilization posture

- The repo has a tagged `1.0.0` public release line, but contributor work
  still includes documentation truthfulness, contract-clarity, and
  conservative cleanup passes.
- Prefer documenting ownership and tightening semantics over broad renames or
  mass field removal.
- When a field looks redundant, classify it first as canonical data, metadata,
  convenience surface, parity surface, or dead legacy echo. Only the last
  category is a removal candidate.
