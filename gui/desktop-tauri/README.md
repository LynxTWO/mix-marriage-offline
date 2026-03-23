# MMO Desktop Tauri App

This directory contains the shipped MMO desktop app.

For end users, this folder is not the normal starting point. Use the packaged
release assets from GitHub Releases instead of running local build commands.

## What the packaged app covers

The desktop app drives the same artifact-backed workflow as the CLI:

- `Doctor`
- `Validate`
- `Analyze`
- `Scene`
- `Render`
- `Results`
- `Compare`

It writes the same core artifacts a release user should expect:

- `project/validation.json`
- `report.json`
- `report.scan.json`
- `stems_map.json`
- `bus_plan.json`
- `scene.json`
- `scene_lint.json`
- `render_manifest.json`
- `safe_render_receipt.json`
- `render_qa.json`
- `compare_report.json`

`project/validation.json` is project-scoped. It validates the nested
`workspace/project` scaffold and does not claim to validate later workspace-root
scene or render outputs such as `scene.json` or `render_manifest.json`.

## Packaged release note

The desktop app launches a bundled MMO sidecar behind the scenes. Think of that
sidecar as the audio engine: the app shell is the front desk, and the sidecar
does the real analysis and render work.

If the app opens but no stage will run, start with `Doctor`. If `Doctor` also
fails, the packaged install likely needs to be reinstalled.

## Local development

Prerequisites:

1. Install the Tauri prerequisites for your OS:
   [https://tauri.app/start/prerequisites/](https://tauri.app/start/prerequisites/)
2. Use Node `24.x`
3. Install the pinned Rust toolchain if needed:
   `rustup toolchain install 1.94.0`

Setup:

1. Run `npm install`
2. From the repo root, install Python build dependencies:
   `python -m pip install -e ".[truth,pdf]" pyinstaller`
3. If your system uses `python3` instead of `python`, set `PYTHON=python3` for
   the sidecar build commands

Useful commands:

- `npm run lint`
- `npm test`
- `npm run prepare-sidecar`
- `npm run tauri dev`
- `npm run tauri build -- --bundles appimage`

Notes:

- `tauri dev` and `tauri build` automatically run `npm run prepare-sidecar`
- desktop production builds do not require the old `gui/server.mjs` runtime
- there is no `.[gui]` Python extra anymore; Tauri is the only shipped desktop
  app path

## CI and packaged smoke

GitHub Actions builds this app on Windows, macOS, and Linux.

The workflows:

- build the frozen MMO sidecar
- build packaged Tauri bundles
- launch the packaged app in smoke mode
- verify `Doctor` plus the `Validate -> Analyze -> Scene -> Render` path
- assert that the expected workspace artifacts were written

The packaged smoke harness lives at:

- `tools/smoke_packaged_desktop.py`
