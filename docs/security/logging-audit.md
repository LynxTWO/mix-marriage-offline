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
| `tools/smoke_packaged_desktop.py` | `656-751`, `1064-1084`, `2226-2478` | JSON stdout, cleanup stdout, failure exceptions, and receipt helpers | Artifact labels, installer kind, signature or cleanup status, bounded stdout or stderr line counts, and on-disk install-state or log presence. The full path-bearing install-state JSON and installer logs still stay on disk. | This is still a protected support path, but the shared console copy is now narrower. The remaining risk is local install-state and installer-log artifacts if a maintainer later shares them outside the machine that created them. | `conditional leak` | Yes. Packaged smoke and installer tooling are protected support paths. |
| `tools/agent/run.py`, `tools/agent/trace.py`, `tools/agent/contract_stamp.py` | `run.py:640-654`, `1128-1145`; `trace.py:46-58`; `contract_stamp.py:66-79`, `197-203` | persistent NDJSON trace file and contract-stamp JSON | Absolute repo root, stamp path, trace path, and other path-bearing fields supplied through trace events | This is not a server log, but it is a persistent trace artifact. If an operator shares `sandbox_tmp/agent_trace.ndjson` or `.mmo_agent/graph_contract.json`, the files expose machine-local repo paths and other local artifact locations. | `conditional leak` | No. This is a local support tool, not a protected runtime path. |
| `src/mmo/cli_commands/_project.py`, `src/mmo/core/config.py` | `_project.py:233-375`, `665-791`; `config.py:238-314`, `317-389` | machine-readable CLI JSON stdout | Shell-facing `project show`, `project save`, and `project load` now default to shared-safe JSON. Explicit `--format json` and RPC `json` still print `project_dir`, `absolute_path`, `session_path`, `scene_path`, and written path summaries when local tooling needs them. | These are intended product outputs, not hidden telemetry, but they are still sensitive when shell history, CI logs, or support captures stdout. The shell-facing boundary is now narrower for the project commands, but the explicit local `json` path and the wider scan output still expose project and session filesystem structure directly. | `conditional leak` | Yes. Project and session control-plane paths can alter local project state. |
| `src/mmo/tools/scan_session.py`, `src/mmo/core/session.py`, `src/mmo/core/media_tags.py` | `scan_session.py:1309-1387`, `1548-1569`, `1617-1674`; `session.py:44-67`, `109-112`; `media_tags.py:261-267` | machine-readable CLI JSON stdout | Shell-facing scan stdout now defaults to a shared-safe profile that drops `session.stems_dir`, per-stem `sha256`, `source_metadata`, `resolved_path`, `resolve_error_detail`, and file-hash evidence. Explicit `--format json` and file-backed `--out` still keep the full local report including `session.stems_dir`, per-stem `file_path`, `sha256`, and media-tag-derived content. | This output still carries private creative-data context when local tooling chooses the full report contract, but the shell-facing default is now narrower for issue threads and shared logs. The remaining risk sits in explicit local `json`, file-backed receipts, and any shared handling of those outputs outside the repo. | `conditional leak` | No for the scan command itself, but the data class is high risk. |

## Approval status

Protected findings require approval before edits.

| Finding | Approval required | Path class | Smallest safe edit after approval | Verification after edit |
| --- | --- | --- | --- | --- |
| Safe-render live progress path logging in `_renderers.py` | Yes | runtime | Implemented on this branch. `safe-render --live-progress` now keeps `where` on target IDs, stable labels, and workspace-relative refs instead of absolute paths. | `tools/run_pytest.sh -q tests/test_cli_safe_render.py -k "live_progress or cancel_file_stops_safe_render_with_exit_130"`, `python3 tools/validate_contracts.py`, one local dry-run `safe-render --live-progress` stderr sample, and one local full-render `safe-render --live-progress` stderr sample. |
| Packaged smoke receipt and JSON output in `tools/smoke_packaged_desktop.py`, plus Windows release console output in `.github/workflows/release.yml` | Yes | support and control-plane | Implemented on this branch. Packaged smoke now prints artifact labels, installer kind, and bounded status summaries instead of raw paths, log tails, and launch streams. The Windows release workflow now logs basename-only labels and signature status instead of full install paths. | `python3 -m py_compile tools/smoke_packaged_desktop.py`, `tools/run_pytest.sh -q tests/test_packaged_desktop_smoke.py tests/test_packaged_smoke_goldens.py`, `python3 tools/validate_contracts.py`, and dry review of the workflow diff for console-output shape. |
| Project CLI JSON output in `_project.py` and scan CLI JSON output in `scan_session.py` | Yes | runtime | Phases 1 through 5 are implemented on this branch: `project show`, `project save`, `project load`, and `scan_session` all have shared-safe shell modes or defaults, while RPC and explicit `json` keep the local contracts unchanged. Remaining work is a later decision about the explicit local `json` and file-backed scan paths, not the shell-facing defaults. | `tools/run_pytest.sh -q tests/test_cli_project_show.py tests/test_cli_project_load_save.py tests/test_cli_gui_rpc.py tests/test_scan_smoke.py tests/test_validation_wav_codec.py tests/test_scan_ffmpeg_basic.py tests/test_scan_ffprobe_layout.py tests/test_scan_truth_weighting_multiformat.py tests/test_truth_meters_optional_deps.py tests/test_cli_scan_lfe_audit.py tests/test_cli_project_build_gui.py`, plus `python3 tools/validate_contracts.py`. |

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
- `project show` now defaults to the shared-safe shell profile. Use
  `--format json` only when local tooling needs the full GUI or RPC path
  contract.
- `project save` and `project load` now default to the shared-safe profile for
  shell use. Use `--format json` only when local tooling truly needs the full
  machine-local path contract.
- `scan_session` and `mmo scan` now default shell stdout to the shared-safe
  profile. Use `--format json` only when local tooling needs the full local
  report, and use `--out` when a later stage needs the full file-backed
  artifact.

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
