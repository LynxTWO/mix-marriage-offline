# Plugin Authoring Starter Pack

Use this doc when you want to ship a first MMO plugin quickly and correctly.
The copyable examples live under `examples/plugin_authoring/`.

## 1. Start from the closest example

- `examples/plugin_authoring/starter_pack/renderers/starter_per_channel_gain.plugin.yaml`
  with `examples/plugin_authoring/starter_pack/starter_per_channel_gain.py`
  - best first copy for semantic-speaker, one-channel-at-a-time logic
- `examples/plugin_authoring/starter_pack/renderers/starter_linked_group_bed.plugin.yaml`
  with `examples/plugin_authoring/starter_pack/starter_linked_group_bed.py`
  - best first copy for linked front/surround/height work plus bed-only safety
- `examples/plugin_authoring/starter_pack/renderers/starter_true_multichannel_checksum.plugin.yaml`
  with `examples/plugin_authoring/starter_pack/starter_true_multichannel_checksum.py`
  - best first copy for full-buffer DSP with seeded determinism and
    layout-specific safety

Also included:

- `examples/plugin_authoring/starter_manifest.template.yaml`
  - commented manifest template
- `examples/plugin_authoring/invalid/layout_specific_without_layout.plugin.yaml`
  - intentional mistake showing what MMO rejects

## 2. Folder structure

MMO scans a plugin root for `*.plugin.yaml` manifests. A minimal starter root
can be this small:

```text
my_plugin_root/
  my_renderer.py
  renderers/
    my_renderer.plugin.yaml
```

For repo-local examples, see:

```text
examples/plugin_authoring/
  README.md
  starter_manifest.template.yaml
  invalid/
    layout_specific_without_layout.plugin.yaml
  starter_pack/
    starter_per_channel_gain.py
    starter_linked_group_bed.py
    starter_true_multichannel_checksum.py
    renderers/
      starter_per_channel_gain.plugin.yaml
      starter_linked_group_bed.plugin.yaml
      starter_true_multichannel_checksum.plugin.yaml
```

## 3. Manifest anatomy

Start from `examples/plugin_authoring/starter_manifest.template.yaml`.

Fields you should set deliberately:

- `plugin_id`
  - stable `PLUGIN.RENDERER.*`, `PLUGIN.DETECTOR.*`, or `PLUGIN.RESOLVER.*`
- `entrypoint`
  - `module:Class` inside the plugin root
- `capabilities.channel_mode`
  - `per_channel`, `linked_group`, or `true_multichannel`
- `capabilities.max_channels`
  - maximum session width the plugin may participate in safely
  - for built-ins and examples this is `32`; topology limits belong elsewhere
- `capabilities.supported_group_sizes`
  - lawful group sizes for one invocation
- `capabilities.supported_link_groups`
  - only for `linked_group`
- `capabilities.latency`
  - `zero`, `fixed`, or `dynamic`
- `capabilities.deterministic_seed_policy`
  - `none`, `seed_required`, or `seed_optional`
- `capabilities.scene_scope`
  - `bed_only` or `object_capable`
- `capabilities.layout_safety`
  - `layout_agnostic` or `layout_specific`
- `capabilities.supported_layout_ids` or `capabilities.scene.supported_target_ids`
  - required when `layout_safety` is `layout_specific`
- `declares`
  - semantic purpose metadata such as emitted issues, consumed issues,
    suggested actions, related features, and target scopes
- `behavior_contract`
  - audible bounds for plugins that render or auto-apply audio changes
- `capabilities.dsp_traits`
  - the measurable DSP truth contract; keep it distinct from audible bounds

Common safety mistake:

- `layout_safety: "layout_specific"` without `supported_layout_ids` or
  `scene.supported_target_ids`
  - MMO rejects this with `ISSUE.SEMANTICS.LAYOUT_SPECIFIC_NO_LAYOUT`

## 4. Execution model overview

MMO supports three channel execution modes for audio-mutating plugins:

- `per_channel`
  - the host calls `process_channel(...)` once per semantic speaker
  - best for fixed gain/trim or speaker-local correction
- `linked_group`
  - the host calls `process_linked_group(...)` for a declared semantic group
  - best for front, surround, or height moves that must stay matched
- `true_multichannel`
  - the host calls `process_true_multichannel(...)` once with the full buffer
  - best for processing that needs all channels at once

In every mode:

- input is `AudioBufferF64`
- output must be `AudioBufferF64`
- routing should use `process_ctx.channel_order` and `SPK.*` IDs, never fixed
  slot numbers
- `max_channels: 32` means session compatibility, not permission to process all
  32 channels as one block unless `channel_mode` and `supported_group_sizes`
  say that is lawful

## 5. Determinism do and don't

Do:

- derive any approved randomness from `process_ctx.seed`
- return stable evidence dictionaries with sorted or deterministic values
- keep behavior independent of wall clock and thread timing

Don't:

- call global `random.*`
- call `numpy.random.*` without an explicit seed
- call `time.time()`, `time.perf_counter()`, or similar APIs
- spawn threads or executors inside plugin execution

The runtime enforces these rules at the plugin boundary.

## 6. Receipts and evidence expectations

Two surfaces matter:

- mode execution evidence
  - `process_channel`, `process_linked_group`, and `process_true_multichannel`
    may return `(AudioBufferF64, evidence_dict)`
  - keep evidence short, deterministic, and directly tied to what changed
- renderer manifest receipts
  - `render(...)` returns a `RenderManifest`
  - the host may further restrict or bypass the plugin based on
    `scene_scope` and `layout_safety`, then records the why in `skipped[]` and
    `notes`

The starter pack examples intentionally demonstrate both:

- the linked-group example is `bed_only`, so object recommendations are
  restricted with an explainable skipped row
- the true-multichannel example is `layout_specific`, so unsupported layouts
  are bypassed with an explainable skipped row
- the per-channel and linked-group examples still declare `max_channels: 32`
  because they can participate in wider sessions without pretending to be
  full-field multichannel processors

## 7. Quick test workflow

Validate the examples and the authoring path with:

```sh
python -m pytest -q tests/test_plugin_modes_golden.py
python -m pytest -q tests/test_plugin_authoring_examples.py
python -m pytest -q tests/test_plugin_registry.py
python -m pytest -q tests/test_renderer_runner.py
python -m mmo plugins validate --plugins examples/plugin_authoring/starter_pack
```

The last command now validates entrypoints relative to the plugin root, so it
works for repo-local examples and external plugin directories the same way.

## 8. GUI-visible extras

If you also want MMO's plugin UI tooling to understand your plugin, add:

- `config_schema`
- `ui_layout`
- `x_mmo_ui` hints on user-facing parameters

The GUI-oriented examples under `plugins/examples/` are still the right
reference for that layer. The starter pack in `examples/plugin_authoring/`
focuses on execution mode, determinism, and safety semantics first.
