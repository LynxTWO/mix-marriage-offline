# MMO Desktop Tauri App

This directory contains the isolated Tauri 2 desktop app for MMO. It is the
primary packaged desktop path and ships a frozen `mmo` CLI as a Tauri sidecar.

Current workflow coverage includes:

- `Doctor` sidecar verification,
- `Prepare` project/workspace creation,
- `Validate` project artifact checks,
- `Analyze` stems into `report.json`,
- `Scene` artifact inspection,
- `Render` via `safe-render --live-progress` with live timeline logs,
- `Results` artifact review,
- `Compare` workflow entry points.

Desktop production builds do not require the Node `gui/server.mjs` runtime.

## Local development

1. Install the Tauri prerequisites for your OS and use Node 24 LTS:
   [Tauri prerequisites](https://tauri.app/start/prerequisites/) If you use
   `nvm`, run `nvm use` from the repo root first.
2. Install the pinned Rust toolchain for the Tauri crate if needed:
   `rustup toolchain install 1.94.0`
3. Install desktop dependencies: `npm install`
4. Install Python sidecar build dependencies from the repo root:
   `python -m pip install -e ".[truth,pdf,gui]" pyinstaller` If your machine
   only has `python3`, use `python3` here and set `PYTHON=python3` when running
   the desktop build commands.
5. Run the frontend only: `npm run dev`
6. Run the desktop UI tests: `npm test`
7. Prepare the MMO sidecar manually if you want: `npm run prepare-sidecar`
8. Run the desktop app: `npm run tauri dev`

In the app:

1. Use the `Dashboard` and `Presets` screens to exercise the design-system
   controls and scale presets.
2. Paste a stems folder path on `Run`.
3. Paste a workspace folder path on `Run`.
4. Run `Doctor` if you want to verify the packaged runtime first.
5. Run `Run All` to execute prepare -> validate -> analyze -> render directly
   through the sidecar.
6. Use `Reveal Workspace` to open the artifact folder after the run.

`tauri dev` and `tauri build` automatically call `npm run prepare-sidecar`
through `beforeDevCommand` / `beforeBuildCommand`. The prepare step skips the
sidecar rebuild when the staged binary in `src-tauri/binaries/` is newer than
the MMO Python sources and packaged data.

## CI

GitHub Actions builds this app on Windows, macOS, and Linux. The workflow:

- installs Python + PyInstaller so the frozen MMO sidecar can be built,
- installs Node and Rust toolchains,
- runs `npm run lint`,
- installs the Playwright browser bundle and runs `npm test`,
- builds packaged desktop bundles (`msi`, `app`, `AppImage`) with
  `npm run tauri build -- --bundles ...`,
- launches the packaged app in smoke mode so the bundled sidecar must pass
  doctor plus validate/analyze/scene/render against a tiny fixture,
- uploads the packaged bundle artifacts after smoke succeeds.
