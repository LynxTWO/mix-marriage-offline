# 19. Stems Drafts (Preview-Only Scene + Routing Plan)

This guide describes the `stems draft` command, which generates preview-only
`scene.draft.json` and `routing_plan.draft.json` files from a classified `stems_map`.

## What are drafts?

Drafts are conservative starter payloads generated from your stem classifications.
They are **preview-only** and **never auto-discovered** by any workflow.
You must explicitly pass them as inputs to any command that consumes a scene or routing plan.

## Generating drafts

After you have a `stems_map.json` (from `stems classify` or `stems pipeline`):

```powershell
python -m mmo stems draft --stems-map stems_map.json --out-dir drafts/
```

This produces:

- `drafts/scene.draft.json` — a scene with one object per stem assignment
- `drafts/routing_plan.draft.json` — a routing plan with mono-to-stereo center-pan routes

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--stems-map` | (required) | Path to `stems_map.json` |
| `--out-dir` | (required) | Output directory for draft files |
| `--scene-out` | `scene.draft.json` | Output filename for the draft scene |
| `--routing-out` | `routing_plan.draft.json` | Output filename for the draft routing plan |
| `--stems-dir` | `/DRAFT/stems` | Absolute stems_dir for `scene.source` |
| `--format` | `text` | Output format: `json` or `text` |
| `--overwrite` | off | Allow overwriting existing output files |

## What is inside the drafts?

### Scene (`scene.draft.json`)

- **scene_id**: `SCENE.DRAFT.<hash>` — deterministic from sorted file IDs
- **source.created_from**: `"draft"`
- **objects**: One per stem assignment, sorted by `(rel_path, file_id)`
  - `channel_count`: 1 (conservative; real counts require file inspection)
  - `intent`: neutral position, zero width/depth, confidence from classifier
  - `notes`: includes `bus_group` and `role_id` for human review
- **beds**: Single master bed `BED.001` (diffuse=0.5, confidence=0.5)

### Routing plan (`routing_plan.draft.json`)

- **source_layout_id**: `LAYOUT.STEMS`
- **target_layout_id**: `LAYOUT.2_0` (stereo)
- **routes**: One per stem, mono source to stereo target, center-panned at 0 dB

## Using drafts explicitly

Drafts are never picked up automatically. To use them, pass them explicitly:

```powershell
python -m mmo analyze --scene drafts/scene.draft.json ...
```

Or use them as a starting point for manual editing before passing to any workflow.

## Safety

- Draft files use `*.draft.json` filenames to avoid confusion with production artifacts.
- No code in the repo auto-discovers scene or routing plan files by glob.
- All scene/routing paths must be passed explicitly by the user.
