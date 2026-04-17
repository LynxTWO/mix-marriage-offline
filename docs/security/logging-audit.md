# Logging, Telemetry, and Sensitive Data Audit

<!-- markdownlint-disable-file MD013 -->

## Scope and method

This pass audited first-party logging and telemetry sinks across `src/mmo/`,
`gui/`, `tools/`, and `.github/workflows/`.

Search method:

- searched for `console.*`, `print(`, `stderr`, `stdout`, `jsonl`, `ndjson`,
  `trace`, `telemetry`, `analytics`, and secret-bearing keywords such as
  `token`, `secret`, `cookie`, `password`, and `authorization`
- reviewed the GUI bridge and subprocess helpers, packaged smoke harness,
  release workflow logging, agent trace artifacts, and representative CLI JSON
  output surfaces
- excluded vendored code, `node_modules/`, `.venv/`, build outputs, and
  generated artifacts

Confidence:

- high for first-party Node and Python sinks that were inspected directly
- medium for runtime-dependent stderr, installer logs, and other subprocess
  output whose exact payload depends on failure mode
- low for out-of-repo dashboards or platform-native logging that is not defined
  in this repo

Deferred or skipped:

- vendored Rust code under `gui/desktop-tauri/src-tauri/vendor/`
- third-party package internals under `node_modules/` and `.venv/`
- external CI provider log retention rules and any out-of-repo dashboards
- runtime payloads that only appear when Windows installers, CLI commands, or
  RPC subprocesses fail in specific ways

The repo does not appear to use first-party SaaS telemetry or crash-reporting
SDKs such as Sentry, PostHog, Datadog, OpenTelemetry, Rollbar, or LogRocket in
the audited code.

## Findings

| Area or file | Line range | Sink or logger used | What it emits | Why it is sensitive | Risk level | Protected area |
| --- | --- | --- | --- | --- | --- | --- |
| `src/mmo/cli_commands/_renderers.py`, `src/mmo/core/progress.py` | `_renderers.py:2557-2564`, `3117-3127`, `3270-3279`, `3323-3332`, `3401-3415`, `3585-3595`; `progress.py:93-112` | `[MMO-LIVE]` stderr progress lines | Deterministic live-log JSON with raw `where` values such as `report_path`, `out_dir`, `receipt_out_path`, and `qa_out_path` | These render logs are not generic status lines. They embed absolute output and workspace paths inside a machine-readable live-log surface. That is local machine data and can also reveal project layout when stderr is captured by wrappers or support tooling. | `conditional leak` | Yes. Render paths and live progress on render flows are protected. |
| `tools/smoke_packaged_desktop.py` | `656-700`, `1064-1086`, `2400-2479` | JSON stdout, failure exceptions, and receipt helpers | Installer path, install log path, install root, installed sidecar paths, launched app path, temp root, full launched stdout or stderr, and install log tail | This is a real support and release path. On success it prints path-rich JSON. On failure it also includes raw installer stdout, stderr, and log tails. Those values can include machine-specific paths and other environment details. | `active leak` | Yes. Packaged smoke and installer tooling are protected support paths. |
| `.github/workflows/release.yml` | `526-529` | `Write-Host` in the Windows install verification step | Installed artifact path, installer log path, and detected install root | These values go straight into CI logs on a protected release path. They are machine-specific filesystem details. The workflow does not need the full paths in console output to verify signatures. | `active leak` | Yes. Release tooling and CI control-plane paths are protected. |
| `tools/agent/run.py`, `tools/agent/trace.py`, `tools/agent/contract_stamp.py` | `run.py:640-654`, `1128-1145`; `trace.py:46-58`; `contract_stamp.py:66-79`, `197-203` | persistent NDJSON trace file and contract-stamp JSON | Absolute repo root, stamp path, trace path, and other path-bearing fields supplied through trace events | This is not a server log, but it is a persistent trace artifact. If an operator shares `sandbox_tmp/agent_trace.ndjson` or `.mmo_agent/graph_contract.json`, the files expose machine-local repo paths and other local artifact locations. | `conditional leak` | No. This is a local support tool, not a protected runtime path. |
| `src/mmo/cli_commands/_project.py`, `src/mmo/core/config.py` | `_project.py:233-284`, `589-660`; `config.py:235-258`, `303-309`, `380-386` | machine-readable CLI JSON stdout | `project show` prints `project_dir` and per-artifact `absolute_path`. `project save` and `project load` print `project_dir`, `session_path`, `scene_path`, and written path summaries. | These are intended product outputs, not hidden telemetry, but they are still sensitive when shell history, CI logs, or support captures stdout. The payloads expose project and session filesystem structure directly. | `conditional leak` | Yes. Project and session control-plane paths can alter local project state. |
| `src/mmo/tools/scan_session.py`, `src/mmo/core/session.py`, `src/mmo/core/media_tags.py` | `scan_session.py:1548-1556`, `1656-1663`; `session.py:44-67`, `109-112`; `media_tags.py:261-267` | machine-readable CLI JSON stdout | Full report JSON including `session.stems_dir`, per-stem `file_path`, `sha256`, and `source_metadata.tags` derived from media metadata | This output can carry private creative-data context, including local stem paths, stable hashes, and embedded media tags. The command is local and explicit, but it becomes a leak when stdout is routed into shared logs or support transcripts. | `conditional leak` | No for the scan command itself, but the data class is high risk. |

