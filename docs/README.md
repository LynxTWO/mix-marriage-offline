# MMO docs index

This folder is the canonical documentation set for Mix Marriage Offline (MMO).

The numeric prefixes reflect a recommended reading order. Gaps may exist as documents evolve.

## Recommended reading order

1. [00-proposal.md](00-proposal.md)  
2. [01-philosophy.md](01-philosophy.md)  
3. [02-architecture.md](02-architecture.md)  
4. [03-ontology.md](03-ontology.md)  
5. [04-plugin-api.md](04-plugin-api.md)  
6. [05-fixtures-and-ci.md](05-fixtures-and-ci.md)  
7. [06-roadmap.md](06-roadmap.md)  
8. [07-export-guides.md](07-export-guides.md)  
9. [08-policy-validation.md](08-policy-validation.md)  
10. [PROJECT_INSTRUCTIONS.md](PROJECT_INSTRUCTIONS.md)  
11. [SCENE_AND_RENDER_CONTRACT_OVERVIEW.md](SCENE_AND_RENDER_CONTRACT_OVERVIEW.md)  

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

## Conventions

- Use relative links between docs (e.g., `(10-authority-profiles.md)`).
- Keep terminology aligned with ontology IDs (actions, issues, gates, reasons).
- Prefer “what/why/where/confidence” for any detector output and “what changed/why/limits” for any resolver output.
