# MMO Desktop Tauri Scaffold

This directory contains an isolated Tauri 2 desktop app scaffold created with
`create-tauri-app` using the `vanilla-ts` Vite template.

## Local development

1. Install the Tauri prerequisites for your OS:
   https://tauri.app/start/prerequisites/
2. Install dependencies:
   `npm install`
3. Run the frontend only:
   `npm run dev`
4. Run the desktop app:
   `npm run tauri dev`

## CI

GitHub Actions builds this app on Windows, macOS, and Linux. The workflow:

- installs Node and Rust toolchains,
- runs `npm run lint`,
- runs `npm test --if-present`,
- builds a release binary with `npm run tauri build -- --no-bundle`,
- uploads the resulting platform binary from `src-tauri/target/release/`.
