# Plugin Authoring Starter Pack

Start here if you want to build a new MMO plugin without digging through the
whole repo.

## What is here

- `starter_pack/`: three tiny, real renderer examples that cover MMO's three
  execution modes.
- `starter_manifest.template.yaml`: a copyable manifest template with field
  notes.
- `invalid/`: one intentionally broken manifest that shows a common safety
  mistake and the error MMO should raise.

## Starter pack examples

- `starter_pack/renderers/starter_per_channel_gain.plugin.yaml`
  with `starter_pack/starter_per_channel_gain.py`
  - `channel_mode: per_channel`
  - `scene_scope: object_capable`
  - `layout_safety: layout_agnostic`
- `starter_pack/renderers/starter_linked_group_bed.plugin.yaml`
  with `starter_pack/starter_linked_group_bed.py`
  - `channel_mode: linked_group`
  - `scene_scope: bed_only`
  - `layout_safety: layout_agnostic`
- `starter_pack/renderers/starter_true_multichannel_checksum.plugin.yaml`
  with `starter_pack/starter_true_multichannel_checksum.py`
  - `channel_mode: true_multichannel`
  - `scene_scope: object_capable`
  - `layout_safety: layout_specific`

Each example does three things on purpose:

- accepts `AudioBufferF64` and returns `AudioBufferF64`
- emits deterministic evidence for tests and receipts
- declares the manifest safety contract the host needs for explainable
  restriction or bypass decisions
- keeps `render()` receipt-only so authors can learn the host contract before
  they add file output side effects

## Quick workflow

1. Copy the closest starter example into your plugin root.
2. Rename the Python class, module, and `plugin_id`.
3. Edit the manifest using `starter_manifest.template.yaml`.
4. Run:

```sh
python -m pytest -q tests/test_plugin_modes_golden.py
python -m pytest -q tests/test_plugin_authoring_examples.py
python -m mmo plugins validate --plugins examples/plugin_authoring/starter_pack
```

## Common mistake example

`invalid/layout_specific_without_layout.plugin.yaml` is intentionally wrong:
it declares `layout_safety: "layout_specific"` but forgets to declare
`supported_layout_ids` or `scene.supported_target_ids`. MMO should reject that
manifest with `ISSUE.SEMANTICS.LAYOUT_SPECIFIC_NO_LAYOUT`.
