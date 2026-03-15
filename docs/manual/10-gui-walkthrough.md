# Desktop GUI walkthrough

The GUI exists to reduce friction, not to hide the truth. It wraps the same CLI
behaviors, keeps receipts, and writes the same artifacts the CLI writes. Every
action is explainable, every output is traceable.

The primary GUI is the **Tauri desktop app**. It covers the full artifact-backed
workflow sequence: `Validate → Analyze → Scene → Render → Results → Compare`.

---

## Launch

Run the Tauri desktop app from the repo or your installed package:

```
cd gui/desktop-tauri
npm run tauri dev        # development
npm run tauri build      # production build
```

Or launch the installed binary directly if you used a packaged install.

---

## Session setup

Before running any stage, configure your session in the **session sidebar**:

- **Stems dir** — folder containing your exported stem files.
- **Workspace dir** — output folder where all artifacts will be written.
- **Layout standard** — the channel layout standard for your delivery (e.g.
  SMPTE, FILM, VST3). Internally normalized to SMPTE.
- **Render target** — the delivery target (e.g. stereo, 5.1, 7.1.4).

Use the native **Browse...** buttons for stems, workspace, and optional
scene-lock artifacts when running the packaged desktop app. Exact manual path
entry still works, and the app keeps deterministic recent-path chips for stems,
workspaces, scene-locks, and compare inputs so repeat sessions are faster.

The empty state keeps the full hero treatment for onboarding. Once a workspace
or artifact is loaded, the left rail automatically compacts so the active
workflow screens get more horizontal room.

These fields persist across screen switches and are passed to every CLI command
the GUI runs.

The **scale control** (top-right, three buttons: 90 / 100 / 115) adjusts the
interface scale. Use 115 on a high-DPI or large display. Hold a modifier key
while adjusting a knob or slider to see the fine-adjust indicator.

---

## Screen-by-screen

### Validate

Run deterministic project and stem checks before committing to later stages.

1. Confirm your stems dir and workspace dir are set.
2. Click **Run Validate**.
3. The screen shows: artifact paths written, a summary of validation outcomes,
   and a JSON preview of the validation report.

Validation failures surface here with actionable messages. Fix them before
moving to Analyze.

![Validate screen — session controls and empty state](assets/screenshots/tauri_session_ready.png)

---

### Analyze

Run CLI-backed analysis and persist the scan artifacts.

1. Click **Run Analyze**.
2. The screen shows: a summary of analysis outcomes, the raw scan log, and a
   JSON preview of the analysis report.

The same deterministic receipts and logs the CLI writes appear here. Nothing is
synthesized — the GUI reads what the CLI wrote.

---

### Scene

Inspect the generated scene intent and preview routing context.

1. Click **Build Scene**.
2. The screen shows:
   - **Scene summary** — perspective, objects count, beds count, confidence.
   - **Focus XY pad** — discrete depth (50–100) and pan control for scene
     focus exploration.
   - **Scene locks** — inspect the current project scene-lock rows, adjust
     perspective/role/front-only/surround/height overrides, and explicitly save
     `scene_locks.yaml`.
   - **Locks context** — the current scene locks YAML path plus lint warnings
     from `mmo scene lint`.
   - **Objects list** — individual scene objects with their routing context.
   - **JSON preview** — the raw `scene.json`.

The scene is explainable: what was decided, why, and with what confidence.
Lint warnings appear inline when the scene has ambiguous or conflicting context,
and saving scene locks refreshes the scene preview/lint context for reruns.

![Scene screen — objects, locks, and lint context loaded](assets/screenshots/tauri_scene_loaded.png)

---

### Render

Run a deterministic render from the GUI against the same CLI contract.

1. Review the config summary (target, layout, stems dir, workspace).
2. Click **Run Render**.
3. The screen shows a **live progress log** with `[MMO-LIVE]` prefixed lines
   streamed from `mmo safe-render --live-progress`.
4. Click **Cancel** at any time to stop the render gracefully.

