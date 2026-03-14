# Plugin Authoring: Minimum Viable Package

This checklist defines the minimum plugin package needed for GUI-visible
metadata. Use it when creating a new plugin under `plugins/`.

## 1. Required package files

- `*.plugin.yaml` manifest (or `plugin.yaml`) with valid `plugin_id`,
  `plugin_type`, `version`, and `entrypoint`.
- `ui/layout.json` referenced by `ui_layout` in the manifest.
- `config_schema` object in the manifest with parameter `properties`.
- `x_mmo_ui` blocks on all parameters referenced by the layout.

Example starter pack:

- `plugins/examples/gain_v0/gain_v0.plugin.yaml`
- `plugins/examples/gain_v0/ui/layout.json`

## 1.1 External plugin roots

MMO now loads plugins from three roots:

- Primary root: `--plugins` (default: `plugins/` in repo mode).
- External root: `~/.mmo/plugins/` by default, or `--plugin-dir <path>` to
  override.
- Built-in packaged root: `mmo.data/plugins` (loaded last when present).

External plugin manifests are automatically validated (schema + ontology
semantics) before registration. Duplicate `plugin_id` values across
primary/external roots are rejected deterministically; built-in packaged
manifests are fallback-only.

## 2. Manifest checklist

- `plugin_id` matches schema pattern for the plugin type (for renderer:
  `PLUGIN.RENDERER.*`).
- `entrypoint` imports successfully.
- `capabilities` uses supported fields (`max_channels`, `channel_mode`,
  `link_groups`, `latency`, `deterministic_seed_policy`, `dsp_traits`,
  `bed_only`, `supported_standards`, `preferred_standard`,
  `supported_layout_ids`, `supported_contexts`, `scene`, `notes`).
- Renderer manifests must declare `capabilities.deterministic_seed_policy`.
- Renderer manifests must declare `capabilities.dsp_traits.tier` and
  `capabilities.dsp_traits.linearity`.
- If `capabilities.dsp_traits.linearity` is `nonlinear`, `anti_aliasing` must be
  `oversampling` or `bandlimited` (not `none`).
- Treat `capabilities.dsp_traits.measurable_claims` as the plugin truth
  contract. Include at least one measurable claim with `metric_id` and expected
  direction.
- If `channel_mode` is `linked_group` or `true_multichannel`, declare
  `supported_standards` (at minimum `["SMPTE"]`). Omit if the plugin is truly
  channel-position-agnostic.
- Never hard-code channel indices. Use `ProcessContext.channel_order` (list of
  `SPK.*` IDs) to locate channels dynamically — safe for both SMPTE and Film
  ordering.
- `ui_layout` is a relative path inside the plugin directory.
- `config_schema` is a JSON Schema object (Draft 2020-12 compatible).

## 2.1 Canonical stage graph for plugin authors

Use the same stage names the architecture docs use and design the plugin around
that boundary:

- Stage 1, input normalization/alignment: core-only technical canonicalization.
- Stage 2, analysis/metering: detector plugins only, advisory-only.
- Stage 3, scene inference: resolver/scene logic only, advisory-only.
- Stage 4, pre-render corrective pass: renderer plugins may apply bounded
  corrective DSP.
- Stage 5, render pass: renderer plugins may create target-layout audio.
- Stage 6, post-render QA: advisory-only measurement/gates.
- Stage 7, export pass: core-owned finalization for format/quantization/dither.

If your plugin mutates audio, it belongs in stage 4 or 5. If it only emits
measurements, intent, warnings, or confidence, it belongs in stage 2, 3, or 6.

Hard rules:

- Detectors and resolvers must not mutate audio.
- Renderer plugins must not silently dither, quantize, or noise-shape inside
  their own private output path before the core export-finalization contract.
- Any audible change must be explainable as either bounded low-risk behavior or
  an approved render action.

## 3. Config schema and UI hints checklist

- Every GUI control parameter is declared under `config_schema.properties`.
- Every GUI control parameter has a valid `x_mmo_ui` block:
  - `widget` is one of `knob`, `fader`, `toggle`, `selector`, `xy`, `meter`,
    `graph`.
  - Use `units` / `step` / `min` / `max` where relevant.
- Keep parameter names stable; layout `param_ref` resolution depends on these
  names.

## 4. UI layout checklist

- Layout validates against `schemas/ui_layout.schema.json`.
- Widgets fit the 12-column grid and avoid overlap.
- Each widget has `widget_id`, `col_span`, `row_span`, and `param_ref`.
- Layout widget `param_ref` values resolve to config parameters.

## 5. Validation checklist (must pass in CI)

Run both commands and confirm deterministic output across repeated runs:

```powershell
python -m mmo plugins show --include-ui-hints --include-ui-layout-snapshot
python -m mmo plugins ui-lint
```

With external plugins:

```powershell
python -m mmo plugins list --plugins plugins --plugin-dir ~/.mmo/plugins
python -m mmo render --report report.json --plugins plugins `
  --plugin-dir ~/.mmo/plugins --out-manifest render_manifest.json
```

Use `python -m mmo plugins show PLUGIN.RENDERER.EXAMPLE_GAIN_V0 ...` to target a
specific plugin.

Expected outcomes:

- `plugins show` reports:
  - `config_schema.present: True`
  - `ui_layout.present: True`
  - `ui_layout_snapshot.violations_count: 0`
  - `ui_hints.present: True`
- `plugins ui-lint` exits cleanly with no errors for the plugin.

See [docs/16-audio-quality-mandates.md](./16-audio-quality-mandates.md) for
digital-first DSP policy, truth-contract guidance, and measurable-claim
examples.
