# The main workflows

MMO has four “normal human” workflows.
Pick the one that matches your intent, not your ego.

## Workflow A: I want a quick engineering check and notes

Quick path.
mmo scan ./stems --out out/report.json
mmo export --report out/report.json --csv out/recall.csv

What you get.
A report JSON with validation, issues, and any enabled meters.
A recall CSV you can apply inside your DAW.

Pro notes.
Use `--meters basic` or `--meters truth` if you want deeper meter packs.
Use `--summary` if you want a human-readable scan summary printed to the terminal.

## Workflow B: I want “one button” artifacts in a deterministic folder

Quick path.
mmo run --stems ./stems --out out/run_001 --export-csv --export-pdf --bundle

What you get.
A single folder with report.json plus optional PDF, CSV, and ui_bundle.json.

Pro notes.
`run` is the musician-friendly orchestrator.
It can also do apply, render, render-many, translation, deliverables index, and listen pack outputs.
Caching is on by default, keyed by lockfile plus run_config hash.

## Workflow C: I want mix-once, render-many deliverables

Quick path.
mmo analyze ./stems --out-report out/report.json
mmo safe-render --report out/report.json --render-many --render-many-targets stereo,5.1,7.1.4 --layout-standard SMPTE --out-dir out/deliverables --receipt-out out/receipt.json

What you get.
Render outputs for each target you requested.
A safe-render receipt with what was auto-applied, what was blocked, and why.

Pro notes.
Use `--dry-run` first when you want to inspect what would happen.
Use `--preview-headphones` when you want a deterministic headphone preview deliverable.
Use `--approve none` to force “no overrides.”
Use `--approve all` only when you truly accept the risk.

## Workflow D: I want a project scaffold I can revisit

Quick path.
mmo project init --stems-root ./stems --out-dir ./project
mmo project refresh --project-dir ./project --stems-root ./stems

What you get.
A structured project directory with stems indexing, classification, and draft intent artifacts.
This is the clean path for teams, long projects, and repeat delivery.

Pro notes.
Project scaffolds help you separate “ingest and classify” from “render and deliver.”
They also make GUI payload building cleaner because file paths become stable and allowlisted.