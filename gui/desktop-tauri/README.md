# MMO Desktop Tauri Scaffold

This directory contains the isolated Tauri 2 desktop app for MMO. The app now
ships a frozen `mmo` CLI as a Tauri sidecar and exposes a Doctor screen that
proves the bundled runtime can execute offline.

## Local development

1. Install the Tauri prerequisites for your OS:
   https://tauri.app/start/prerequisites/
2. Install desktop dependencies:
   `npm install`
3. Install Python sidecar build dependencies from the repo root:
   `python3 -m pip install -e ".[truth,pdf,gui]" pyinstaller`
4. Run the frontend only:
   `npm run dev`
5. Prepare the MMO sidecar manually if you want:
   `npm run prepare-sidecar`
6. Run the desktop app:
   `npm run tauri dev`

`tauri dev` and `tauri build` automatically call `npm run prepare-sidecar`
through `beforeDevCommand` / `beforeBuildCommand`. The prepare step skips the
sidecar rebuild when the staged binary in `src-tauri/binaries/` is newer than
the MMO Python sources and packaged data.

## CI

GitHub Actions builds this app on Windows, macOS, and Linux. The workflow:

- installs Python + PyInstaller so the frozen MMO sidecar can be built,
- installs Node and Rust toolchains,
- runs `npm run lint`,
- runs `npm test --if-present`,
- builds a release binary with `npm run tauri build -- --no-bundle`,
- uploads the resulting platform binary from `src-tauri/target/release/`.
