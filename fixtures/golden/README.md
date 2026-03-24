# fixtures/golden/

Cross-platform golden render fixtures for
`classify -> bus-plan -> scene -> safe-render`.

Each fixture keeps:

- deterministic synthetic stems under `stems/`
- checked-in scene + bus-plan snapshots under `expected/`
- invariant snapshots under `expected/expected_metrics.json`
- exact QA/gate snapshots under `expected/expected_gate_outcomes.json`

Packaged smoke goldens keep:

- `render_manifest.json`, `safe_render_receipt.json`, and `render_qa.json`
- deterministic rendered WAVs under `render/`
- `expected_smoke_truth.json` snapshots for packaged desktop render-audit checks

Fixtures:

- `golden_small_stereo`: `LAYOUT.2_0`
- `golden_small_surround`: `LAYOUT.5_1`, `LAYOUT.7_1`
- `golden_small_immersive`: `LAYOUT.7_1_4`, `LAYOUT.9_1_6`
- `packaged_smoke_full_success`: valid master artifact triad
- `packaged_smoke_zero_decoded_failure`: decoded-stem failure with diagnostic artifact
- `packaged_smoke_silent_invalid`: silent invalid-master artifact triad
- `packaged_smoke_partial_multi_layout`: mixed success/failure across layouts
- `packaged_smoke_uniform_rate_44100`: uniform-rate preservation at 44.1 kHz

Regenerate stems:

```bash
PYTHONPATH=src .venv/bin/python fixtures/golden/generate_stems.py
```

Regenerate expected snapshots:

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
from tests.test_golden_fixtures import write_expected_snapshots
write_expected_snapshots()
PY
```
