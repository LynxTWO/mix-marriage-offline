# fixtures/golden/

Cross-platform golden render fixtures for
`classify -> bus-plan -> scene -> safe-render`.

Each fixture keeps:

- deterministic synthetic stems under `stems/`
- checked-in scene + bus-plan snapshots under `expected/`
- invariant snapshots under `expected/expected_metrics.json`
- exact QA/gate snapshots under `expected/expected_gate_outcomes.json`

Fixtures:

- `golden_small_stereo`: `LAYOUT.2_0`
- `golden_small_surround`: `LAYOUT.5_1`, `LAYOUT.7_1`
- `golden_small_immersive`: `LAYOUT.7_1_4`, `LAYOUT.9_1_6`

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
