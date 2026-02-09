# Scene and Render Contract Overview

This document defines the minimum scene/render contract for MMO's mix-once, render-many architecture.

## A) Minimal viable scene model (MVP)

A scene contains layout-agnostic intent, not fixed speaker routing.

### Objects (stems)

Each object includes:

- Position/width/depth hints
  - position hint (for example azimuth, optional elevation)
  - width hint
  - depth hint (directness/distance proxy)
- Confidence
- Locks (for example, do not move, preserve dynamics, preserve tone)

### Bed/field hints

- Diffuse distribution hints for surround/height style placement
- Hints are advisory, not forced channel assignment

### Out of scope for MVP

- No ML instrument detection is required
- No requirement to infer full object metadata from stereo-only content
- No automatic "creative intent generation" beyond explicit user intent plus bounded inference

## B) Render target contract

A render target must define:

- Canonical channel ordering
- Speaker positions when required by processing or export format
- Downmix policy references (stable IDs)
- Safety limits with context-based thresholds (`suggest`, `auto_apply`, `render`)

Render contracts must rely on canonical ontology layout definitions to avoid channel-order drift.

## C) QA and gates expectations

Renderers must:

- Respect gate outcomes for the target context (`render` vs `auto_apply`)
- Emit artifacts with deterministic metadata (no wall-clock creation timestamps)
- Provide clear "why blocked" explanations with stable IDs

High-level gate/backoff loop:

1. Run render attempt with current settings.
2. Evaluate similarity and safety gates (including downmix and correlation risk).
3. If gates fail and an allowed backoff exists, apply conservative backoff and re-render.
4. Stop after a deterministic maximum attempt count; do not loop endlessly.
5. Emit a deterministic attempt log describing what was tried and why the final state passed or blocked.

When similarity gates fail, renderer must back off or stop. When correlation risk is high, renderer must reduce risk conservatively or stop. In both cases, behavior must be deterministic and explainable.

## D) Position stereo properly

- Stereo is one render target among many.
- When scene plus intent plus layout contracts exist, they are the source of truth.
- Stereo assets can inform inference, but must not override explicit scene locks or user intent.

## Related docs

- [PROJECT_INSTRUCTIONS.md](PROJECT_INSTRUCTIONS.md)
- [09-product-vision.md](09-product-vision.md)
- [11-gui-vision.md](11-gui-vision.md)
