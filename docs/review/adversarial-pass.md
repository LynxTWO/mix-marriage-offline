# Adversarial Edge-Case Review

<!-- markdownlint-disable-file MD013 -->

## Areas reviewed in this pass

- `docs/architecture/system-map.md`
- `docs/architecture/coverage-ledger.md`
- `docs/unknowns/critical-paths.md`
- `docs/security/logging-audit.md`
- `docs/unknowns/logging-audit.md`
- `.github/workflows/ci.yml`, `release.yml`, `pages.yml`, and `policy-validation.yml`
- `Makefile`, `gui/package.json`, and `gui/desktop-tauri/package.json`
- support and control-plane tools under `tools/`, with extra attention on cleanup, sync, smoke, screenshot, benchmark, and direct-render helpers

## What earlier passes got right

- The main repo shape is real. The primary runtime is still the Python CLI, the local dev shell, and the packaged Tauri desktop app. I did not find a hidden database, queue, SaaS telemetry SDK, notebook-driven runtime, or submodule-owned live path in this repo.
- The comment loop improved the core map in the right places. Render authority, project state, GUI bridge, browser state, packaged desktop state, native shell, plugin contracts, and packaged contract loaders are much easier to explain from repo evidence than they were before.
- The logging audit corrected one easy false comfort. Local-only CLI JSON, stderr, and smoke receipts are not harmless once CI, support, or issue threads capture them.

## What earlier passes overstated or missed

| Claim or earlier habit | Evidence | Gap | Why it matters |
| --- | --- | --- | --- |
| The coverage ledger was treated as the current source of truth for slice status. | `coverage-ledger.md` still marked the dev-shell frontend, packaged desktop frontend, desktop native shell, and DSP follow-up exporter slice as `mapped` or `deferred` after later comment passes already covered them. | The ledger had stale rows, so later slice ranking could drift away from actual coverage. | A stale ledger makes the next review order look more settled than it is. |
| `docs/unknowns/critical-paths.md` repeatedly said "no open question remained" across broad slices. | The file records many passes as fully explainable, but later audit work still found release, logging, and support-path gaps outside those narrow code slices. | The statements were too easy to read as repo-wide closure instead of slice-local closure. | That wording makes overclaiming easier when parallel support or control-plane paths were never first-class review targets. |
| The repo map undercounted support and control-plane tools. | `tools/safe_cleanup.py` deletes allowlisted repo-local dirs. `tools/sync_packaged_data_mirror.py` copies and deletes packaged-data mirrors. `tools/sync_claude_agents.py` rewrites `.claude/agents/`. `tools/run_renderers.py` drives renderer logic outside the main CLI docs. `tools/capture_tauri_screenshots.py` rewrites screenshot baselines. `tools/benchmark_render_precision.py` writes temp scenes and calls `render-run` directly. | These paths were present, but they were not elevated as first-class review slices. | They act like quiet control planes. They can delete, copy, benchmark, or publish evidence outside the main runtime flow. |
| The Pages workflow looked like a low-stakes doc note. | `.github/workflows/pages.yml` has `pages: write`, `id-token: write`, and `actions/deploy-pages`. | The map did not treat Pages deploy as an out-of-repo publish boundary with its own control-plane risk. | Public docs are shipped behavior for operators and users, even if they are not audio runtime code. |
| Local-only assumptions were treated as enough boundary protection. | `docs/security/logging-audit.md` shows raw GUI stderr forwarding, live render progress paths on stderr, path-rich packaged smoke receipts, and machine-readable CLI JSON with local paths and metadata. | "Offline" and "local" do not stop data from becoming telemetry once logs, stdout, or receipts are shared. | Trust-boundary notes should reflect where local outputs escape into CI, release logs, or support channels. |

## Which risks moved up or down

| Area | Direction | Why |
| --- | --- | --- |
| Support tooling and quiet control planes | Up | Cleanup, sync, screenshot, direct-render, and benchmark helpers can mutate repo state, packaged data, or review evidence outside the main CLI and desktop flows. |
| Release tooling and Windows installer verification | Up | Release signing, packaged smoke, installer receipts, and GitHub artifact handling still depend on out-of-repo behavior that the repo cannot fully prove from static review alone. |
| Product-output and logging boundary | Up | The logging audit showed that CLI JSON, stderr, traces, and smoke receipts become telemetry once wrappers or CI capture them. |
| Main GUI and desktop runtime shape | Down | The earlier comment passes and tests now cover the local bridge, browser state, packaged desktop state, and native shell entrypoints well enough that they are no longer the weakest map area. |
| Shared plugin contracts and registry loaders | Down | Shared plugin contracts, loader rules, market metadata, and packaged contract loaders now have targeted review evidence. The remaining gap is bundled plugin implementation behavior, not the contract surface itself. |

## Slice order changes after this review

1. Move support-tool and release-control-plane review earlier than any more GUI comment work.
   Focus on `tools/safe_cleanup.py`, `tools/sync_packaged_data_mirror.py`, `tools/sync_claude_agents.py`, `tools/run_renderers.py`, `tools/capture_tauri_screenshots.py`, `tools/benchmark_render_precision.py`, `.github/workflows/release.yml`, and `.github/workflows/pages.yml`.
2. Keep bundled plugin implementations as a separate slice from shared plugin contracts.
   The contract and authoring surfaces are much better explained now, but `plugins/` and `src/mmo/data/plugins/` still deserve their own read-only or comment pass if plugin behavior becomes the focus.
3. Treat logging fixes as follow-up work, not as proof that the trust map is closed.
   The release path, GUI stderr forwarding, render live-progress logging, and product-output JSON all still need explicit approval before edits.

## Protected areas that still need human approval before any edit

- `gui/lib/mmo_cli_runner.mjs` and `gui/lib/rpc_process_client.mjs`
  GUI bridge and RPC subprocess surfaces are protected. The logging audit already found raw stderr forwarding here.
- `src/mmo/cli_commands/_renderers.py` and `src/mmo/core/progress.py`
  Render live-progress logging is a render-path change, even when the edit only narrows path output.
- `tools/smoke_packaged_desktop.py` and `.github/workflows/release.yml`
  Packaged smoke, installer verification, and signing flows are protected support and control-plane paths.
- `tools/safe_cleanup.py` and `tools/sync_packaged_data_mirror.py`
  Cleanup and packaged-data mirror behavior fall under delete, cleanup, sync, and packaged-data resolution rules in `AGENTS.md`.
- `_project.py`, `scan_session.py`, and related machine-readable JSON outputs
  Narrowing those outputs would touch product-output contracts, not only logs.

Earlier protected-area edits on this branch were comment-only and user-directed.
This pass did not find an unapproved behavior change in a protected area.
