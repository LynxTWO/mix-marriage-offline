# Logging Audit Unknowns

<!-- markdownlint-disable-file MD013 -->

This file records runtime questions from the logging, telemetry, and sensitive
data audit. Add entries here instead of guessing when code clearly forwards
stderr, logs, or trace artifacts but the exact payload depends on runtime
conditions.

| Area or file | Concern | Why it matters | Evidence found so far | Likely owner if known | Next best check | Risk level |
| --- | --- | --- | --- | --- | --- | --- |
| `gui/lib/mmo_cli_runner.mjs`, `gui/lib/rpc_process_client.mjs` | The worst-case stderr payloads are not known from code alone | Both helpers forward raw stderr text into GUI-visible error paths. A failing command can include absolute paths, artifact locations, or other local context. | `runMmoCli()` appends full trimmed stderr to failure summaries, and `RpcProcessClient` appends the last five stderr lines to close errors. | GUI bridge | Run failing `project.show`, `project.render_run`, and `gui rpc` calls against a path-rich project and capture the exact surfaced error text. | `needs runtime confirmation` |
| `tools/smoke_packaged_desktop.py` | Windows installer stdout, stderr, and log tails may include more than path data | The smoke harness prints full installer output on failure and path-rich JSON on success. The exact data class depends on MSI or NSIS behavior and the built app. | Static review found `_windows_install_receipt()`, `_run_windows_installer()`, and the result JSON all forward raw installer output or full paths. | desktop packaging or release tooling | Run the Windows packaged smoke flow and inspect both success and failure output, including `msi-install.log` and `nsis-install.log`. | `needs runtime confirmation` |
| `tools/agent/*` | It is not confirmed whether path-bearing trace artifacts are ever shared outside local runs | The trace and contract-stamp files persist local paths. That is low risk locally, but it becomes a real leak if shared in CI artifacts, issue attachments, or support transcripts. | Static review found default writes to `sandbox_tmp/agent_trace.ndjson` and `.mmo_agent/graph_contract.json`, but no workflow upload was found in this repo. | agent harness | Confirm whether any manual or automated workflow exports or uploads these artifacts. | `needs runtime confirmation` |
