<!-- markdownlint-disable-file MD013 -->

# Bundled Renderer Comment Audit

This pass applies the next approved bundled-plugin comment batch after the
loader and market authority notes.

## Scope

Reviewed and commented in this batch:

- `src/mmo/plugins/renderers/mixdown_renderer.py`
- `src/mmo/plugins/renderers/placement_mixdown_renderer.py`
- `src/mmo/plugins/renderers/safe_renderer.py`

Proof checks for the selected boundaries:

- `tests/test_mixdown_renderer_multiformat.py`
- `tests/test_placement_mixdown_renderer.py`
- `tests/test_corrective_plugins.py`
- `docs/review/bundled-plugin-review.md`
- `docs/review/remediation-backlog.md`

## What this batch clarified

### Baseline mixdown stays a stable reference renderer

`src/mmo/plugins/renderers/mixdown_renderer.py` now says the quiet rule
directly: recommendation IDs are recorded for audit context, but recommendation
payloads do not steer the baseline DSP path.

The new comments also pin the deterministic trace boundary to the written file
and render seed. That keeps later receipt and metadata checks tied to the same
artifact that was exported.

### Placement rendering treats stereo as the QA anchor

`src/mmo/plugins/renderers/placement_mixdown_renderer.py` now says the trust
boundary directly:

- stereo is the reference artifact for later immersive layout QA
- decorrelation and similarity QA stay dormant until that stereo master exists
- the saved stereo master path is the one later layouts compare against
- manifest output order is part of the review surface and should stay stable

### Safe renderer still fails closed

`src/mmo/plugins/renderers/safe_renderer.py` already carried most of its
approval-audit explanation. This batch only tightened one remaining rule:
unknown or incomplete recommendation policy metadata defaults to
`requires_approval` instead of drifting into implicit approval.

## What remained unchanged

- baseline mixdown DSP behavior and output layout set
- placement render intent, fallback, and similarity QA behavior
- safe renderer output shape and recommendation classification behavior

## What still needs a later protected batch

This batch did not cover:

- approval-gated corrective detectors and resolvers such as
  `lfe_corrective_detector.py` and `lfe_corrective_resolver.py`
- the subjective-pack bypass in `src/mmo/dsp/plugins/registry.py` and
  `src/mmo/plugins/subjective/`
- checkout-example and offline market parity questions recorded in
  `docs/unknowns/bundled-plugin-review.md`

Those paths still need their own approval-aware comment pass or trust-boundary
audit.
