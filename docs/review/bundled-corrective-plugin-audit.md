<!-- markdownlint-disable-file MD013 -->

# Bundled Corrective Plugin Audit

This pass applies the next approved bundled-plugin comment batch after the
loader, market, and first-renderer notes.

## Scope

Reviewed and commented in this batch:

- `src/mmo/plugins/detectors/lfe_corrective_detector.py`
- `src/mmo/plugins/resolvers/lfe_corrective_resolver.py`

Proof checks for the selected boundaries:

- `tests/test_corrective_plugins.py`
- `tests/test_lfe_corrective_approval.py`
- `docs/review/bundled-plugin-review.md`
- `docs/review/remediation-backlog.md`

## What this batch clarified

### Detector output stays evidence-bound and LFE-scoped

`src/mmo/plugins/detectors/lfe_corrective_detector.py` now says the quiet rule
directly:

- the corrective detector only enters this path when the session already shows
  explicit LFE routing or the audit measurements already carry `EVID.LFE.*`
  evidence
- the detector carries the original file-path and channel-row evidence through
  every emitted issue
- one stem can raise more than one `ISSUE.LFE.*` finding, but the detector does
  not choose which corrective action should run

### Resolver emits approval-gated candidates, not silent fixes

`src/mmo/plugins/resolvers/lfe_corrective_resolver.py` now says the trust
boundary directly:

- explicit LFE routing only affects the recommendation notes and rollback text
- every emitted recommendation remains `requires_approval=True` with high
  impact and risk
- the resolver describes candidate filter parameters and rollback steps, but it
  does not apply filters or reroute content
- detector evidence is passed through unchanged so blocked or applied receipts
  still point back to the measured stem

## What remained unchanged

- LFE issue thresholds and emitted `ISSUE.LFE.*` IDs
- corrective filter payload choices for the three supported issue types
- approval-gated recommendation semantics
- safe-render QA rerun behavior after an approved corrective filter
- the explicit-LFE no-silent-reroute guarantee

## What still needs a later protected batch

This batch did not cover:

- the subjective-pack bypass in `src/mmo/dsp/plugins/registry.py` and
  `src/mmo/plugins/subjective/`
- checkout-example and offline market parity questions recorded in
  `docs/unknowns/bundled-plugin-review.md`

Those paths still need their own approval-aware trust-boundary work before the
bundled-plugin slice can move past `mapped`.
