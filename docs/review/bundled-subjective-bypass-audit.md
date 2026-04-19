<!-- markdownlint-disable-file MD013 -->

# Bundled Subjective Bypass Audit

This pass applies the next approved bundled-plugin comment batch after the
corrective detector and resolver notes.

## Scope

Reviewed and commented in this batch:

- `src/mmo/dsp/plugins/registry.py`
- `src/mmo/plugins/subjective/__init__.py`
- `src/mmo/plugins/subjective/binaural_preview_v0.py`

Proof checks for the selected boundaries:

- `tests/test_subjective_plugins.py`
- `tests/test_subjective_binaural_preview.py`
- `tests/test_cli_safe_render.py`
- `docs/review/bundled-plugin-review.md`
- `docs/unknowns/bundled-plugin-review.md`

## What this batch clarified

### Subjective plugins are a DSP-side allowlist, not manifest-loaded installs

`src/mmo/dsp/plugins/registry.py` now says the quiet rule directly: the
subjective pack is a deliberate DSP-side exception. Its plugin IDs resolve from
the in-memory multichannel registry without going through `plugin_loader`,
bundled manifests, or market roots.

`src/mmo/plugins/subjective/__init__.py` now reinforces the same boundary at
the package root so the shipped allowlist is visible where the pack is defined.

### Binaural preview uses the fixed shipped module directly

`src/mmo/plugins/subjective/binaural_preview_v0.py` now says the trust
boundary directly:

- the binaural target calls `BinauralPreviewV0Plugin` from shipped code instead
  of resolving a manifest-backed plugin entrypoint
- `build_headphone_preview_manifest()` derives preview outputs from renderer
  manifests, but plugin selection remains fixed to the shipped binaural preview
  module
- this path therefore lives beside the main manifest-loader flow, not inside it

## What remained unchanged

- subjective plugin IDs and deterministic registry order
- binaural preview renderer and action IDs
- headphone preview render behavior and metadata shape
- CLI binaural target flow and emitted preview deliverables
- bundled fallback, market-install, and manifest-loader behavior outside this
  subjective exception

## Coverage decision

The bundled-plugin slice can now move from `mapped` to `commented`.

Reason:

- loader, market, shipped renderers, corrective approval paths, and the
  subjective bypass all now have targeted code or audit notes
- the remaining bundled-plugin questions are evidence gaps about checkout
  examples and offline market parity, not missing trust-boundary notes on the
  main shipped code paths

That status change does not close those remaining unknowns.

## What still needs follow-up

This batch did not resolve:

- checkout-example visibility under `plugins/examples/*`
- offline market parity between `src/mmo/data/plugin_market/assets/plugins/*`
  and shipped `src/mmo/plugins/*`

Those stay open in `docs/unknowns/bundled-plugin-review.md` and should be
handled as evidence work, not folded into another protected comment batch.