## Approval status

Protected findings require approval before edits.

| Finding | Approval required | Path class | Smallest safe edit after approval | Verification after edit |
| --- | --- | --- | --- | --- |
| Safe-render live progress path logging in `_renderers.py` | Yes | runtime | Replace absolute `where` path entries with artifact labels or project-relative identifiers when a stable local path is not essential. | `tools/run_pytest.sh -q tests/test_cli_safe_render.py tests/test_safe_render_live_progress.py` or the nearest existing live-progress coverage, plus `python3 tools/validate_contracts.py`. |
| Packaged smoke receipt and JSON output in `tools/smoke_packaged_desktop.py` | Yes | support | Keep the smoke verdict and artifact kind, but replace absolute paths with basenames or short labels and replace raw stdout, stderr, and log tails with bounded status summaries. Leave full logs on disk only when a human opts in. | `python3 -m py_compile tools/smoke_packaged_desktop.py`, `python3 tools/validate_contracts.py`, and the nearest smoke-tool tests under `tests/test_packaged_desktop_smoke.py` and `tests/test_packaged_smoke_goldens.py`. |
| Windows install path echoes in `.github/workflows/release.yml` | Yes | control-plane | Stop echoing full install paths. Keep only installer kind, success state, and signature status in console output. | Dry review of workflow output shape plus the existing packaged smoke and release validation jobs. |
| Project CLI JSON output in `_project.py` | Yes | runtime | If later approved, split machine-readable local output from shared-log-safe output, or move absolute paths behind an explicit flag. | `tools/run_pytest.sh -q tests/test_cli_project_load_save.py tests/test_cli_project_show.py` if present, plus `python3 tools/validate_contracts.py`. |

The non-protected `tools/agent/*` trace and stamp finding does not require
approval by policy, but it still changes an artifact contract, so it should be
handled as a narrow follow-up instead of being bundled into this audit pass.

## Safe patterns for this repo

- Log stage names, issue IDs, and counts, not full report or session payloads.
- Prefer artifact labels like `render_report.json` over absolute workspace
  paths.
- In GUI bridge errors, surface exit code and `stderr_present`, not raw
  subprocess stderr.
- Keep `[MMO-LIVE]` `where` values on stable IDs or relative labels, not
  machine-local paths.
- Do not print `render_execute.json`, `event_log.jsonl`, or project session
  payloads into CI or support logs.
- Treat stem paths, media tags, render receipts, and compare artifacts as
  sensitive creative data by default.
