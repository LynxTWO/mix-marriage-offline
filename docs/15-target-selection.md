# Target Selection

This guide explains how MMO target selection works in CLI and UI flows.

## What Targets Are

Render targets are canonical output layouts from `ontology/render_targets.yaml`.

- `TARGET.STEREO.2_0`: baseline stereo reality check and widest playback coverage.
- `TARGET.SURROUND.5_1`: surround bed with center + LFE + side channels.
- `TARGET.SURROUND.7_1`: surround with additional rear channels for deeper rear imaging.

Practical selection guidance:

- Choose stereo when you need universal playback and a translation baseline.
- Choose 5.1 when center anchoring and surround spread are part of delivery intent.
- Choose 7.1 when rear motion/depth cues matter and the playback context supports it.

## IDs, Aliases, and Deterministic Resolution

MMO accepts both canonical target IDs and friendly aliases (for example `Stereo (streaming)`).

Resolution is deterministic (`mmo.core.render_targets.resolve_render_target_id`):

1. Trim input token; reject empty input.
2. If token exactly matches a known `target_id`, use it.
3. Otherwise normalize alias comparison by removing whitespace and case-folding.
4. Match against target `aliases` using the same normalization.
5. If multiple matches exist, fail with a deterministic ambiguity error listing sorted IDs.
6. If no matches exist, fail with a deterministic unknown-token error listing sorted available targets.

## `mmo targets recommend` Usage

`mmo targets recommend` always includes stereo as rank 1 baseline, then adds conservative surround candidates from report/scene signals.

Inputs:

- `--report`: report JSON path, or directory containing `report.json`
- `--scene`: optional scene JSON path
- `--max`: max rows returned (default `3`)

If `--report` points to a directory and `--scene` is omitted, MMO auto-reads `scene.json` from that same directory when present.

Example JSON output:

```bash
mmo targets recommend --report out --format json
```

```json
[
  {
    "confidence": 1.0,
    "rank": 1,
    "reasons": [
      "Baseline stereo reality check."
    ],
    "target_id": "TARGET.STEREO.2_0"
  },
  {
    "confidence": 0.92,
    "rank": 2,
    "reasons": [
      "Routing plan targets LAYOUT.5_1"
    ],
    "target_id": "TARGET.SURROUND.5_1"
  },
  {
    "confidence": 0.84,
    "rank": 3,
    "reasons": [
      "Run config downmix targets LAYOUT.7_1"
    ],
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

- `targets`: full catalog for picker UI (deterministically sorted by `target_id`).
- `highlighted_target_ids`: baseline stereo plus targets referenced by:
  - `report.routing_plan.target_layout_id`
  - `report.run_config.downmix.target_layout_id`
  - dashboard deliverable `target_layout_id` values
- `recommendations`: conservative ranked suggestions (`target_id`, `rank`, `confidence`, `reasons`).

Notes:

- Recommendations are emitted when a valid scene payload is available to the bundle builder.
- UI should treat recommendations as advisory defaults; explicit user selections remain authoritative.
