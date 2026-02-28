# Audio Quality + Digital-First DSP Mandates

MMO is an offline deterministic system. Plugin DSP must be explicit, measurable,
and compatible with objective gates.

## Why digital-first

- Digital-native processing is repeatable and testable across platforms.
- Information-preserving transforms are the default because they reduce regression risk.
- Any coloration must be intentional, declared, and bounded by measurable outcomes.

## Truth contract (plugin-level)

A plugin truth contract is the measurable promise the plugin makes about what it
changes and what it does not change.

For renderer plugins, the contract is declared in:

- `capabilities.deterministic_seed_policy`
- `capabilities.dsp_traits` (including `tier`, `linearity`, and anti-aliasing intent)
- `capabilities.dsp_traits.measurable_claims`

Plugins must never bypass objective core gates. If gates fail, plugin behavior must
respect gate feedback and conservative backoff/stop decisions.

## Writing measurable claims

Each claim should be machine-checkable and auditable:

- `metric_id`: metric to evaluate (for example peak, loudness delta, dynamic range).
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

## Examples

Linear, information-preserving renderer:

```yaml
capabilities:
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
```

Controlled nonlinear renderer:

```yaml
capabilities:
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
```
