# MMO User Guide

> **This is a quickstart pointer.** For the full User Manual, see
> [manual/00-manual-overview.md](manual/00-manual-overview.md).

## 1. Install and verify

Install from source checkout:

```bash
pip install .
```

Optional extras:

```bash
pip install .[pdf]
pip install .[watch]
```

Verify the CLI is available:

```bash
python -m mmo --help
```

Run the environment doctor to confirm required runtime tools and optional PDF
support:

```bash
python -m mmo env doctor --format text
```

## 2. First run (scan stems and export a recall sheet)

Given a folder of aligned stems:

```bash
python -m mmo scan ./stems --out out/report.json
```

Bare `mmo scan` stdout now defaults to the shared-safe JSON profile. Use
`--format json` only when local tooling needs the full local report contract.
`--out` still writes the full file-backed report.

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

Desktop app path: the Tauri desktop app tracked in
[gui_parity.md](gui_parity.md).

The old CustomTkinter `mmo-gui` path has been retired. It no longer ships in
source installs or release artifacts. For headless or checkout workflows, use
the CLI directly.

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

Save and restore a project session (scene + history + allowlisted receipt
snapshots):

```bash
python -m mmo project save ./project --session out/session.json
python -m mmo project load ./project --session out/session.json
```

The CLI now defaults those commands to the shared-safe summary profile. Use
`--format json` only when local tooling needs the full machine-local path
contract.

The current session receipt scaffold is `renders/render_execute.json`,
`renders/render_preflight.json`, and `renders/render_qa.json`.

## 9. Troubleshooting

- If truth metering fails in a source checkout: repair the base install with
  `pip install .`
- If PDF export fails: `pip install .[pdf]`
- For watch-folder automation: `pip install .[watch]`
- For deterministic checks in development:

```bash
python tools/validate_contracts.py
python -m pytest -q
```

For detailed troubleshooting see
[manual/13-troubleshooting.md](manual/13-troubleshooting.md).
