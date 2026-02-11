# Scene Templates

Scene templates are starter intent packs for scene editing flows. They are deterministic registry entries that apply fixed intent patches to scene/object/bed targets, with no ML inference and no randomness.

## What Templates Are

- Templates live in `ontology/scene_templates.yaml` and are validated by `schemas/scene_templates.schema.json`.
- Each template has stable `template_id`, `label`, `description`, and `patches`.
- Patches match a scope (`scene`, `object`, `bed`) and set intent fields like `position`, `width`, `depth`, `loudness_bias`, `diffuse`, and `confidence`.
- Templates are meant for fast, repeatable starting intent, then normal lock/intent editing can continue.

## Determinism Constraints

- Template IDs in the registry must be sorted; unsorted registries fail validation/load.
- Any `label_regex` in patch match rules must compile; invalid regex fails validation/load.
- Schema validation is strict (`additionalProperties: false`), so ad-hoc metadata (including timestamp fields) is rejected.
- Apply/preview behavior is deterministic: ordered template application, deterministic skip behavior, deterministic output ordering.

## Lock Semantics

- Hard locks are always respected during apply/preview.
- If scene-level intent includes a hard lock, scene-scope template patches are skipped.
- For object/bed patches, targets with hard locks (or scene-level hard locks) are skipped.
- Templates do not edit lock IDs; they do not add/remove items in `intent.locks`.

## Apply Semantics

- Default apply mode fills only missing intent fields.
- `--force` (or `--force-templates` in scene build flow) overwrites existing intent fields.
- Hard-lock behavior is unchanged in both modes: locked targets are still skipped.

## CLI Commands

List templates:

```bash
mmo scene template list
mmo scene template list --format json
```

Show one or more templates:

```bash
mmo scene template show TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER
mmo scene template show TEMPLATE.SCENE.LIVE.YOU_ARE_THERE TEMPLATE.SCENE.SURROUND.FRONT_STAGE_CLEAR_REAR_FIELD --format json
```

Apply one or more templates to a scene:

```bash
mmo scene template apply TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER --scene out/scene.json --out out/scene.json
mmo scene template apply TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER TEMPLATE.SCENE.LIVE.YOU_ARE_THERE --scene out/scene.json --out out/scene.json --force
```

Optional preview (when command is available in your build):

```bash
mmo scene template preview TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER --scene out/scene.json
mmo scene template preview TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER --scene out/scene.json --force --format json
```

Apply templates during scene build:

```bash
mmo scene build --report out/report.json --out out/scene.json --templates TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER
mmo scene build --report out/report.json --out out/scene.json --templates TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER,TEMPLATE.SCENE.LIVE.YOU_ARE_THERE --force-templates
```

Apply templates in render-many run flow:

```bash
mmo run --stems stems --out out --render-many --scene-templates TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER --targets TARGET.STEREO.2_0
```

Apply templates in project render-many flow:

```bash
mmo project run --project song.mmo_project.json --out out --render-many --scene-templates TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER --targets TARGET.STEREO.2_0
```

## Safe Usage Checklist

1. Start with `mmo scene template list` and `mmo scene template show ...` to confirm intent.
2. Prefer preview before write when available: `mmo scene template preview ...`.
3. Use default apply mode first; switch to `--force` only when you intentionally want overwrite behavior.
4. Keep hard locks in place for non-negotiable intent before applying templates.
5. Re-run your normal scene/render validation flow after template application.