The render writes the same output artifacts as `mmo safe-render` from the CLI.
No extra processing is applied by the GUI.

---

### Results

Review all written artifacts, receipts, and what changed.

After a render completes, click **Refresh** (or navigate to Results). The
screen now leads with the artifact browser, selected artifact preview, final
receipt, and what changed, while deeper QA and inspection widgets stay grouped
under lower inspection sections instead of competing equally for attention.

The screen surfaces:

- **Artifact browser** — paths to every output artifact written in this run.
  Use the detail slider (1–10) inside the receipt summary card to control how
  many lines of context appear per artifact.
- **What changed** — a compact summary of output paths and recommendation
  deltas tied to the generated files.
- **QA issues** — render QA issues from the receipt, listed by severity and
  issue ID.
- **Recommendation confidence** — confidence chips sourced from the receipt,
  classified as high (≥75%), medium (≥50%), or low.
- **Inspection meters** — deterministic, artifact-backed views:
  - Vectorscope (goniometer)
  - Transfer-curve proxy (when dynamics context is available)
  - Phase correlation meter
  - Gain reduction meter

Everything on this screen is read from artifacts — nothing is computed by the
GUI itself. Packaged desktop builds also expose native import buttons for the
receipt, manifest, and render-QA artifacts.

![Results screen — receipt, QA issues, meters, and confidence chips](assets/screenshots/tauri_results_loaded.png)

---

### Compare

Run a post-render or post-analysis comparison between two artifact states.

1. Load **A** and **B** artifacts using exact paths, recent compare-input
   chips, or the native JSON/folder picker buttons.
2. Use the **A / B toggle** to switch the active audition state.
3. Use the **compensation knob** (−12 to +12 dB, step 0.1) in the lower
   inspection section to loudness-match the two sides for a fair listen. The
   knob records the compensation method/amount — this is evaluation-only and
   disclosed in the summary.
4. The screen shows:
   - **Compare summary** — the active A/B readout plus delta chips showing what
     moved between A and B.
   - **Loudness match status** — the compensation amount and a "Fair listen"
     disclosure so you know the comparison is level-matched, not representative
     of the final mix level.
   - **Lower inspection details** — compensation fine-tune and the raw
     `compare_report.json` preview.

The compare contract is the same as `mmo compare` from the CLI. The GUI passes
real artifact inputs and reads the resulting `compare_report.json`.

![Compare screen — A/B data loaded with loudness match active](assets/screenshots/tauri_compare_loaded.png)

---

## Recommended workflow order

```
Validate → Analyze → Scene → Render → Results → Compare
```

Each stage depends on artifacts from the prior stage. Running out of order is
allowed but may produce missing-artifact warnings.

---

## Regenerating screenshots

The User Manual screenshots for this chapter are generated by the Tauri
Playwright capture spec. To regenerate them locally:

```
python tools/capture_tauri_screenshots.py --out-dir docs/manual/assets/screenshots
```

This starts the Vite dev server automatically (via the Playwright `webServer`
block) and captures four screens with realistic fixture data:

- `tauri_session_ready.png` — Validate screen, session controls, empty state
- `tauri_scene_loaded.png` — Scene screen with objects, locks, and lint context
- `tauri_results_loaded.png` — Results screen with receipt, QA, and meters
- `tauri_compare_loaded.png` — Compare screen with A/B data and loudness match

After running, commit the updated PNGs. The perceptual diff checker
(`tools/check_screenshot_diff.py`) validates that regenerated screenshots match
the committed baselines within tolerance.

---

## Legacy fallback (deprecated)

The CustomTkinter `mmo-gui` fallback (`python -m mmo.gui.main`) remains
available as a legacy bounded workflow but is **deprecated**. It will not
receive new parity work. For a zero-ambiguity workflow, use the Tauri app or
the CLI directly.

The legacy walkthrough content (screenshots, CTK-specific flow) has been
retired from this chapter. The parity checklist is tracked in
[../gui_parity.md](../gui_parity.md).
