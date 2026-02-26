# 12 GUI Dev Shell

This document defines the first real GUI shell for MMO as a thin dev client.

Scope:

- spawn `mmo gui rpc`,
- call `rpc.discover`, `env.doctor`, `project.show`, `project.build_gui`,
- render plugin forms from `config_schema` + `ui_hints`,
- render layout snapshots from plugin `ui_layout`.

Non-goals:

- no installers,
- no audio preview,
- no production packaging.

## Golden Smoke Path

Use this same repo-relative path on every machine:

- Stems root: `sandbox_tmp/gui_smoke_demo/stems_root`
- Project dir: `sandbox_tmp/gui_smoke_demo/project`

## Prerequisites

- Python 3.12+
- Node.js 20+
- MMO installed in editable mode so the CLI is available:
  - `python -m pip install -e .`

## Windows (PowerShell)

```powershell
Set-Location C:\GitHub\mix-marriage-offline
python -m pip install -e .
python tools/make_demo_stems.py sandbox_tmp/gui_smoke_demo/stems_root/stems
mmo project init --stems-root sandbox_tmp/gui_smoke_demo/stems_root --out-dir sandbox_tmp/gui_smoke_demo/project
mmo project render-init sandbox_tmp/gui_smoke_demo/project --target-layout LAYOUT.2_0
Set-Location gui
npm install
npm run dev
```

If `mmo` is not on PATH:

```powershell
$env:MMO_GUI_PYTHON_BIN = "python"
npm run dev
```

Open `http://localhost:4175`.

## Linux/macOS (bash/zsh)

```bash
cd /path/to/mix-marriage-offline
python3 -m pip install -e .
python3 tools/make_demo_stems.py sandbox_tmp/gui_smoke_demo/stems_root/stems
mmo project init --stems-root sandbox_tmp/gui_smoke_demo/stems_root --out-dir sandbox_tmp/gui_smoke_demo/project
mmo project render-init sandbox_tmp/gui_smoke_demo/project --target-layout LAYOUT.2_0
cd gui
npm install
npm run dev
```

If `mmo` is not on PATH:

```bash
MMO_GUI_PYTHON_BIN=python3 npm run dev
```

Open `http://localhost:4175`.

## GUI Smoke Flow

In the running GUI:

1. Click `Call rpc.discover`.
2. Click `Call env.doctor`.
3. Set:
   - `Project directory`: your `sandbox_tmp/gui_smoke_demo/project` absolute path.
   - `Stems root (for scan)`: your `sandbox_tmp/gui_smoke_demo/stems_root` absolute path.
   - `Pack output`: leave default or set another path under the project.
   - `Plugins directory`: keep `plugins` unless testing another plugin tree.
4. Click `Call project.show`.
5. Click `Call project.build_gui + refresh`.

Expected result:

- `project.show` output includes `ui_bundle.json` with `exists: true`.
- Plugin cards are rendered (schema fields when present).
- Layout snapshots render as section/widget overlays when plugin layouts exist.

## Dev Commands

```bash
cd gui
npm run dev
npm test
```

`npm test` runs Node unit tests for:

- RPC subprocess client behavior,
- schema-to-form field mapping.
