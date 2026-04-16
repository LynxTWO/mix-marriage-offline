# Critical Path Unknowns

<!-- markdownlint-disable-file MD013 -->

This file records unresolved questions from comment-only critical-path passes.
Add entries here instead of guessing when a risky code path cannot be explained
confidently from repo evidence.

Status for the 2026-04-16 pass: no unresolved critical-path questions remained
after inspection.

| File | Line range or function | What is unclear | Why it matters | Evidence found so far | What would confirm the answer |
| --- | --- | --- | --- | --- | --- |
| _None in the current pass_ | _N/A_ | The selected backend paths were explainable from code, docs, and the system map without inventing behavior. | Keep this file present so future passes have a stable place to record uncertainty instead of burying it in comments. | Reviewed `src/mmo/resources.py`, `src/mmo/core/plugin_loader.py`, `src/mmo/core/plugin_market.py`, `src/mmo/cli_commands/_project.py`, `src/mmo/cli_commands/_gui_rpc.py`, `src/mmo/core/render_engine.py`, `src/mmo/core/watch_folder.py`, and `docs/architecture/system-map.md`. | Add one row per unresolved behavior as soon as a future pass finds a gap. |
