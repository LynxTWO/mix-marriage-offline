# Coverage Pass Unknowns

<!-- markdownlint-disable-file MD013 -->

This file records blockers to honest large-repo coverage planning. Add entries
here instead of pretending the whole repo has been reviewed when evidence is
thin or split across surfaces.

Status for the 2026-04-16 coverage pass: no blocking coverage unknowns remained
after inspection.

| Area or file | Concern | Why it matters | Evidence found so far | Likely owner if known | Next best check | Risk level |
| --- | --- | --- | --- | --- | --- | --- |
| _None in current pass_ | The slice-planning pass could classify the tracked repo shape, excluded surfaces, and next-pass order without leaving a coverage blocker. | Later large-repo passes still need one place to record real blockers instead of smoothing them over in the ledger. | Reviewed the top-level repo tree, existing architecture docs, coverage ledger baseline, unknowns logs, `src/mmo/` module layout, GUI and Tauri directory structure, package manifests, Cargo and Tauri config, `Makefile`, workflows, and tracked examples or fixture docs. | not declared in repo | Add a row when a later slice cannot be ranked or explained honestly from repo evidence. | low |