- Keep installer logs, launch stdout, and launch stderr on disk for local
  debugging. Do not copy them wholesale into workflow console output.
- Never echo secrets, passwords, tokens, cookies, cert material, or signed URLs
  in workflows. Passing them through environment variables is not the same as
  logging them.
- Use allowlists for structured log fields. Do not forward whole objects from
  CLI JSON, installer receipts, or subprocess errors.
- If a machine-readable CLI output is needed for automation, document that it
  is product output and avoid piping it into shared logs by default.

## High-risk domain data note

This repo handles high-risk creative and local-environment data even though it
is not a health or finance product.

High-risk data present in audited output surfaces:

- local stems directories and per-stem paths
- media tags carried in `source_metadata.tags`
- render artifact and workspace paths
- event-log and receipt paths
- machine-local install roots and temp roots

No first-party analytics SDK or crash reporter was found in the audited code.
The main exposure is local status output, persistent traces, release logs, and
machine-readable CLI JSON that can be copied into logs.

## Unknowns and follow-up

See also [docs/unknowns/logging-audit.md](../unknowns/logging-audit.md).

| Area or file | Concern | Why it matters | Evidence found so far | Likely owner if known | Next best check | Risk level |
| --- | --- | --- | --- | --- | --- | --- |
| `gui/lib/mmo_cli_runner.mjs`, `gui/lib/rpc_process_client.mjs` | The new GUI bridge summaries still need one end-to-end runtime spot-check | The code now surfaces public candidate labels, exit or error summaries, and `stderr_present` or `stderr_lines` counts instead of raw stderr text. A failing dev-shell run should still confirm the browser never reintroduces raw subprocess text elsewhere in the stack. | Static review shows the bridge now emits allowlisted summaries, and `cd gui && npm test` covers the new redacted contract in `gui/tests/mmo_cli_runner.test.mjs` and `gui/tests/rpc_process_client.test.mjs` | GUI bridge | Run one failing render or project command in the dev shell and inspect the surfaced error text end to end | `needs runtime confirmation` |
| `tools/smoke_packaged_desktop.py` and release workflow logs | Windows installer stdout, stderr, and log tails may contain more than paths | Static review shows full installer output is retained and printed, but the exact MSI or NSIS payload depends on the installer and runner state | The harness writes `stdout`, `stderr`, and `log_tail` into failures and path-rich JSON into success output | desktop packaging or release tooling | Run the packaged smoke harness on Windows and inspect the emitted console output and `msi-install.log` or `nsis-install.log` | `needs runtime confirmation` |
| `tools/agent/*` trace artifacts | It is unclear whether any automation publishes `sandbox_tmp/agent_trace.ndjson` or `.mmo_agent/graph_contract.json` outside local runs | Local-only artifacts are lower risk until they are uploaded, pasted, or attached to CI or issue threads | Static review found no workflow that uploads these files, but the tool writes them by default with path-bearing fields | agent harness | Confirm whether any manual or automated workflow exports these artifacts to shared locations | `needs runtime confirmation` |

## Coverage note

Covered in this pass:

- first-party Python `print` and stderr surfaces in CLI and support tools
- first-party Node `console.*` and subprocess stderr forwarding in the GUI and
  desktop helper layers
- persistent local trace or receipt artifacts under `tools/agent/`
- packaged smoke and Windows installer diagnostics
- GitHub workflow console output in release paths

Sampled but not elevated:

- build and validation scripts that only print artifact names, counts, or
  validator status
- GUI bridge failure summaries that now expose public candidate labels, exit or
  error summaries, and `stderr_present` or `stderr_lines` counts instead of raw
  subprocess stderr
- GUI server startup logging that only prints the localhost dev-shell URL
- scan-session live progress logs that use `stem_id` or `session` markers
  instead of raw paths
- workflow secret handling that passes signing inputs through environment
  variables without echoing their values

Still worth a later audit if scope expands:

- platform-native logs outside repo-owned code
- any out-of-repo CI artifact retention or support transcript process
- future Tauri-native logging additions
