# The main workflows

MMO has four “normal human” workflows. Pick the one that matches your intent,
not your ego.

## Workflow A: I want a quick engineering check and notes

Quick path. mmo scan ./stems --out out/report.json mmo export --report
out/report.json --csv out/recall.csv

What you get. A report JSON with validation, issues, and any enabled meters. A
recall CSV you can apply inside your DAW.

Pro notes. Use `--meters basic` or `--meters truth` if you want deeper meter
packs. Use `--summary` if you want a human-readable scan summary printed to the
terminal. Bare `mmo scan` stdout now defaults to the shared-safe JSON profile.
Use `--out` when local tooling needs the full local report. Shared-safe stdout
is the only shell JSON profile.

## Workflow B: I want “one button” artifacts in a deterministic folder

Quick path. mmo run --stems ./stems --out out/run_001 --export-csv --export-pdf
--bundle

What you get. A single folder with report.json plus optional PDF, CSV, and
ui_bundle.json.

Pro notes. `run` is the musician-friendly orchestrator. It can also do apply,
render, render-many, translation, deliverables index, and listen pack outputs.
Caching is on by default, keyed by lockfile plus run_config hash.

## Workflow B+: I want spatial placement with a scene template

Add `--scene-templates` to any `mmo run` call to apply a named placement
template before the scene is built.

```sh
mmo run --stems ./stems --out out/run_001 \
  --scene-templates TEMPLATE.SCENE.LIVE.YOU_ARE_THERE \
  --render-many --targets stereo,5.1,7.1
```

Available templates:

- `TEMPLATE.SCENE.LIVE.YOU_ARE_THERE` — listener at center of stage; drums
  behind, guitars at sides, bass front-left, lead vocal front-center. Sets
  `in_band` perspective so immersive routing is fully active.
- `TEMPLATE.SEATING.BAND.IN_BAND` — role-driven stage seating for modern band
  stems.
- `TEMPLATE.SEATING.ORCHESTRA.IN_ORCHESTRA` — orchestral seating with
  in-orchestra perspective.
- `TEMPLATE.SEATING.ORCHESTRA_AUDIENCE` — audience-perspective orchestral map.
- `TEMPLATE.SCENE.STEREO.BAND_WIDE_VOCAL_CENTER` — keep lead anchored, spread
  band safely (stereo-focused).
- `TEMPLATE.SCENE.SURROUND.FRONT_STAGE_CLEAR_REAR_FIELD` — front stage objects,
  beds carry rear energy.

Templates only fill missing intent fields — they do not overwrite locks you have
already set.

## Workflow C: I want mix-once, render-many deliverables

Quick path. mmo analyze ./stems --out-report out/report.json mmo safe-render
--report out/report.json --render-many --render-many-targets stereo,5.1,7.1.4
--layout-standard SMPTE --out-dir out/deliverables --receipt-out
out/receipt.json

What you get. Render outputs for each target you requested. A safe-render
receipt with what was auto-applied, what was blocked, and why.

Pro notes. Use `--dry-run` first when you want to inspect what would happen. Use
`--preview-headphones` when you want a deterministic headphone preview
deliverable. Use `--approve none` to force “no overrides.” Use `--approve all`
only when you truly accept the risk.

## Workflow D: I want a project scaffold I can revisit

Quick path. mmo project init --stems-root ./stems --out-dir ./project mmo
project refresh --project-dir ./project --stems-root ./stems

What you get. A structured project directory with stems indexing,
classification, and draft intent artifacts. This is the clean path for teams,
long projects, and repeat delivery.

Pro notes. Project scaffolds help you separate “ingest and classify” from
“render and deliver.” They also make GUI payload building cleaner because file
paths become stable and allowlisted.

If you want to follow these same workflows in the Tauri desktop app, read the
[Desktop GUI walkthrough](10-gui-walkthrough.md). That chapter follows the same
`Validate → Analyze → Scene → Render → Results → Compare` order, but it
describes canonical GUI states such as session-ready, loaded compact workspace,
and loaded Results/Compare views instead of assuming one fixed screen shape.
