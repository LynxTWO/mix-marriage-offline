# Architecture Pass Unknowns

This file records unresolved architecture questions from read-only inventory
passes. Add rows here instead of guessing when a runtime unit, boundary, or
artifact cannot be explained from repo evidence.

Status for the 2026-04-15 inventory pass: no unresolved architecture questions
remained after inspection.

| File or module | What is unclear | Why it matters | Evidence found so far | What would clarify it |
| --- | --- | --- | --- | --- |
| _None in the current pass_ | The current inventory pass could tie each reviewed runtime unit, entrypoint, artifact store, and trust boundary to repo evidence. | Keep this file present so later passes have a stable place to record uncertainty instead of hiding it in code or comments. | Reviewed repo docs, `src/mmo/cli.py`, `src/mmo/cli_commands/_gui_rpc.py`, `gui/server.mjs`, `src/mmo/resources.py`, plugin loader and market code, Tauri config, desktop docs, and CI or release workflows. | Add one row per unresolved boundary as soon as a future pass finds a gap. |
