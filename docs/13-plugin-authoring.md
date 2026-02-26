# Plugin Authoring: Minimum Viable Package

This checklist defines the minimum plugin package needed for GUI-visible metadata.
Use it when creating a new plugin under `plugins/`.

## 1. Required package files

- `*.plugin.yaml` manifest (or `plugin.yaml`) with valid `plugin_id`, `plugin_type`,
  `version`, and `entrypoint`.
- `ui/layout.json` referenced by `ui_layout` in the manifest.
- `config_schema` object in the manifest with parameter `properties`.
- `x_mmo_ui` blocks on all parameters referenced by the layout.

Example starter pack:

- `plugins/examples/gain_v0/gain_v0.plugin.yaml`
- `plugins/examples/gain_v0/ui/layout.json`

## 1.1 External plugin roots

MMO now loads plugins from two roots:

- Primary root: `--plugins` (default: `plugins/` in repo mode).
- External root: `~/.mmo/plugins/` by default, or `--plugin-dir <path>` to override.

External plugin manifests are automatically validated (schema + ontology semantics)
before registration. Duplicate `plugin_id` values across roots are rejected.

## 2. Manifest checklist

- `plugin_id` matches schema pattern for the plugin type
  (for renderer: `PLUGIN.RENDERER.*`).
- `entrypoint` imports successfully.
- `capabilities` uses supported fields (`max_channels`, `channel_mode`, `link_groups`,
  `latency`, `deterministic_seed_policy`, `bed_only`, `supported_standards`,
  `preferred_standard`, `supported_layout_ids`, `supported_contexts`, `scene`, `notes`).
- If `channel_mode` is `linked_group` or `true_multichannel`, declare `supported_standards`
  (at minimum `["SMPTE"]`). Omit if the plugin is truly channel-position-agnostic.
- Never hard-code channel indices. Use `ProcessContext.channel_order` (list of `SPK.*` IDs)
  to locate channels dynamically — safe for both SMPTE and Film ordering.
- `ui_layout` is a relative path inside the plugin directory.
- `config_schema` is a JSON Schema object (Draft 2020-12 compatible).

## 3. Config schema and UI hints checklist

- Every GUI control parameter is declared under `config_schema.properties`.
- Every GUI control parameter has a valid `x_mmo_ui` block:
  - `widget` is one of `knob`, `fader`, `toggle`, `selector`, `xy`, `meter`, `graph`.
  - Use `units` / `step` / `min` / `max` where relevant.
- Keep parameter names stable; layout `param_ref` resolution depends on these names.

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
python -m mmo render --report report.json --plugins plugins --plugin-dir ~/.mmo/plugins --out-manifest render_manifest.json
```

Use `python -m mmo plugins show PLUGIN.RENDERER.EXAMPLE_GAIN_V0 ...` to target a specific plugin.

Expected outcomes:

- `plugins show` reports:
  - `config_schema.present: True`
  - `ui_layout.present: True`
  - `ui_layout_snapshot.violations_count: 0`
  - `ui_hints.present: True`
- `plugins ui-lint` exits cleanly with no errors for the plugin.
