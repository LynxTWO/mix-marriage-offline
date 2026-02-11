# Mix Marriage Offline (MMO) Project Instructions

This document defines the foundational architecture constraints for MMO.

## A) Updated goal

MMO explicitly supports **mix once, render many**.

Pipeline:

`analyze + intent -> scene -> render targets (stereo, 5.1, 7.1.4, ...)`

The scene is the source of truth when stems plus intent are available.

## B) Objective Core vs Subjective Plugins

### Objective Core (non-negotiable contracts)

- Metering, validation, lockfile/caching determinism guards
- Gates: safety, translation, downmix similarity
- Schemas, ontologies, and output artifacts (reports, bundles, manifests)
- Stable IDs, canonical ordering, and deterministic execution behavior

### Subjective Plugins (extensible strategy layer)

- Detectors (suggestions), resolvers (optional), renderers (deliverables)
- Must not bypass Objective Core contracts or gate outcomes
- Must declare capabilities:
  - `max_channels`
  - supported layouts
  - supported contexts (`suggest`, `auto_apply`, `render`)

## C) Determinism requirements (minimum: up to 32 channels)

- Stable ordering everywhere: IDs, outputs, manifests, reports, artifact listings
- Seeded decorrelation policies when used; seed source must be documented and stable
- Consistent dither/noise policies; same inputs plus same settings must produce same outputs
- No time-based metadata in outputs (for example, no creation timestamps in encoded formats)
- Deterministic retry/backoff limits and deterministic attempt ordering
- If BLAS/OpenMP backends show allocation hiccups or nondeterministic performance variance during validation, pin backend thread counts:
  - `OPENBLAS_NUM_THREADS=1`
  - `OMP_NUM_THREADS=1`
  - `MKL_NUM_THREADS=1`
  - `VECLIB_MAXIMUM_THREADS=1` (macOS)
  - `NUMEXPR_NUM_THREADS=1`
- These environment settings do not change mix decisions; they reduce runtime variability in numeric backends.

## D) Layout safety principles

- Downmix similarity gates (`LUFS delta`, `True Peak delta`, `Correlation delta`) are conservative guardrails
- Phase/correlation risk checks use conservative backoff; system should block or advise, not silently "fix"
- Stereo is a render target, not automatically the source of truth when stems plus intent exist
- Gate outcomes must be explainable with stable IDs and clear reason text

## E) Required plugin semantics

Every plugin must declare and honor:

- `channel_mode`: explicit mono/stereo/multichannel behavior and assumptions
- `link_groups`: how linked multi-stem processing is declared (for example, drum bus)
- Latency reporting: plugin must report added latency (samples or ms), even if currently unused by host flow
- `determinism_seed` behavior: where the seed comes from and how it is applied
- Speaker position requirements: if positions are needed, renderer/plugin must consume canonical layout definitions

## F) Advisory inference policy

Stereo stems with baked pan/width are inference-only:

- Inference must be confidence-gated
- Inference must never overwrite explicit user locks or intent
- Inference must be explained (`what`, `why`, `where`, `confidence`)

## G) Nerd toggle philosophy

- Default UI hides jargon and prioritizes clear outcomes
- Nerd mode reveals IDs, meters, gates, thresholds, and parameters
- Both views must represent the same underlying truth and decisions

## Validation

- `make validate`
- `python tools/validate.py`
- `python tools/validate_contracts.py`
- `python -m pytest` automatically prefers local `src/` imports via `tests/conftest.py`.
- `PYTHONPATH=src` is still valid, but no longer required for pytest in this repository.

## Related docs

- [SCENE_AND_RENDER_CONTRACT_OVERVIEW.md](SCENE_AND_RENDER_CONTRACT_OVERVIEW.md)
- [14-scene-templates.md](14-scene-templates.md)
- [09-product-vision.md](09-product-vision.md)
- [11-gui-vision.md](11-gui-vision.md)
