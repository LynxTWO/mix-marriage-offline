<!-- markdownlint-disable-file MD013 -->

# Bundled Plugin Review

This read-only pass maps the bundled-plugin slice that was still deferred in
`docs/architecture/coverage-ledger.md`.

## Scope and method

Reviewed in this pass:

- bundled manifests under `plugins/`
- packaged fallback manifests under `src/mmo/data/plugins/`
- shipped implementation modules under `src/mmo/plugins/`
- offline market assets under `src/mmo/data/plugin_market/assets/plugins/`
- authority and install paths in `src/mmo/core/plugin_loader.py`,
  `src/mmo/core/plugin_market.py`, `src/mmo/resources.py`,
  `src/mmo/core/plugin_validation.py`, and `src/mmo/core/plugin_schema_index.py`
- direct shipped bypass paths in `src/mmo/dsp/plugins/registry.py`,
  `src/mmo/core/binaural_target.py`, and `src/mmo/cli_commands/_renderers.py`
- supporting docs and tests in `docs/architecture/system-map.md`,
  `docs/architecture/repo-slices.md`, `tests/test_plugin_loader.py`, and
  `tests/test_plugin_market.py`

## What this pass confirmed

### `src/mmo/data/plugins/` is fallback manifest authority, not a second code tree

`tools/sync_packaged_data_mirror.py` only mirrors allowlisted plugin manifests
into `src/mmo/data/plugins/`. `src/mmo/resources.py` resolves that directory as
the built-in plugin root in installed mode, and
`src/mmo/core/plugin_loader.py` loads it after explicit and external plugin
roots. The packaged mirror is real runtime fallback authority, but it does not
ship Python implementation modules.

### Bundled plugin behavior is split across more than one shipped surface

The repo does not ship one uniform bundled-plugin set.

In this checkout:

- `plugins/` exposes 22 plugin manifests, including `plugins/examples/*`
- `src/mmo/data/plugins/` exposes 16 packaged fallback manifests
- `src/mmo/data/plugin_market/assets/plugins/` exposes 25 market-installable
  manifests plus Python modules

That split matters because checkout behavior, packaged fallback behavior, and
offline market installs do not surface the same plugin catalog.

### Shipped implementation behavior still lives in `src/mmo/plugins/*`

The fallback manifests point at entrypoints such as
`mmo.plugins.renderers.safe_renderer:SafeRenderer`, so executable behavior
still comes from shipped modules under `src/mmo/plugins/*`.

The reviewed implementation set includes:

- renderers that write or audit outputs, such as
  `mixdown_renderer.py`, `placement_mixdown_renderer.py`,
  `gain_trim_renderer.py`, and `safe_renderer.py`
- detectors and resolvers that shape auto-apply or approval behavior, such as
  `clipping_headroom_detector.py`, `headroom_gain_resolver.py`,
  `lfe_corrective_detector.py`, and `lfe_corrective_resolver.py`

### Offline market assets are a separate authority path

`src/mmo/core/plugin_market.py` installs plugins by copying manifests and
modules from `src/mmo/data/plugin_market/assets/plugins/` into a writable
external root. That asset tree is not the same thing as the smaller packaged
fallback manifest root under `src/mmo/data/plugins/`.

This means bundled plugin behavior is split across:

- repo manifests in `plugins/`
- packaged fallback manifests in `src/mmo/data/plugins/`
- shipped implementation modules in `src/mmo/plugins/`
- offline market assets in `src/mmo/data/plugin_market/assets/plugins/`

### `plugins/examples/*` is a checkout-only runtime wrinkle

`docs/13-plugin-authoring.md` treats the example plugins as authoring material,
but `src/mmo/core/plugin_loader.py` will still discover them when the primary
plugin root is the repo checkout `plugins/` tree.

That makes checkout behavior broader than packaged fallback behavior. The
examples are valid manifests, not inert docs blobs.

### The subjective pack bypasses the manifest loader

`src/mmo/dsp/plugins/registry.py` hard-registers the subjective pack, and
`src/mmo/plugins/subjective/binaural_preview_v0.py` is called through
`src/mmo/core/binaural_target.py` and `src/mmo/cli_commands/_renderers.py`
without going through the main manifest loader.

That is shipped plugin-like behavior, but it sits outside the bundled manifest
roots that earlier slice wording implied.

## Coverage decision

Move the bundled-plugin slice from `deferred` to `mapped`.

Reason:

- the slice is no longer a vague follow-up
- the authority split and main trust boundaries are now identified with repo
  evidence
- the slice is still not explained well enough to call it `commented`

## What remains unclear

- whether `plugins/examples/*` should stay runtime-discoverable in a repo
  checkout or should remain authoring-only material
- how closely the offline market asset tree must match shipped
  `src/mmo/plugins/*` modules over time
- whether the subjective pack should stay a DSP-side exception or move into a
  more explicit plugin-authority note

See `docs/unknowns/bundled-plugin-review.md`.

## Follow-up status

The first two protected follow-ups now landed on this branch:

- loader and market authority notes in `src/mmo/core/plugin_loader.py` and
  `src/mmo/core/plugin_market.py`
- shipped renderer invariants in `mixdown_renderer.py`,
  `placement_mixdown_renderer.py`, and `safe_renderer.py`

The next highest-value follow-up is the remaining approval-sensitive part of
the slice:

- approval-gated corrective behavior in `lfe_corrective_detector.py` and
  `lfe_corrective_resolver.py`
- the subjective-pack bypass in `src/mmo/dsp/plugins/registry.py` and
  `src/mmo/plugins/subjective/`
