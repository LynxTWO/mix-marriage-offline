# MMO User Guide

This guide covers the practical, repeatable MMO workflow for day-to-day use.

## 1. Install and verify

Install from source checkout:

```bash
pip install .
```

Optional extras:

```bash
pip install .[truth]
pip install .[pdf]
pip install .[gui]
```

Verify the CLI is available:

```bash
python -m mmo --help
```

## 2. First run (analyze stems)

Given a folder of aligned stems:

```bash
python -m mmo scan ./stems --out-report out/report.json
```

Then export a recall sheet:

```bash
python -m mmo report --report out/report.json --csv out/recall.csv
```

## 3. Mix-once render-many

Run a deterministic render-many pass from one report:

```bash
python -m mmo safe-render \
  --report out/report.json \
  --render-many \
  --render-many-targets stereo,5.1,7.1.4 \
  --out-dir out/deliverables
```

This keeps one analysis pass and writes per-target outputs using MMO channel
layout contracts.

## 4. Translation and downmix QA

Inspect available downmix paths:

```bash
python -m mmo downmix list --format json
```

Run downmix QA against a stereo reference:

```bash
python -m mmo downmix qa \
  --src out/deliverables/your_mix_5_1.wav \
  --ref refs/reference_stereo.wav \
  --source-layout LAYOUT.5_1 \
  --format json
```

## 5. Watch-folder batch mode

Auto-run deterministic batches when new stem sets land:

```bash
python -m mmo watch ./incoming_stems --out-dir out/watch_runs
```

Use this for label-style drops where you want unattended but bounded runs.

## 6. GUI workflow

Launch GUI:

```bash
python -m mmo.gui.main
```

Recommended GUI flow:

1. Load stem folder.
2. Pick render target and layout standard.
3. Review detected issues with explainability fields (`what/why/where/confidence`).
4. Run safe render.
5. Use headphone preview when you want a deterministic binaural check.

## 7. Plugin marketplace (offline index)

List bundled marketplace entries:

```bash
python -m mmo plugin list --format json
```

Refresh local snapshot:

```bash
python -m mmo plugin update
```

## 8. Benchmarking (v1.1 suite)

Run the benchmark suite:

```bash
PYTHONPATH=src python3 benchmarks/suite.py --out sandbox_tmp/benchmarks/v1.1.0.json
```

See `benchmarks/README.md` for case IDs and run tuning options.

## 9. Headphone binaural preview (v1.1)

Render a deterministic binaural audition file alongside any safe-render run:

```bash
python -m mmo safe-render \
  --report out/report.json \
  --render-many \
  --render-many-targets stereo,5.1,7.1.4 \
  --out-dir out/deliverables \
  --preview-headphones
```

Each target produces a companion `.headphones.wav` with explainable metadata
linking it back to its source render.

## 10. Variant runner (v1.1)

Render multiple output variants while reusing cached analysis:

```bash
python -m mmo safe-render \
  --report out/report.json \
  --render-many \
  --render-many-targets stereo,5.1,7.1,7.1.4 \
  --layout-standard SMPTE \
  --out-dir out/variants/smpte

python -m mmo safe-render \
  --report out/report.json \
  --render-many \
  --render-many-targets stereo,5.1,7.1,7.1.4 \
  --layout-standard FILM \
  --out-dir out/variants/film
```

Analysis artifacts are content-hash-keyed so the second run skips the scan phase.

## 11. Project session persistence (v1.1)

Save and restore the full scene + history + receipts:

```bash
# Save session after a render run
python -m mmo project save --out out/session.json

# Reload and continue from that state
python -m mmo project load --session out/session.json
```

Session files are strict-schema JSON with deterministic, sorted keys.

## 12. Troubleshooting (v1.1)

- `python -m mmo env doctor` verifies optional runtime tools (for example ffprobe).
- If truth metering fails, reinstall with `pip install .[truth]`.
- If PDF export fails, reinstall with `pip install .[pdf]`.
- For deterministic checks in development, run:

```bash
python3 tools/validate_contracts.py
PYTHONPATH=src python3 -m pytest -q
```
