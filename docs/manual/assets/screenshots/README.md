# Manual screenshot baselines

This directory holds the committed screenshot baselines for the MMO desktop
manual.

"Canonical state" means a deterministic, named app state used for docs and
regression baselines. Screenshots are canonical app states, not exhaustive UI
coverage. Screenshots do not attempt to capture every transient state. Native
file pickers and OS dialogs are described in text, not committed as baseline
screenshots.

All currently committed Tauri manual PNGs use a fixed-region desktop capture
contract: a 1280 x 900 CSS-pixel Firefox viewport positioned on the top of the
app shell or a named screen/widget anchor. They are not full-page document
captures.

## Policy

- Treat these PNGs as the authoritative manual/regression baseline for the
  named Tauri desktop states below.
- Compact, loaded, and expanded states must be named explicitly in the manual.
  If a state is too dynamic for one stable PNG, keep it text-only but still
  give it a canonical state name.
- Refresh screenshots only when a canonical state meaning changes: a new
  default layout, a different required panel, changed workflow emphasis, or a
  materially different orientation surface for readers. This also includes
  intentional fixed-region composition changes that move the anchored shell or
  screen surfaces enough to invalidate the committed baseline.
- Do not commit native file pickers, OS dialogs, or other platform-specific
  transient states as baselines.
- Prefer fixed-region captures over full-state document captures. Use an
  intentionally full-state PNG only when the whole document height is itself
  the canonical contract, and name that choice explicitly in this README and
  the walkthrough.
- After intentional GUI changes, update both the screenshot baselines and the
  manual chapter that references them.

## Capture contract

- Fixed-region committed PNGs: all current Tauri baselines. Each image is a
  stable 1280 x 900 CSS-pixel desktop frame. Session uses the top of the app
  shell. Results and Compare anchor on their respective loaded summary widgets.
  The Scene captures anchor on the Scene locks card so the lock-context state
  remains visible inside the fixed frame.
- Intentionally full-state committed PNGs: none in the current Tauri manual
  set. If that changes later, document the reason here before committing the
  baseline.
- Text-only canonical states: use this when a meaningful state depends on
  expansion depth or viewport height. The current example is Results secondary
  inspection expanded.

## Screenshot inventory

| Filename | Canonical state | Capture contract | Used in manual |
| --- | --- | --- | --- |
| `tauri_session_ready.png` | Validate screen, session-ready empty state | Fixed region: top of app shell | [Chapter 10 / Validate](../../10-gui-walkthrough.md#validate) |
| `tauri_session_loaded_compact.png` | Session shell, loaded compact workspace mode | Fixed region: top of app shell | [Chapter 10 / Shared session shell](../../10-gui-walkthrough.md#shared-session-shell) |
| `tauri_scene_loaded.png` | Scene screen, loaded with lock context | Fixed region: Scene locks anchor in viewport | [Chapter 10 / Scene](../../10-gui-walkthrough.md#scene) |
| `tauri_scene_locks_editor.png` | Scene screen, lock editor open | Fixed region: Scene locks anchor in viewport | [Chapter 10 / Scene](../../10-gui-walkthrough.md#scene) |
| `tauri_results_loaded.png` | Results screen, loaded default state | Fixed region: Results summary anchor in viewport | [Chapter 10 / Results](../../10-gui-walkthrough.md#results) |
| `tauri_compare_loaded.png` | Compare screen, loaded loudness-matched state | Fixed region: Compare summary widget anchor in viewport | [Chapter 10 / Compare](../../10-gui-walkthrough.md#compare) |

## Named dynamic state without a committed PNG

| State name | Why it stays text-only | Used in manual |
| --- | --- | --- |
| Results screen, secondary inspection expanded | The inspection sections move with viewport width, sidebar mode, and panel expansion, so the state is named in text but not committed as a baseline screenshot. | [Chapter 10 / Results](../../10-gui-walkthrough.md#results) |

## Refresh workflow

Use this whenever an intentional GUI change might have changed a canonical
state.

1. Capture a fresh comparison set into a temp directory.
2. Diff it against the committed baselines.
3. If the change is intentional, refresh the committed baselines.
4. Update the manual text in [Chapter 10](../../10-gui-walkthrough.md) if the
   canonical state meaning or orientation text changed.

```bash
python tools/capture_tauri_screenshots.py --out-dir /tmp/mmo-tauri-screens
python tools/check_screenshot_diff.py --committed docs/manual/assets/screenshots --generated /tmp/mmo-tauri-screens
```

If the GUI change is intentional and the canonical state meaning really did
change, refresh the committed baselines:

```bash
python tools/capture_tauri_screenshots.py --out-dir docs/manual/assets/screenshots
```

Then review and commit the updated PNGs together with the matching manual text.

## Interpreting screenshot diffs

- Small variance is acceptable. Minor rendering jitter, PNG compression
  variance, and tiny visual nits should stay under the diff threshold.
- Large state/layout changes usually mean one of two things: the app drifted
  into the wrong state during capture, or a canonical state meaning changed and
  the baseline now needs to be refreshed.
- A size mismatch usually means the capture contract drifted: wrong viewport,
  wrong anchor region, or a stale full-page baseline still being compared
  against the fixed-region contract.
- If a large diff is intentional, refresh the baselines and manually update the
  walkthrough chapter so the screenshots, captions, and surrounding text still
  describe the same named state.
- Native file pickers and OS dialogs never need baseline refreshes because they
  are intentionally text-only.
