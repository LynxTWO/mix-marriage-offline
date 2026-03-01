# MMO docs index

This folder is the canonical documentation set for Mix Marriage Offline (MMO).

The numeric prefixes reflect a recommended reading order. Gaps may exist as documents evolve.

## Start here

- [manual/00-manual-overview.md](manual/00-manual-overview.md)
  **User Manual** — the canonical end-user guide: install, workflows, safe-render,
  translation QA, plugins, projects, and troubleshooting.
  Chapter order is defined in [manual/manual.yaml](manual/manual.yaml).
- [user_guide.md](user_guide.md)
  Quickstart pointer with the most common commands. For depth, see the User Manual.
- [00-quickstart.md](00-quickstart.md)
  Golden-path walkthrough: stems to project scaffold in five minutes.
- [STATUS.md](STATUS.md)
  Live project checklist with milestone definitions and done criteria.
- [milestones.yaml](milestones.yaml)
  Machine-readable milestone IDs, states, and doc section links.

## Installed vs checkout paths

- Repo checkout mode may use `plugins/` as the primary plugin root.
- Installed package mode always has bundled manifests under `mmo.data/plugins`.
- Runtime plugin scanning order is: primary (`--plugins`), external (`--plugin-dir`
  or `~/.mmo/plugins`), then built-in packaged root fallback.

## Contribution workflow

- [Status system (`STATUS.md` + `milestones.yaml`)](STATUS.md)
  Keep milestone checklist state and machine-readable milestone state aligned.
- [13-plugin-authoring.md](13-plugin-authoring.md)
  Minimum viable plugin package checklist for GUI-visible plugin metadata.
- [PR checklist template](../.github/pull_request_template.md)
  Required checklist for milestone links, state moves, changelog updates, and validation/tests reporting.

## Recommended reading order

1. [00-proposal.md](00-proposal.md)
2. [01-philosophy.md](01-philosophy.md)  
3. [02-architecture.md](02-architecture.md)  
4. [03-ontology.md](03-ontology.md)  
5. [04-plugin-api.md](04-plugin-api.md)  
6. [13-plugin-authoring.md](13-plugin-authoring.md)  
7. [05-fixtures-and-ci.md](05-fixtures-and-ci.md)  
8. [06-roadmap.md](06-roadmap.md)  
9. [07-export-guides.md](07-export-guides.md)  
10. [08-policy-validation.md](08-policy-validation.md)  
11. [PROJECT_INSTRUCTIONS.md](PROJECT_INSTRUCTIONS.md)  
12. [SCENE_AND_RENDER_CONTRACT_OVERVIEW.md](SCENE_AND_RENDER_CONTRACT_OVERVIEW.md)  

## Scene-first contracts

- [PROJECT_INSTRUCTIONS.md](PROJECT_INSTRUCTIONS.md)  
  Core architecture requirements for mix-once/render-many, Objective Core boundaries, determinism, and plugin semantics.
- [SCENE_AND_RENDER_CONTRACT_OVERVIEW.md](SCENE_AND_RENDER_CONTRACT_OVERVIEW.md)  
  MVP scene model plus render target contract, gate expectations, and deterministic backoff behavior.

## Product vision and UX

- [09-product-vision.md](09-product-vision.md)  
  Product promise (“technical co-pilot”), user stories, and mode overview.
- [10-authority-profiles.md](10-authority-profiles.md)  
  Guide vs Assist vs Full send, hard stops vs taste gates, safety rules.
- [11-gui-vision.md](11-gui-vision.md)  
  Musician-first GUI principles, nerd toggle, screens, and rollout milestones.
- [12-gui-dev.md](12-gui-dev.md)
  First runnable GUI dev shell (thin client over `mmo gui rpc`) and cross-platform smoke steps.
- [17-stem-discovery.md](17-stem-discovery.md)  
  Stem-set scan/classify/review flow, safe override artifact, and confidence-first behavior.
- [18-corpus-scanning.md](18-corpus-scanning.md)
  Private names-only corpus scan flow for role lexicon refinement.
- [19-stems-drafts.md](19-stems-drafts.md)
  Preview-only scene and routing plan drafts from classified stems.
- [20-stems-audition.md](20-stems-audition.md)
  Per-bus-group WAV audition pack rendering and manifest format.
- [21-loudness-profiles.md](21-loudness-profiles.md)
  Data-driven `LOUD.*` profile contracts for render/preflight receipts.

## Conventions

- Use relative links between docs (e.g., `(10-authority-profiles.md)`).
- Keep terminology aligned with ontology IDs (actions, issues, gates, reasons).
- Prefer “what/why/where/confidence” for any detector output and “what changed/why/limits” for any resolver output.
