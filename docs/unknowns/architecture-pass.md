# Architecture Pass Unknowns

<!-- markdownlint-disable-file MD013 -->

This file records unresolved architecture questions from read-only inventory
passes. Add rows here instead of guessing when a runtime unit, boundary, or
artifact cannot be explained from repo evidence.

Status for the 2026-04-16 architecture refresh: no open architecture unknowns
remained after inspection.

| Area or file | Concern | Why it matters | Evidence found so far | Likely owner if known | Next best check | Risk level |
| --- | --- | --- | --- | --- | --- | --- |
| _None in current pass_ | The architecture refresh could tie each reviewed runtime unit, entry surface, state boundary, and trust boundary to repo evidence without leaving an open blocker. | Later passes still need one stable place to record uncertainty instead of pushing it into code or prose. | Reviewed repo docs, steering files, `pyproject.toml`, `requirements.txt`, `Makefile`, GUI `package.json` files, Tauri `Cargo.toml`, `.github/workflows/`, the existing system map, the prior unknowns log, smoke tooling, and the backend entry surfaces already mapped in the repo. | not declared in repo | Add a row when a later pass finds a boundary it cannot explain from repo evidence. | low |
