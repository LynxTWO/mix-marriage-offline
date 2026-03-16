# GUI parity checklist

This file is the canonical GUI parity contract for MMO. The desktop app path is
the Tauri app, and parity is complete only when that app covers every required
screen and behavior listed here. In the current repo, that exit rule is
satisfied.

## Desktop App Path

Tauri is the desktop app path for MMO. It is the only GUI surface that should
gain parity work or release-facing desktop workflow claims.

- Desktop implementation: [Tauri desktop README](../gui/desktop-tauri/README.md)
- Product roadmap: [Roadmap](06-roadmap.md)
- Completion gate: [Project When Complete](../PROJECT_WHEN_COMPLETE.md)

## Legacy Retirement Note

The old CustomTkinter desktop implementation has been removed from the repo,
package metadata, CI, and release workflows. Desktop claims, screenshots, and
smoke tests should point only to the Tauri app.

- Legacy note:
  [Desktop GUI walkthrough](manual/10-gui-walkthrough.md)

## Required Links

- [Roadmap](06-roadmap.md)
- [Project When Complete](../PROJECT_WHEN_COMPLETE.md)
- [Tauri desktop README](../gui/desktop-tauri/README.md)
- [Desktop GUI walkthrough (Tauri)](manual/10-gui-walkthrough.md)

## Required Screens

- [x] Validate: open project or workspace, run deterministic project/stem
      checks, and surface actionable validation failures before later stages.
- [x] Analyze: run CLI-backed analysis, persist artifacts, and expose the same
      deterministic receipts and logs that the CLI writes.
- [x] Scene: inspect generated scene intent, preview routing/object-vs-bed
      context, and keep scene artifacts explainable.
- [x] Render: run deterministic render workflows from the GUI against the same
      CLI contracts, including progress and cancellation surfaces.
- [x] Results: show the written artifacts, final receipts, and what changed in a
      way that maps back to generated files.
- [x] Compare: provide post-render or post-analysis comparison workflow entry
      points so users can review outcomes before committing changes.

## Required Behaviors

- [x] A/B loudness-comp compare: comparison defaults must loudness-match the two
      audition states, record the deterministic compensation method/amount in
      `compare_report.json`, and disclose that evaluation-only compensation in
      the user-visible compare readout.
- [x] Dynamics/spatial inspection: Results must expose deterministic,
      artifact-backed gain reduction, phase correlation, and
      goniometer/vectorscope views, with a transfer-curve proxy when the loaded
      artifacts contain enough dynamics context.
- [x] Explainability surfaces: Results/Compare must expose hover/focus
      "what/why" hints, recommendation confidence indicators sourced from
      artifacts, and compact "what changed" summaries after run/apply/compare
      actions.
- [x] Scene locks edit: the GUI supports deterministic scene lock editing,
      explicit save to `scene_locks.yaml`, and refreshes scene context for
      repeatable reruns.

## Explicitly Non-Blocking Here

- Macro mood systems and semantic macro controls remain optional.
- Soundstage candy and non-essential spatial eye candy remain optional.
- A/B/C/D morphing remains optional.

## Exit Rule

Parity lands when every required screen and required behavior above is complete
in the Tauri app. That condition is satisfied in the current repo, so
release-facing desktop workflow claims should point to Tauri.
