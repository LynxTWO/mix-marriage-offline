# Scene and Render Contract Overview

This document defines the minimum scene/render contract for MMO's mix-once, render-many architecture.

## A) Minimal viable scene model (MVP)

A scene contains layout-agnostic intent, not fixed speaker routing.

### Objects (stems)

Each object includes:

- Position/width/depth hints
  - position hint (for example azimuth, optional elevation)
  - width hint
  - depth hint (directness/distance proxy)
- Confidence
- Locks (for example, do not move, preserve dynamics, preserve tone)

### Bed/field hints

- Diffuse distribution hints for surround/height style placement
- Hints are advisory, not forced channel assignment

### Out of scope for MVP

- No ML instrument detection is required
- No requirement to infer full object metadata from stereo-only content
- No automatic "creative intent generation" beyond explicit user intent plus bounded inference

## B) Render target contract

A render target must define:

- Canonical channel ordering
- Speaker positions when required by processing or export format
- Downmix policy references (stable IDs)
- Safety limits with context-based thresholds (`suggest`, `auto_apply`, `render`)

Render contracts must rely on canonical ontology layout definitions to avoid channel-order drift.

## B.1) Dual channel-ordering standard support

MMO supports two channel-ordering standards for all surround and immersive layouts.
Every render contract records which standard was requested.

### SMPTE / ITU-R (default)

The ordering baked into WAV, FLAC, WavPack, FFmpeg, and most DAW exports.
This is the MMO default for all file I/O.

- 5.1: **L R C LFE Ls Rs** (LFE at index 3)
- 7.1.4: L R C LFE Ls Rs Lrs Rrs TFL TFR TRL TRR

### Film / Cinema / Pro Tools

The ordering used in most professional mixing rooms and cinema dubbing stages.

- 5.1: **L C R Ls Rs LFE** (LFE at last position)
- 7.1.4: L C R Ls Rs Lrs Rrs LFE TFL TFR TRL TRR

### How to request Film ordering

CLI:
```
mmo safe-render --report report.json --layout-standard FILM ...
```

Python (render contract):
```python
from mmo.core.render_contract import build_render_contract
contract = build_render_contract("TARGET.SURROUND.5_1", "LAYOUT.5_1", layout_standard="FILM")
```

Python (channel query and reorder):
```python
from mmo.core.layout_negotiation import get_channel_order, reorder_channels
film_order = get_channel_order("LAYOUT.5_1", "FILM")
smpte_order = get_channel_order("LAYOUT.5_1", "SMPTE")
film_data = reorder_channels(smpte_data, smpte_order, film_order)
```

### Explainability

Every render job note and receipt includes the active standard:
`"using SMPTE channel order (SMPTE/ITU-R default)"` or
`"using FILM channel order (Film/Cinema/Pro Tools)"`.

### Dual-LFE export contract (x.2 layouts)

For layouts with two LFE channels (`SPK.LFE`, `SPK.LFE2`), MMO export contracts
must remain explicit even when container metadata is lossy:

- Render reports always carry canonical SPK channel order (`channel_order`) and
  channel count from the resolved layout contract.
- Recall-sheet context includes the same channel-order contract text.
- WAV export uses a conservative `WAVEFORMATEXTENSIBLE` strategy:
  direct-out style channel mask (`mask=0`) to avoid false single-LFE semantics.
- If FFmpeg is used and supports `LFE2`, MMO passes explicit layout strings
  (`FL+FR+FC+LFE+LFE2+...`) instead of relying on implicit defaults.
- Reports include warnings + validation instructions when external players/DAWs
  may collapse or relabel `LFE2`.

### run_config override

```json
{ "schema_version": "0.1.0", "render": { "layout_standard": "FILM" } }
```

## C) QA and gates expectations

Renderers must:

- Respect gate outcomes for the target context (`render` vs `auto_apply`)
- Emit artifacts with deterministic metadata (no wall-clock creation timestamps)
- Provide clear "why blocked" explanations with stable IDs

High-level gate/backoff loop:

1. Run render attempt with current settings.
2. Evaluate similarity and safety gates (including downmix and correlation risk).
3. If gates fail and an allowed backoff exists, apply conservative backoff and re-render.
4. Stop after a deterministic maximum attempt count; do not loop endlessly.
5. Emit a deterministic attempt log describing what was tried and why the final state passed or blocked.

When similarity gates fail, renderer must back off or stop. When correlation risk is high, renderer must reduce risk conservatively or stop. In both cases, behavior must be deterministic and explainable.

## D) Position stereo properly

- Stereo is one render target among many.
- When scene plus intent plus layout contracts exist, they are the source of truth.
- Stereo assets can inform inference, but must not override explicit scene locks or user intent.

## Related docs

- [PROJECT_INSTRUCTIONS.md](PROJECT_INSTRUCTIONS.md)
- [09-product-vision.md](09-product-vision.md)
- [11-gui-vision.md](11-gui-vision.md)
