# Target Selection

This guide explains how MMO target selection works in CLI and UI flows.

## Token Types

MMO accepts interchangeable target tokens:

- `TARGET.*` IDs from `ontology/render_targets.yaml` (delivery-target entries).
- `LAYOUT.*` IDs from `ontology/layouts.yaml` (speaker-layout entries).
- Musician-friendly shorthands: `stereo`, `2.0`, `2.1`, `3.0`, `3.1`, `4.0`,
  `4.1`, `quad`, `lcr`, `5.1`, `7.1`, `7.1.4`, `binaural`.

Examples:

- `TARGET.STEREO.2_0`
- `TARGET.STEREO.2_1`
- `TARGET.FRONT.3_0`
- `TARGET.FRONT.3_1`
- `TARGET.SURROUND.4_0`
- `TARGET.SURROUND.4_1`
- `LAYOUT.5_1`
- `stereo`
- `quad`
- `7.1.4`

## Deterministic Resolution Order

MMO resolves tokens with `mmo.core.target_tokens.resolve_target_token` in this
order:

1. `TARGET.*` ID
2. `LAYOUT.*` ID
3. Canonical shorthands (`stereo`, `2.0`, `2.1`, `3.0`, `3.1`, `4.0`, `4.1`,
   `quad`, `lcr`, `5.1`, `7.1`, `7.1.4`, `binaural`)
4. Render-target alias matching, then layout-alias matching
5. Ambiguous matches fail with a deterministic error listing sorted candidates

`ResolvedTarget` includes:

- `target_id` (optional; `None` when a token resolves to layout-only)
- `layout_id`
- `display_label`
- `source` (`target_id`, `layout_id`, `shorthand`, `alias`)

Notes:

- Commands that require concrete render target IDs resolve layout tokens to
  target IDs only when the mapping is unambiguous.
- If a layout maps to multiple targets, MMO errors with sorted candidates.
- `binaural`, `LAYOUT.BINAURAL`, and `TARGET.HEADPHONES.BINAURAL` resolve to the
  first-class headphone deliverable target.

## Binaural Deliverable Path

MMO treats binaural as a deterministic two-stage render:

1. Render an internal speaker-layout source first:
   - `LAYOUT.7_1_4` when scene/session signals mention heights.
   - `LAYOUT.5_1` when the scene is surround-ish but not height-driven.
   - `LAYOUT.2_0` fallback otherwise.
2. Virtualize that source render to `LAYOUT.BINAURAL` using conservative
   ILD/ITD + RMS gating (`binaural_preview_v0`).

Safe-render receipts and render contract/report notes explicitly call out that
binaural output is virtualization and include the chosen source layout ID.

## Practical Guidance

- Use `stereo` for quick musician flow.
- Use `TARGET.*` for explicit engineering control.
- Use `LAYOUT.*` when you care about speaker layout and want target selection
  inferred.
- Use `2.1`, `3.0`/`lcr`, `3.1`, `4.0`/`quad`, and `4.1` for first-class
  front/quad variants.
- `safe-render --render-many` defaults remain `stereo,5.1,7.1.4`; add `binaural`
  explicitly in `--render-many-targets` when a headphone deliverable is
  required. Add `2.1`, `3.0`, `3.1`, `4.0`, or `4.1` explicitly when those
  deliverables are required.

## `mmo targets recommend` Usage

`mmo targets recommend` always includes stereo as rank 1 baseline, then adds
conservative surround candidates from report/scene signals.

Inputs:

- `--report`: report JSON path, or directory containing `report.json`
- `--scene`: optional scene JSON path
- `--max`: max rows returned (default `3`)

If `--report` points to a directory and `--scene` is omitted, MMO auto-reads
`scene.json` from that same directory when present.

Example JSON output:

```bash
mmo targets recommend --report out --format json
```

```json
[
  {
    "confidence": 1.0,
    "rank": 1,
    "reasons": ["Baseline stereo reality check."],
    "target_id": "TARGET.STEREO.2_0"
  },
  {
    "confidence": 0.92,
    "rank": 2,
    "reasons": ["Routing plan targets LAYOUT.5_1"],
    "target_id": "TARGET.SURROUND.5_1"
  },
  {
    "confidence": 0.84,
    "rank": 3,
    "reasons": ["Run config downmix targets LAYOUT.7_1"],
    "target_id": "TARGET.SURROUND.7_1"
  }
]
```

Example text output:

```bash
mmo targets recommend --report out --format text
```

```text
Recommended targets:
  1) TARGET.STEREO.2_0 (conf=1.00)
     - Baseline stereo reality check.
  2) TARGET.SURROUND.5_1 (conf=0.92)
     - Routing plan targets LAYOUT.5_1
  3) TARGET.SURROUND.7_1 (conf=0.84)
     - Run config downmix targets LAYOUT.7_1
```

## How UI Uses `ui_bundle.render_targets`

`build_ui_bundle(...)` exposes target data in `ui_bundle.render_targets`:

- `targets`: full catalog for picker UI (deterministically sorted by
  `target_id`).
- `highlighted_target_ids`: baseline stereo plus targets referenced by:
  - `report.routing_plan.target_layout_id`
  - `report.run_config.downmix.target_layout_id`
  - dashboard deliverable `target_layout_id` values
- `recommendations`: conservative ranked suggestions (`target_id`, `rank`,
  `confidence`, `reasons`).

Notes:

- Recommendations are emitted when a valid scene payload is available to the
  bundle builder.
- UI should treat recommendations as advisory defaults; explicit user selections
  remain authoritative.
