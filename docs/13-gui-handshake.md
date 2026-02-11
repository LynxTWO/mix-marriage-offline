# Minimal GUI Handshake (Open -> Edit -> Run Render-Many)

This document defines the smallest real GUI loop using existing MMO contracts and CLI entry points.

The loop is:

1. Open a project file.
2. Load a UI bundle.
3. Surface scene metadata when available.
4. Edit scene intent and target selection.
5. Execute render-many via `render_plan -> variants`.
6. Present results and launch compare flows.

## 0) Contract Artifacts Used

- Project: `.mmo_project.json` (`schemas/project.schema.json`)
- UI bundle: `ui_bundle.json` (`schemas/ui_bundle.schema.json`)
- Scene: `scene.json` (`schemas/scene.schema.json`)
- Render plan: `render_plan.json` (`schemas/render_plan.schema.json`)
- Variant plan/result: `variant_plan.json`, `variant_result.json`
- Results: `deliverables_index.json`, `listen_pack.json`, `render_manifest.json`
- Compare output: `compare_report.json`

## 1) Open `.mmo_project.json`

Load the project payload and show:

- `stems_dir`
- `last_run` (mode + pointers)
- profile/preset defaults from `run_config_defaults.profile_id` and `run_config_defaults.preset_id`

CLI helper:

```bash
mmo project show --project path/to/song.mmo_project.json --format json
```

Notes:

- `last_run` is optional but, when present, is the primary pointer map for reopening prior results.
- `run_config_defaults` is optional; use it as the default profile/preset source for GUI controls.

## 2) Load `ui_bundle` (dashboard + presets + render_targets)

Build/load `ui_bundle.json` and bind:

- Dashboard: `dashboard`
- Preset-facing data: `dashboard.preset_recommendations` (and any profile/preset info in `report.run_config`)
- Targets: `render_targets.targets`

CLI builder:

```bash
mmo bundle --report out/report.json --project path/to/song.mmo_project.json --scene out/scene.json --render-plan out/render_plan.json --deliverables-index out/deliverables_index.json --listen-pack out/listen_pack.json --render-manifest out/render_manifest.json --out out/ui_bundle.json
```

Notes:

- `--scene`, `--render-plan`, `--deliverables-index`, and `--listen-pack` are optional pointers, but should be provided when available.
- For variant runs, render manifests are per-variant (see step 6).

## 3) If `scene.json` exists, show `scene_meta`

When `scene.json` exists and was passed to `mmo bundle`, the bundle includes:

- `scene_meta.locks_used`
- `scene_meta.intent_param_defs`
- `scene_meta.scene_templates` (if template registry entries exist)

This is the minimal contract for a scene-aware inspector.

## 4) Edit Loop

Edit operations map directly to existing CLI commands:

Apply template (if implemented):

```bash
mmo scene template apply TEMPLATE.SCENE.* --scene out/scene.json --out out/scene.json
```

For starter intent packs and safe apply semantics, see [14-scene-templates.md](14-scene-templates.md).

Add/remove locks:

```bash
mmo scene locks add --scene out/scene.json --scope scene --lock LOCK.* --out out/scene.json
mmo scene locks remove --scene out/scene.json --scope scene --lock LOCK.* --out out/scene.json
```

Set intent params:

```bash
mmo scene intent set --scene out/scene.json --scope scene --key width --value 0.7 --out out/scene.json
```

Choose render-many targets:

```bash
mmo targets list --format json
mmo targets show TARGET.STEREO.2_0 --format json
```

For deterministic target selection and recommendation wiring, see [15-target-selection.md](15-target-selection.md).

Persist selected target IDs in GUI state, then pass them as CSV in execution (step 5).

## 5) Execute

### 5a) Build `render_plan` when missing

```bash
mmo render-plan build --scene out/scene.json --targets TARGET.STEREO.2_0,TARGET.SURROUND.5_1 --out out/render_plan.json --context render
```

### 5b) Run `render-plan to-variants --run`

```bash
mmo render-plan to-variants --render-plan out/render_plan.json --scene out/scene.json --out out/variant_plan.json --out-dir out --run --listen-pack --deliverables-index
```

### 5c) Update project `last_run` pointers

After a successful run, update the opened project file to point at generated artifacts:

- `last_run.mode = "variants"`
- `last_run.out_dir`
- `last_run.variant_plan_path`
- `last_run.variant_result_path`
- `last_run.deliverables_index_path` (if written)
- `last_run.listen_pack_path` (if written)

Pointer key names must stay aligned with `schemas/project.schema.json`.

## 6) Results + Compare Entry Points

Show:

- `deliverables_index.json` (catalog of deliverables/artifacts)
- `listen_pack.json` (audition ordering and variant notes)
- render manifests

Render-manifest lookup:

- Variants: `variant_result.results[*].render_manifest_path`
- Also available in `deliverables_index.entries[*].artifacts.render_manifest` when present

Compare entry points:

- Any two reports:

```bash
mmo compare --a path/to/A/report.json --b path/to/B/report.json --out out/compare_report.json
```

- Directory form is also valid (`--a` / `--b` may point to folders containing `report.json`).
- Common GUI wiring:
  - Variant vs variant (from `variant_result.results[*].report_path`)
  - Current run vs last run (from project `last_run` pointers)
