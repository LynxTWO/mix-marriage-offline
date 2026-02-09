# MMO Scene and Render Contract Overview

This document describes the minimal “mix-once, render-many” contract for MMO. It is intended to be implementation-friendly and to keep future plugins safe across up to 32 channels.

## Design summary

The pipeline is split into three responsibilities:

1) **Scene (mix intent):** layout-agnostic representation of “what the mix is.”  
2) **DSP graph:** stem and bus processing (EQ, dynamics, saturation, etc).  
3) **Renderer:** converts the scene into a target layout (2.0, 5.1, 7.1.4, etc) and runs QA gates.

The scene is the source of truth. Stereo is one render target, not the master reference.

## Terminology

- **Object:** discrete content with a position/width intent (lead vocal, snare, lead synth, key FX hit).  
- **Bed/field:** diffuse, enveloping energy intended for surrounds/heights (rooms, tails, pads, audience).  
- **Render target:** a speaker layout definition plus channel order contract.  
- **Downmix contract:** explicit coefficients and policies for fold-down checks.

## Scene model (minimum viable)

### Scene header

- `scene_version`: semantic version  
- `sample_rate`  
- `timebase`: samples or seconds  
- `layout_agnostic`: always true  
- `seed`: deterministic seed for any stochastic processes

### Objects (list)

For each object:

- `id`, `role` (ontology ID), `source_ref` (stem/bus reference)  
- **Placement intent**
  - `azimuth_deg` (or normalized -1..+1 pan proxy)
  - `elevation_deg` (optional; usually 0 unless explicit)
  - `width` (0..1 or degrees)
  - `depth` (0..1, interpreted as directness vs distance proxy)
- `locks`: explicit user overrides that must not be changed automatically  
- `confidence`: 0..1 (inference confidence, not user confidence)
- `render_hints`: optional constraints (no heights, center-locked, no rears, etc)

### Bed/field (one or more beds)

Minimum representation (keep it simple at first):

- `bed_id`, `role`
- `content_ref`: bus/return reference
- `distribution_hints`: surround and height weighting, bandwidth limits, decorrelation policy
- `seed`: deterministic seed (can be derived from scene seed + bed_id)

The bed can start as “multi-return buses” (surround send, height send) and evolve later into an Ambisonic/HOA field without changing the contract.

### Routing intent

- `front_stage_bus`  
- `surround_bus`  
- `height_bus`  
- `lfe_send_bus` (creative LFE send, optional)  
- `fx_returns` (reverbs/delays with early/late tags)

## Stereo stem inference rules (advisory)

If the input stems already contain baked pan/width:

- Estimate azimuth primarily from **band-limited energy ratio** (avoid bass-heavy bins).  
- Estimate width from **mid/side energy ratio** and **inter-channel coherence**.  
- Apply temporal smoothing so pan does not chatter.  
- If confidence is low or content is strongly diffuse, classify as bed/field instead of object.

Depth is not literal front/back. Use depth proxies:
- direct-to-reverb ratio  
- transient clarity vs late energy  
- spectral distance cues

## Render contract (targets)

A render target includes:

- `layout_id` (ontology ID)  
- `channels`: canonical ordered list of semantic channel IDs  
- `speaker_positions`: azimuth/elevation per channel where relevant  
- `downmix_policy_id`: link to ontology/downmix policy  
- `limits`: max surround energy, max height energy, decorrelation policy, etc

### Channel order

Every target layout must have a single canonical channel order in the ontology. Do not rely on “whatever ffmpeg does” internally.

### LFE and “.2”

Content generally carries one LFE channel. If outputting two subs, treat it as playback/bass management unless explicitly targeting a format that requires dual-LFE program feeds.

## QA gates (minimum)

Renderer must produce a `render_report` including:

- downmix fold-down similarity score vs stereo reference (or stem-based reference mix)  
- correlation/phase-risk metrics per channel group  
- loudness and true-peak/headroom  
- “safety backoff” decisions (when confidence was low)

Required behavior:

- If downmix similarity fails: reduce surround/height contributions and re-render (bounded iterations).  
- If correlation risk is high: reduce decorrelation aggressiveness or re-route energy to bed.

## Plugin API expectations (scene-aware)

Every plugin must declare:

- `max_channels` (≥ 32 target)  
- `channel_mode`: per-channel vs linked-group vs true-multichannel  
- supported link groups (front/surround/height)  
- latency reporting and determinism usage  
- whether it requires speaker positions  
- whether it should run pre-render (object/stem domain) or in the bed/field domain

## Suggested next files

- `schemas/scene.json`  
- `schemas/render_request.json`  
- `schemas/render_report.json`  
- `ontology/layouts.yaml` and `ontology/downmix.yaml` expansions  
- fixtures to validate determinism and downmix similarity
