<!-- markdownlint-disable-file MD013 -->

# Bundled Plugin Trust-Boundary Audit

This pass applies the first approved bundled-plugin comment batch.

## Scope

Reviewed and commented in this batch:

- `src/mmo/core/plugin_loader.py`
- `src/mmo/core/plugin_market.py`

Proof checks for the selected boundaries:

- `tests/test_plugin_loader.py`
- `tests/test_plugin_market.py`
- `docs/review/bundled-plugin-review.md`
- `docs/unknowns/bundled-plugin-review.md`

## What this batch clarified

### Loader authority stays root-based

`src/mmo/core/plugin_loader.py` now says the quiet rules directly:

- explicit `plugin_dir` beats `MMO_PLUGIN_DIR`
- a blank `MMO_PLUGIN_DIR` counts as unset
- a missing explicit external root is a hard error
- a missing implicit default external root is skipped
- bundled packaged manifests stay in candidate order, but they are fallback at
  the root level
- once any repo or external root yields entries, packaged fallback stops
  contributing entries for that load
- primary and external roots are peers, so duplicate `plugin_id` values raise
  instead of shadowing
- manifest validation and import trust stay scoped to one root at a time

### Market install scope stays narrow

`src/mmo/core/plugin_market.py` now says the install boundary directly:

- market installs only accept plugin-relative files under `plugins/`
- entrypoints must still resolve to plugin-relative modules
- explicit index-path overrides are trusted operator input, but extra probes
  stay anchored to that trusted index
- `installable` means the market can resolve a manifest and module without
  importing plugin code
- `installed` means active plugin-root scanning already sees the plugin
- the market index is only a locator, while the manifest on disk is the
  authority before any copy happens

## What remained unchanged

- plugin root precedence
- bundled fallback behavior
- duplicate-ID failure behavior
- market asset resolution order
- manifest authority before install
- install target behavior and idempotent copy semantics

## What still needs a later protected batch

This batch did not cover:

- shipped renderers under `src/mmo/plugins/renderers/`
- approval-gated corrective detectors and resolvers
- the subjective-pack bypass in `src/mmo/dsp/plugins/registry.py` and
  `src/mmo/plugins/subjective/`

Those paths still need their own approval-aware comment pass or trust-boundary
audit.
