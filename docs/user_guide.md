# MMO User Guide

> **This is a quickstart pointer.**
> For the full User Manual, see [manual/00-manual-overview.md](manual/00-manual-overview.md).

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
pip install .[watch]
```

Verify the CLI is available:

```bash
python -m mmo --help
```

Run the environment doctor to confirm optional dependencies:

```bash
python -m mmo env doctor --format text
```

## 2. First run (scan stems and export a recall sheet)

Given a folder of aligned stems:

```bash
python -m mmo scan ./stems --out out/report.json
```

Export a recall CSV:

```bash
python -m mmo export --report out/report.json --csv out/recall.csv
```

## 3. Mix-once render-many

Analyze, then render to multiple targets in one pass:

```bash
python -m mmo analyze ./stems --out-report out/report.json
python -m mmo safe-render \
  --report out/report.json \
  --render-many \
  --render-many-targets stereo,5.1,7.1.4 \
  --out-dir out/deliverables \
  --receipt-out out/receipt.json
```

Use `--dry-run` first to inspect the plan without writing audio.

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
python -m mmo watch ./incoming_stems --out out/watch_runs
```

Use `--once` to process once and exit instead of watching continuously.

## 6. GUI workflow

Launch the desktop GUI:

```bash
mmo-gui
```

Or from a repo checkout:

```bash
python -m mmo.gui.main
```

## 7. Plugin marketplace (offline index)

List bundled marketplace entries:

```bash
python -m mmo plugin list --format json
```

Refresh the local snapshot:

```bash
python -m mmo plugin update
```

## 8. Project sessions

Save and restore a project session (scene + history + receipts):

```bash
python -m mmo project save ./project --session out/session.json
python -m mmo project load ./project --session out/session.json
```

## 9. Troubleshooting

- If truth metering fails: `pip install .[truth]`
- If PDF export fails: `pip install .[pdf]`
- For watch-folder automation: `pip install .[watch]`
- For deterministic checks in development:

```bash
python tools/validate_contracts.py
python -m pytest -q
```

For detailed troubleshooting see [manual/13-troubleshooting.md](manual/13-troubleshooting.md).
