# MMO Docs Index

This folder is the canonical documentation set for Mix Marriage Offline (MMO).

The numbered docs are the primary human-facing reference set for product
behavior, workflows, and architecture. Runtime authority still lives in the
backend, schemas, and ontology where those sources are named explicitly.
Non-numbered one-offs are kept only as supporting reference when still useful.

## Current Shipped Capabilities

- Deterministic analysis, report export, and contract artifacts.
- Scene-first, mix-once/render-many workflows across CLI and desktop paths.
- Compare workflows with `compare_report.json` and fair-listen `loudness_match`
  disclosure.
- Render targets from stereo through immersive, plus first-class binaural
  headphone delivery and preview flows.
- Five supported channel-ordering standards: `SMPTE`, `FILM`, `LOGIC_PRO`,
  `VST3`, and `AAF`.
- Tauri desktop workflow screens for
  `Validate -> Analyze -> Scene -> Render -> Results -> Compare`, including
  deterministic scene-lock editing and artifact-backed results/compare parity.

## Current Limits

- Desktop claims and release assets must map to the shipped Tauri app or the
  CLI; there is no secondary Python desktop shell.
- MMO does not replace proprietary Atmos renderers or licensed Dolby
  workflows.
- Automated packaged smoke is part of CI, but final human fresh-install
  signoff still happens when promoting a release candidate or public tag.

## Start Here

- [manual/00-manual-overview.md](manual/00-manual-overview.md) User Manual.
  Canonical end-user install, workflow, troubleshooting, and GUI walkthrough
  sequence.
- [00-quickstart.md](00-quickstart.md) Golden-path walkthrough from stems to
  project scaffold and render-ready artifacts.
- [02-architecture.md](02-architecture.md) Architecture as shipped today:
  deterministic artifacts, scene/render flow, compare, delivery, and desktop
  paths.
- [semantic_contracts.md](semantic_contracts.md) One-page ownership map for
  canonical IDs, backend authority, plugin manifest semantics, and intentional
  render-surface mirroring.
- [15-target-selection.md](15-target-selection.md) Canonical target tokens,
  shorthands, and binaural target behavior.
- [18-channel-standards.md](18-channel-standards.md) Canonical channel-ordering
  standards contract.
- [11-gui-vision.md](11-gui-vision.md) Current GUI direction, shipped surfaces,
  and desktop workflow stabilization notes.
- [STATUS.md](STATUS.md) Live milestone checklist and current completion
  boundaries.
- [milestones.yaml](milestones.yaml) Machine-readable milestone IDs, states, and
  doc section links.

## Canonical Doc Map

- Core product framing: [00-proposal.md](00-proposal.md),
  [01-philosophy.md](01-philosophy.md),
  [09-product-vision.md](09-product-vision.md)
- Semantic ownership: [semantic_contracts.md](semantic_contracts.md),
  [03-ontology.md](03-ontology.md)
- Scene/render contracts: [02-architecture.md](02-architecture.md),
  [13-gui-handshake.md](13-gui-handshake.md),
  [15-target-selection.md](15-target-selection.md),
  [18-channel-standards.md](18-channel-standards.md)
- Exports, translation, and delivery:
  [07-export-guides.md](07-export-guides.md),
  [16-translation-checks.md](16-translation-checks.md),
  [21-loudness-profiles.md](21-loudness-profiles.md)
- Plugins and ontology: [03-ontology.md](03-ontology.md),
  [04-plugin-api.md](04-plugin-api.md),
  [13-plugin-authoring.md](13-plugin-authoring.md)
- GUI and desktop: [11-gui-vision.md](11-gui-vision.md),
  [12-gui-design-system.md](12-gui-design-system.md),
  [12-gui-dev.md](12-gui-dev.md), [gui_parity.md](gui_parity.md)

## Contribution Workflow

- [Contributor AI workflow](contributing/ai-workflow.md) Repo-fit workflow for
  evidence review, doc triggers, unknowns, approval gates, and comment drift.
- [Status system (`STATUS.md` + `milestones.yaml`)](STATUS.md) Keep milestone
  checklist state and machine-readable milestone state aligned.
- [architecture/system-map.md](architecture/system-map.md) Inventory of runtime
  units, entrypoints, local artifact stores, config inputs, and trust
  boundaries.
- [unknowns/architecture-pass.md](unknowns/architecture-pass.md) Architecture
  inventory uncertainty log. Record unresolved boundaries here instead of
  guessing.
- [13-plugin-authoring.md](13-plugin-authoring.md) Starter-pack workflow for
  first plugins, including execution mode, determinism, and safety semantics.
- [../examples/plugin_authoring/README.md](../examples/plugin_authoring/README.md)
  Copyable manifests, example plugins, and an intentional invalid manifest.
- [PR checklist template](../.github/pull_request_template.md) Required
  checklist for milestone links, changelog updates, and validation reporting.

## Installed Vs Checkout Paths

- Repo checkout mode may use `plugins/` as the primary plugin root.
- Installed package mode always has bundled manifests under `mmo.data/plugins`.
- Runtime plugin scanning order is primary (`--plugins`), external
  (`--plugin-dir` or `~/.mmo/plugins`), then built-in packaged root fallback.

## Recommended Reading Order

1. [00-proposal.md](00-proposal.md)
2. [01-philosophy.md](01-philosophy.md)
3. [02-architecture.md](02-architecture.md)
4. [semantic_contracts.md](semantic_contracts.md)
5. [03-ontology.md](03-ontology.md)
6. [04-plugin-api.md](04-plugin-api.md)
7. [05-fixtures-and-ci.md](05-fixtures-and-ci.md)
8. [07-export-guides.md](07-export-guides.md)
9. [09-product-vision.md](09-product-vision.md)
10. [11-gui-vision.md](11-gui-vision.md)
11. [13-plugin-authoring.md](13-plugin-authoring.md)
12. [15-target-selection.md](15-target-selection.md)
13. [18-channel-standards.md](18-channel-standards.md)

## Legacy Reference Notes

- [PROJECT_INSTRUCTIONS.md](PROJECT_INSTRUCTIONS.md) and
  [SCENE_AND_RENDER_CONTRACT_OVERVIEW.md](SCENE_AND_RENDER_CONTRACT_OVERVIEW.md)
  are older deep-dive references. Prefer the numbered docs above when linking
  new readers into the docs set.

## Conventions

- Use relative links between docs, for example `(10-authority-profiles.md)`.
- Keep terminology aligned with ontology IDs.
- Prefer "what/why/where/confidence" for detector output and "what
  changed/why/limits" for resolver or delivery output.
