# Audio Quality + Digital-First DSP Mandates

MMO is an offline deterministic system. Plugin DSP must be explicit, measurable,
and compatible with objective gates.

## Why digital-first

- Digital-native processing is repeatable and testable across platforms.
- Information-preserving transforms are the default because they reduce
  regression risk.
- Any coloration must be intentional, declared, and bounded by measurable
  outcomes.

## Truth contract (plugin-level)

A plugin truth contract is the measurable promise the plugin makes about what it
changes and what it does not change.

Manifest sections keep different responsibilities:

- `capabilities`
  - runtime and host execution contract
- `declares`
  - semantic purpose and ontology relationships
- `behavior_contract`
  - bounded audible-change promise

Do not overload `capabilities` with semantic purpose or `declares` with
loudness/peak bounds.

For renderer plugins, the contract is declared in:

- `capabilities.deterministic_seed_policy`
- `capabilities.dsp_traits` (including `tier`, `linearity`, and anti-aliasing
  intent)
- `capabilities.dsp_traits.measurable_claims`

Plugins must never bypass objective core gates. If gates fail, plugin behavior
must respect gate feedback and conservative backoff/stop decisions.

## Writing measurable claims

Each claim should be machine-checkable and auditable:

- `metric_id`: metric to evaluate (for example peak, loudness delta, dynamic
  range).
- `expected_direction`:
  - `up` means metric should increase.
  - `down` means metric should decrease.
  - `within` means metric must stay inside a bounded threshold.
- `threshold` (optional): numeric tolerance/target bound.
- `note` (optional): short plain-language context for reviewers.

Guidelines:

- Prefer objective meter IDs used in QA/report flows.
- Keep thresholds conservative and stable across repeated renders.
- Declare claims for both intended change and collateral safety bounds.

## Canonical stage ownership

The stage graph matters as much as the plugin math:

- Stages 2, 3, and 6 are advisory-only and must not modify audio.
- Stages 4 and 5 are the only stages where plugin DSP may make audible changes.
- Stages 1 and 7 are technical boundary stages; they may change representation
  for correctness or delivery, but not hide creative decisions.

This is why export finalization is core-owned. Dither, quantization, clamp
behavior, and final receipt emission are part of the public contract, not an
undocumented renderer-specific side effect.

## Export finalization mandate

For v1, the deterministic export-finalization contract is deliberately narrow:

- supported policies are `none`, `tpdf`, and `tpdf_hp`
- 16-bit PCM defaults to `tpdf`
- 24-bit and 32-bit integer PCM default to `none`
- true noise-shaped export policies are out of v1 unless the schemas and code
  are extended explicitly

`tpdf_hp` is allowed because it is a disclosed high-pass TPDF variant already
modeled in `export_finalize.py` and the manifest/report schemas. It should not
be described as general-purpose psychoacoustic noise shaping.

Plugins may declare `adds_noise` in their DSP traits when that is part of the
creative or corrective algorithm, but that is separate from export finalization.
No plugin may silently dither or quantize the final delivery outside the core
receipt-bearing export boundary.

`capabilities.dsp_traits` and `behavior_contract` serve different purposes:

- `dsp_traits`
  - what kind of DSP the plugin performs and what measurable claims it makes
- `behavior_contract`
  - how tightly the plugin promises to preserve loudness, peak, phase, or image

`max_channels: 32` in the examples below means session compatibility. The host
still uses topology fields such as `channel_mode`, `supported_group_sizes`, and
`supported_link_groups` to decide what invocation shape is lawful.

Corrective `auto_apply` or render-capable plugins default to conservative
`0.1 LUFS` / `0.1 dBTP` bounds unless they declare looser values explicitly
with rationale.

## Examples

Linear, information-preserving renderer:

```yaml
capabilities:
  max_channels: 32
  channel_mode: "true_multichannel"
  deterministic_seed_policy: "none"
  dsp_traits:
    tier: "information_preserving"
    linearity: "linear"
    phase_behavior: "linear_phase"
    adds_noise: false
    introduces_harmonics: false
    anti_aliasing: "na"
    measurable_claims:
      - metric_id: "METER.TRUE_PEAK_DBTP"
        expected_direction: "within"
        threshold: 0.2
behavior_contract:
  loudness_behavior: "preserve"
  max_integrated_lufs_delta: 0.1
  peak_behavior: "bounded"
  max_true_peak_delta_db: 0.1
  gain_compensation: "required"
```

Controlled nonlinear renderer:

```yaml
capabilities:
  max_channels: 32
  channel_mode: "linked_group"
  deterministic_seed_policy: "none"
  dsp_traits:
    tier: "controlled_nonlinear"
    linearity: "nonlinear"
    phase_behavior: "mixed"
    adds_noise: false
    introduces_harmonics: true
    anti_aliasing: "oversampling"
    oversampling_factor: 2
    measurable_claims:
      - metric_id: "METER.DYNAMIC_RANGE_DB"
        expected_direction: "down"
      - metric_id: "METER.TRUE_PEAK_DBTP"
        expected_direction: "within"
        threshold: 1.0
behavior_contract:
  loudness_behavior: "bounded"
  max_integrated_lufs_delta: 0.5
  peak_behavior: "bounded"
  max_true_peak_delta_db: 0.5
  rationale: "This nonlinear renderer is intentionally looser than the default
    corrective bounds."
```
