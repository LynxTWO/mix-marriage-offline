# MMO System Map

This file is the repo inventory companion to
[../02-architecture.md](../02-architecture.md). Use `02-architecture.md` for
shipped product behavior and scene/render rules. Use this map for runtime
units, entrypoints, on-disk state, configuration inputs, and trust boundaries.

## 1. System summary

| Topic | Notes |
| --- | --- |
| Repo type | Offline Python application with a packaged Tauri desktop app, a local web dev shell, packaged schemas and ontology data, and release tooling. |
| Main runtime model | Users drive workflows through the `mmo` CLI, a frozen CLI binary, or the shipped Tauri desktop shell. Those paths write deterministic JSON and YAML artifacts into local project or workspace directories. |
| Main data stores | No confirmed SQL, NoSQL, cache service, or object-store backend. Runtime state lives in local files: project and session JSON, render artifacts, compare artifacts, scene locks, cached plugin-market snapshots, repo-local or OS cache/temp roots, and packaged data under `schemas/`, `ontology/`, and `src/mmo/data/`. |
| Main external dependencies | Local `ffmpeg` and `ffprobe`, OS filesystem and subprocess behavior, Tauri shell and WebView, Node/Vite/Playwright for dev and test, Rust/Tauri packaging, GitHub Actions, and GitHub Pages. |
| Main high-risk domains | Render mutation, fallback audio behavior, plugin authority and install roots, filesystem writes and deletes, packaged data resolution, local path handling, and sidecar packaging or release signing. |
| Explicit absences | No confirmed runtime SaaS API, no database, no message broker, no Docker/Kubernetes/Terraform/Helm deployment stack, and no checked-in `.env.example`. |

## 2. Runtime units and entrypoints

### Product and runtime units

| Runtime unit | Where it lives | How it starts | Triggered by | Depends on | Data or side effects it owns |
| --- | --- | --- | --- | --- | --- |
| `mmo` CLI | `src/mmo/cli.py`, `pyproject.toml` console script | `mmo ...` or `python -m mmo ...` | Local users, scripts, repo tools, GUI helpers | Python package, packaged data, schemas, ontology, optional `ffmpeg` or `ffprobe` | Reads stems and project inputs. Writes reports, scene and render artifacts, compare outputs, plugin metadata, and project files. |
| Frozen CLI and release binary entrypoint | `src/mmo/_frozen_cli_entrypoint.py`, `tools/build_binaries.py` | Standalone CLI binary or packaged sidecar launch | End-user CLI installs, Tauri sidecar boot, smoke harnesses | Bundled Python runtime, packaged data, local tools | Same artifact and filesystem effects as the CLI, but from a packaged executable. |
| Tauri desktop app | `gui/desktop-tauri/`, `gui/desktop-tauri/src-tauri/` | Packaged desktop app or `npm run tauri dev` | Local desktop users | Bundled sidecar `binaries/mmo`, Tauri plugins, local artifact files | Owns desktop UI state, file picking, stage orchestration, and smoke-only Tauri command exposure. |
| GUI RPC subprocess | `src/mmo/cli_commands/_gui_rpc.py` | `mmo gui rpc` | Local dev shell or another local client | CLI project helpers, plugin-market helpers, scene-lock helpers | Replies over JSON lines. Reads and writes project files, plugin cache files, and scene locks depending on method. |
| Local web dev shell | `gui/server.mjs`, `gui/lib/*.mjs`, `gui/web/` | `cd gui && npm run dev` or `node server.mjs` | Browser requests during local development | Node HTTP server, static assets, CLI runner, RPC subprocess | Serves local UI assets, proxies RPC calls, reads allowlisted artifacts, and streams audio pointers from local render outputs. Not a shipped product surface. |
| Watch-folder automation | `src/mmo/core/watch_folder.py`, CLI `watch` command | `mmo watch ...` | Polling a local watch directory | Stem discovery, target resolution, CLI subprocess execution | Tracks changed stem sets, maintains a local queue snapshot, and launches render batches into local output folders. |

### Operational and developer units

| Unit | Where it lives | How it starts | Purpose | Side effects |
| --- | --- | --- | --- | --- |
| Validation and build tools | `tools/` | Direct Python or shell invocation, CI jobs | Validate contracts and policies, build docs, build binaries, prepare Tauri sidecar, run fixtures | Read repo state, write build outputs under `dist/`, `sandbox_tmp/`, screenshot dirs, or temp roots |
| Packaged desktop smoke harness | `tools/smoke_packaged_desktop.py` | CI or local operator run | Launch built bundles, verify the packaged app and bundled sidecar on a clean temp root | Installs or launches desktop bundles, writes smoke summaries and temp workspace artifacts |
| GitHub Actions CI, release, and docs deployment | `.github/workflows/ci.yml`, `release.yml`, `policy-validation.yml`, `pages.yml` | GitHub events or manual dispatch | Cross-platform validation, packaging, release artifact upload, Pages deploy | Publishes build artifacts, optional Windows signing setup, and `site/` deployment to GitHub Pages |

## 3. Interface surface

### CLI command families

Grouped from `src/mmo/cli.py`. This section lists the human-facing entry surface
without repeating every parser line.

| Command family | Trigger | What it does | Auth or special privilege | Reads and writes | Downstream systems touched |
| --- | --- | --- | --- | --- | --- |
| `scan`, `analyze`, `run` | `mmo scan ...`, `mmo analyze ...`, `mmo run ...` | Intake stems, run the analysis pipeline, and optionally export or render in one pass | Local-only. Needs filesystem access to stems and output paths. | Reads stems and optional config. Writes `report.json`, `report.scan.json`, exports, and optional UI bundle outputs. | Filesystem, schemas, ontology, DSP backends, optional `ffmpeg` or `ffprobe`, plugin pipeline |
| `stems *` | `mmo stems scan|sets|classify|bus-plan|pipeline|draft|audition ...` | Discover stem sets, classify roles, build bus plans, manage overrides, create draft scene artifacts, and make audition packs | Local-only. Some commands write classification or audition outputs. | Reads stems, overrides, and policy data. Writes `stems_map.json`, `bus_plan.json`, review outputs, and audition artifacts. | Filesystem, ontology, presets, plugin registry data |
| `scene *` | `mmo scene build|show|validate|lint|locks ...` | Build and inspect `scene.json`, manage intent fields, apply templates, and save lock selections | Local-only. Writes scene and lock artifacts in the chosen workspace or project. | Reads stems maps, bus plans, scene templates, and lock ontology. Writes `scene.json`, `scene_lint.json`, and `scene_locks.yaml`. | Filesystem, ontology, schema validation |
| `render *`, `render-plan *`, `render-request *`, `render-report`, `render-compat`, `safe-render`, `apply` | `mmo render ...`, `mmo render-plan ...`, `mmo render-request template`, `mmo safe-render ...` | Build render requests and plans, execute render stages, emit QA and receipts, and inspect render compatibility | Local-only. High-risk because it can change audio outputs and write many artifacts. | Reads scene and report inputs. Writes `render_request.json`, `render_plan.json`, `render_report.json`, `render_execute.json`, `render_manifest.json`, `safe_render_receipt.json`, `render_qa.json`, and audio outputs. | Filesystem, DSP renderers, `ffmpeg`, `ffprobe`, plugin execution |
| `project *` | `mmo project new|init|show|save|load|validate|build-gui|render-run|pack ...` | Create and validate project scaffolds, persist or reload sessions, bundle GUI payloads, and drive render runs from a project root | Local-only. Writes project state and packaged zip outputs. | Reads project directories, sessions, reports, and render artifacts. Writes `.mmo_project.json`, session JSON, `ui_bundle.json`, `renders/*`, and pack archives. | Filesystem, schema validation, render pipeline, plugin metadata, GUI bundle generation |
| `watch` | `mmo watch ...` | Poll a watch folder, detect changed stem sets, and queue CLI render batches | Local-only. Long-running process with filesystem and subprocess access. | Reads watch directory contents. Writes queue snapshots to stdout and batch output directories. | Filesystem, subprocess launch of CLI flows |
| `compare`, `review` | `mmo compare ...`, `mmo review ...` | Compare analysis or render artifacts and produce review-friendly reports | Local-only. Reads existing artifacts and writes compare outputs. | Reads `report.json`, `render_qa.json`, and workspace paths. Writes `compare_report.json` and review text or JSON. | Filesystem, compare logic |
| `bundle`, `ui`, `ui-layout-snapshot` | `mmo bundle ...`, `mmo ui ...`, `mmo ui-layout-snapshot ...` | Build UI pointer payloads and inspect UI-facing plugin or artifact metadata | Local-only. Writes UI bundle outputs. | Reads report, project, plugin, and layout files. Writes `ui_bundle.json` and layout snapshot outputs when requested. | Filesystem, plugin metadata, GUI asset preparation |
| `variants *`, `deliverables index` | `mmo variants run|listen-pack ...`, `mmo deliverables index ...` | Run mix-once or render-many workflows and summarize deliverables for listening or export | Local-only. Writes many variant outputs. | Reads variant plans, render plans, and project artifacts. Writes variant workspaces, `listen_pack.json`, and `deliverables_index.json`. | Filesystem, render pipeline, compare and delivery helpers |
| `translation *`, `downmix *`, `routing show`, `timeline *` | `mmo translation ...`, `mmo downmix ...`, `mmo routing show`, `mmo timeline ...` | Run translation checks, render translation auditions, inspect routing, run downmix QA, and validate timelines | Local-only. Some commands emit QA and render outputs. | Reads reports, scenes, timelines, and render artifacts. Writes translation check outputs, audition files, and downmix QA data. | Filesystem, DSP backends, render target registries |
| `plugin *` | `mmo plugin list|update|install ...` | Browse the offline plugin market, refresh the cached market snapshot, and install a market entry into an external plugin root | Local-only. Writes plugin snapshot cache and installed plugin files. | Reads packaged or cached plugin market index and plugin roots. Writes cache snapshot JSON and copied plugin manifests or modules. | Filesystem, cache dir, plugin marketplace index |
| `plugins *` | `mmo plugins list|validate|show|self-test|ui-lint ...` | Validate plugin manifests, inspect plugin details, and lint or self-test plugin surfaces | Local-only. Validation can fail the run but does not require network auth. | Reads repo, packaged, or external plugin roots. Writes lint outputs only when requested. | Filesystem, schema validation, dynamic plugin import paths |
| `env doctor`, `gui rpc`, `gui-state`, `event-log` | `mmo env doctor`, `mmo gui rpc`, `mmo gui-state ...`, `mmo event-log ...` | Report environment health, run the JSON-line RPC server, validate GUI state, and validate demo event logs | Local-only. `gui rpc` exposes a long-lived local process surface. | Reads env vars, tool paths, GUI state payloads, and event logs. Writes JSON responses or validation outputs. | Filesystem, local subprocess clients, tool discovery |
| Registry and operator support surfaces | `mmo presets ...`, `targets ...`, `roles ...`, `gates ...`, `locks ...`, `lock ...`, `help ...`, `ontology validate`, `role-lexicon merge`, `ui-hints ...`, `ui-copy ...`, `ui-examples ...` | Inspect registries, help text, locks, UI hints, copied text, and ontology-driven support data | Local-only. Usually read-only, except merge or write helpers. | Reads ontology, schema, copied UI assets, and lockfiles. Writes merged lexicon or lock outputs when requested. | Filesystem, ontology, schemas, copied UI content |

### GUI RPC methods

Grouped from `src/mmo/cli_commands/_gui_rpc.py`.

| RPC method | What it does | Reads and writes | Privilege notes |
| --- | --- | --- | --- |
| `rpc.discover` | Returns the RPC method inventory, version, and parameter shapes | Reads only in-process metadata | Local process trust only |
| `env.doctor` | Builds the environment doctor payload used by the GUI | Reads env vars, path resolution, and tool availability | No network auth. Relies on local process environment. |
| `project.show` | Returns project scaffold details and artifact pointers | Reads project files and discovered artifact paths | Local project read access required |
| `project.validate` | Validates the project scaffold and nested artifact references | Reads project files and schema-backed artifacts | Local-only validation surface |
| `project.save` | Saves a project session payload | Reads project state. Writes session JSON. | Local write access to chosen session path |
| `project.load` | Loads a saved session back into a project | Reads session JSON. Writes project state files. | Local write access to chosen project |
| `project.build_gui` | Builds a GUI bundle and optional plugin payloads for a project | Reads project and plugin data. Writes pack or bundle outputs and optional scan artifacts. | Local write access. Can trigger scan and bundle steps. |
| `project.write_render_request` | Writes or edits allowlisted fields in `renders/render_request.json` | Reads project state. Writes render-request artifact. | Local write access to project renders dir |
| `project.render_run` | Executes project render stages and optional preflight, QA, or event logging | Reads project and render inputs. Writes `renders/*` outputs. | High-risk local side effects because it can trigger rendering and audio writes |
| `project.pack` | Builds a zip payload from a project root | Reads project files. Writes a pack archive. | Local archive write access required |
| `plugin.market.list` | Builds the offline plugin-market payload | Reads packaged index, cache snapshot, and installed plugin roots | Read-only, but reveals local plugin state |
| `plugin.market.update` | Refreshes the cached offline plugin-market snapshot | Reads packaged index. Writes snapshot JSON under the cache dir. | Local cache write access required |
| `plugin.market.install` | Installs one marketplace entry into an external plugin root | Reads market index and bundled plugin source files. Writes manifest and module files into a plugin dir. | Local write access to plugin root. No network auth. |
| `scene.locks.inspect` | Reads current scene-lock state and available lock definitions | Reads scene files, lock ontology, and project scaffold | Read-only |
| `scene.locks.save` | Saves scene-lock selections and rewrites the draft scene as needed | Reads project and lock metadata. Writes `scene_locks.yaml` and updated scene draft output. | Local write access to project workspace |

### Local dev-shell HTTP endpoints

Grouped from `gui/server.mjs`.

| Method and path | What it does | Reads or writes | Trust notes |
| --- | --- | --- | --- |
| `GET` or `HEAD` `/` and static asset paths | Serves the local dev UI and module assets from `gui/web/` and `gui/lib/` | Reads static files only | Local dev surface only. Not shipped inside the packaged desktop app. |
| `POST /api/rpc` | Proxies a method call to the local `mmo gui rpc` subprocess and returns the JSON reply | Reads request JSON. Side effects depend on the RPC method invoked. | No auth layer. Trust is the local browser talking to a local process. |
| `POST /api/ui-bundle` | Reads an existing `ui_bundle.json`, enriches plugin entries, and returns an expanded payload | Reads `ui_bundle.json`, plugin manifests, layout docs, and optional snapshot assets | Allowlisted file reads only. No writes in this handler. |
| `POST /api/render-request` | Reads an allowlisted `renders/render_request.json` and returns it as JSON | Reads one render-request file | Path must resolve to `renders/render_request.json`. No writes. |
| `POST /api/render-artifact` | Reads an allowlisted render artifact such as `render_execute.json`, `render_plan.json`, `render_report.json`, or `event_log.jsonl` | Reads one allowlisted artifact file | No writes. Path is rejected unless it matches the allowlist under `renders/`. |
| `GET` or `HEAD /api/audio-stream` | Streams audio pointers referenced by `renders/render_execute.json` | Reads `render_execute.json` and the selected audio file. No writes. | Rejects paths outside the project dir or project outputs unless `MMO_GUI_ALLOW_EXTERNAL_OUTPUT_PATHS=1` is set. |

### Tauri-side interfaces

| Interface | Source | Notes |
| --- | --- | --- |
| Bundled sidecar executable | `gui/desktop-tauri/src-tauri/tauri.conf.json`, `gui/desktop-tauri/src/mmo-sidecar.ts` | The shipped desktop app launches `binaries/mmo` as a local sidecar. Desktop stages drive local artifact files and subprocess calls, not a network API. |
| Tauri command `desktop_smoke_config` | `gui/desktop-tauri/src-tauri/src/lib.rs` | Smoke-only command that exposes `MMO_DESKTOP_SMOKE_*` inputs to packaged smoke tests. |
| Desktop frontend screens | `gui/desktop-tauri/index.html`, `docs/11-gui-vision.md`, `gui/desktop-tauri/README.md` | The shipped path covers `Doctor -> Validate -> Analyze -> Scene -> Render -> Results -> Compare`. The docs explicitly say the packaged app does not launch the old Node dev server. |
| Dev-only browser frontend URL | `gui/desktop-tauri/src-tauri/tauri.conf.json` | `devUrl` points to `http://localhost:1420` during local development only. Packaged builds use `../dist`. |

## 4. Data stores and schemas

MMO is artifact-first. The runtime stores state in local files instead of a
database.

| Store or schema surface | What it stores | Key files or entities | Retention or deletion notes | Non-obvious usage |
| --- | --- | --- | --- | --- |
| Packaged registries and contracts | Canonical schema, ontology, preset, and packaged plugin data | `schemas/`, `ontology/`, mirrored packaged data under `src/mmo/data/` | Packaged with the wheel or app. Replaced by reinstall or release upgrade, not by runtime mutation. | `src/mmo/resources.py` can resolve from `MMO_DATA_ROOT`, packaged data, or a repo checkout. That makes contract authority a trust boundary. |
| Project scaffold and session state | Project metadata, session persistence, project validation, scene locks, and lockfiles | `.mmo_project.json`, session JSON, `project/validation.json`, `scene_locks.yaml`, lock or timeline files referenced by project commands | Persists until a user removes or overwrites it. No global retention policy found in code. | The project scaffold describes nested artifact locations, but later scene and render artifacts can also live at workspace-root paths outside the nested project folder. |
| Analysis artifacts | Intake and role-classification outputs | `report.json`, `report.scan.json`, `stems_map.json`, `bus_plan.json`, optional CSV summaries | Persist in the chosen workspace until removed | `stems_map.json` answers role mapping. `bus_plan.json` answers deterministic routing. They are related but not interchangeable. |
| Scene and render planning artifacts | Intent metadata and render job planning | `scene.json`, `scene_lint.json`, `render_request.json`, `render_plan.json`, `render_report.json` | Persist until overwritten or deleted by the operator | `scene.json` is intent metadata, not rendered audio. The dev shell and desktop UI both consume pointers into these artifacts. |
| Render execution and audit artifacts | Executed jobs, receipts, QA results, deliverable summaries, and UI bundle pointers | `render_execute.json`, `render_manifest.json`, `safe_render_receipt.json`, `render_qa.json`, `compare_report.json`, `deliverables_index.json`, `listen_pack.json`, `ui_bundle.json`, `event_log.jsonl` | Persist until removed. Some flows rebuild them in place when `--force` is used. | `render_execute.json` also drives dev-shell audio streaming. `compare_report.json` can carry `loudness_match` context when paired `render_qa.json` files exist. |
| Plugin stores | Built-in manifests, repo checkout plugins, user-installed plugins, and cached offline market snapshot | `plugins/`, `src/mmo/data/plugins/`, `examples/plugin_authoring/`, user plugin dir from `default_user_plugins_dir()`, cache snapshot `plugin_index.snapshot.json`, packaged market assets under `src/mmo/data/plugin_market/assets/plugins/` | User installs and cache snapshots persist until removed or replaced | Runtime plugin root order is primary `--plugins`, external `--plugin-dir` or `MMO_PLUGIN_DIR` or default user dir, then built-in packaged fallback. |
| Cache and temp roots | Snapshot caches, temporary files, repo-local temp roots, and smoke temp data | `.mmo_cache`, `.mmo_tmp`, OS cache roots, OS temp roots, smoke harness temp dirs | Cache and temp data can be recreated. Cleanup is local or test-driven; no scheduled cleanup service was found. | `src/mmo/resources.py` prefers repo-local cache or temp roots in checkout mode, then falls back to OS locations. |

## 5. External dependencies

The shipped product path is offline-first. No confirmed runtime SaaS or network
API dependency was found in the application workflow.

### Runtime dependencies

| External system | Why MMO uses it | How it is configured | Runtime units that depend on it | What breaks if it is down | Retry or fallback behavior confirmed in code |
| --- | --- | --- | --- | --- | --- |
| `ffmpeg` | Decode, transcode, and some render or QA paths | PATH lookup or `MMO_FFMPEG_PATH` | CLI, sidecar, render, downmix QA, smoke harness | Non-WAV decode and some render or export paths fail | Explicit env override supported. No general runtime retry loop found. |
| `ffprobe` | Read media metadata and layout info | PATH lookup or `MMO_FFPROBE_PATH` | CLI, sidecar, env doctor, QA, metadata checks | Metadata and layout inspection fail | Explicit env override supported. No general runtime retry loop found. |
| OS filesystem | Source of stems, project dirs, plugin roots, caches, and render outputs | User-chosen paths plus env overrides | All runtime units | Core workflow stops because MMO is artifact-first | Validation and allowlists reject some bad paths, but there is no alternative backing store. |
| Local process spawning | Runs sidecar processes, CLI helpers, and tool discovery | Direct subprocess invocation | Dev shell, Tauri sidecar orchestration, watch-folder automation, smoke harness | RPC, watch-folder batches, or sidecar launches fail | CLI runner falls back from `mmo` to `python -m mmo` in the local dev shell. |
| Tauri shell and WebView | Packaged desktop shell for the shipped app | `gui/desktop-tauri/src-tauri/tauri.conf.json` and Rust/Tauri build chain | Tauri desktop app | Desktop app cannot launch or render UI | No alternate packaged GUI path exists. Docs say Tauri is the only shipped desktop app. |

### Build, test, and release dependencies

| External system | Why MMO uses it | How it is configured | Who depends on it | What breaks if it is down |
| --- | --- | --- | --- | --- |
| Node 24, npm, Vite, local frontend deps | Build the dev shell and desktop frontend assets | `gui/package.json`, `gui/desktop-tauri/package.json` | GUI dev, Tauri frontend builds, GUI tests | Dev shell and desktop frontend builds fail |
| Playwright | GUI and screenshot automation | `gui/desktop-tauri/tests/`, CI install steps | Screenshot capture and desktop UI tests | Screenshot regeneration and browser-based tests fail |
| Rust 1.94 and Cargo/Tauri toolchain | Build the desktop shell and sidecar integration layer | `gui/desktop-tauri/src-tauri/Cargo.toml`, Tauri workflows | Desktop packaging and smoke flows | Tauri bundles cannot be produced |
| GitHub Actions | Cross-platform validation, packaging, release, smoke, docs deploy | `.github/workflows/*.yml` | CI, release, pages | Automated validation, packaging, and publication stop |
| GitHub Pages | Hosts `site/` output | `.github/workflows/pages.yml` | Docs site deploy | Site deployment stops |
| Windows signing certificate and timestamp service | Optional code signing for Windows release bundles | GitHub secrets and release workflow env | Windows release packaging | Signed Windows builds are skipped or fail if signing is required |

## 6. Secrets and configuration

No checked-in secret values were found. Runtime and CI read key names from code,
docs, or workflow env blocks.

### Runtime overrides

| Key | Used by | Required or optional | Notes |
| --- | --- | --- | --- |
| `MMO_DATA_ROOT` | `src/mmo/resources.py`, env doctor | Optional runtime override | Repoints schema, ontology, preset, and packaged plugin resolution to a user-chosen root. Must contain the expected resource layout. |
| `MMO_CACHE_DIR` | `src/mmo/resources.py`, smoke harness, env doctor | Optional runtime override | Repoints cache writes such as plugin-market snapshot cache. |
| `MMO_TEMP_DIR` | `src/mmo/resources.py`, smoke harness, env doctor | Optional runtime override | Repoints temp writes. Checkout mode otherwise prefers repo-local or OS temp roots. |
| `MMO_FFMPEG_PATH` | DSP backends, env doctor, smoke harness, docs | Optional runtime override | Forces the `ffmpeg` binary path. |
| `MMO_FFPROBE_PATH` | DSP backends, env doctor, smoke harness, docs | Optional runtime override | Forces the `ffprobe` binary path. |
| `MMO_PLUGIN_DIR` | `src/mmo/core/plugin_loader.py`, CLI overrides | Optional runtime override | Sets the external plugin root when `--plugin-dir` is not used. |

### GUI, dev-shell, and local runner helpers

| Key | Used by | Required or optional | Notes |
| --- | --- | --- | --- |
| `GUI_DEV_PORT` | `gui/server.mjs` | Optional local dev setting | Defaults the local dev-shell HTTP port to `4175` when absent. |
| `MMO_GUI_ALLOW_EXTERNAL_OUTPUT_PATHS` | `gui/server.mjs` | Optional local dev override | Allows `/api/audio-stream` to serve audio outside the project roots. Disabled by default. |
| `MMO_GUI_MMO_BIN` | `gui/lib/mmo_cli_runner.mjs` | Optional local dev override | Replaces the default `mmo` executable candidate. |
| `MMO_GUI_PYTHON_BIN` | `gui/lib/mmo_cli_runner.mjs` | Optional local dev override | Replaces the default `python` fallback candidate for `python -m mmo`. |
| `PYTHON` | `gui/desktop-tauri/README.md`, Tauri sidecar build scripts | Environment-specific helper | Used when local systems expose `python3` instead of `python` during sidecar preparation. |
| `PYTHONPATH` | GUI CLI runner and repo test runners | Environment-specific helper | GUI runner prepends `src/`. Repo pytest runners also rely on local `PYTHONPATH=src` behavior. |

### Test, screenshot, smoke, and build toggles

| Key | Used by | Required or optional | Notes |
| --- | --- | --- | --- |
| `MMO_CAPTURE_SCREENSHOTS` | `gui/desktop-tauri/tests/capture-screenshots.spec.ts`, screenshot tooling | Optional test toggle | Enables screenshot capture suites that are skipped by default. |
| `MMO_SCREENSHOT_DIR` | Screenshot tooling and Playwright capture spec | Optional test override | Repoints screenshot output directory. |
| `MMO_DESKTOP_SMOKE_SUMMARY_PATH` | Rust `desktop_smoke_config`, smoke harness | Required for packaged smoke mode | Output summary file path for packaged desktop smoke runs. |
| `MMO_DESKTOP_SMOKE_STEMS_DIR` | Rust `desktop_smoke_config`, smoke harness | Required for packaged smoke mode | Input stems directory for packaged desktop smoke runs. |
| `MMO_DESKTOP_SMOKE_WORKSPACE_DIR` | Rust `desktop_smoke_config`, smoke harness | Required for packaged smoke mode | Workspace root for packaged desktop smoke runs. |
| `MMO_DESKTOP_SMOKE_RENDER_TARGET` | Rust `desktop_smoke_config`, smoke harness | Optional smoke override | Defaults to `TARGET.STEREO.2_0` when absent. |
| `MMO_DESKTOP_SMOKE_LAYOUT_STANDARD` | Rust `desktop_smoke_config`, smoke harness | Optional smoke override | Defaults to `SMPTE` when absent. |
| `MMO_DESKTOP_SMOKE_SCENE_LOCKS_PATH` | Rust `desktop_smoke_config`, smoke harness | Optional smoke override | Optional scene-lock artifact for smoke runs. |
| `MMO_TAURI_TARGET_TRIPLE` | `tools/prepare_tauri_sidecar.py` | Optional build override | Forces the Rust target triple for sidecar preparation when auto-detection is not enough. |
| `MMO_PYTEST_N` | `tools/run_pytest.sh`, `.ps1`, `.cmd`, CI | Optional test runner setting | Enables xdist parallelism when installed. |
| `MMO_PYTHON_BIN` | `tools/run_pytest.sh` | Optional test runner override | Chooses the Python interpreter when PATH discovery is not enough. |
| `SKIP_NUMPY_TESTS` | Truth-meter and other optional dependency tests | Optional local or CI toggle | Skips numpy-dependent tests when the environment lacks the needed stack. |
| `GITHUB_BASE_REF` | `tools/validate_ontology_changes.py` | CI-oriented optional input | Supplies base-branch context for additive ontology validation. |

### Release-only secrets and signing inputs

| Key | Used by | Required or optional | Notes |
| --- | --- | --- | --- |
| `MMO_WINDOWS_CERT_BASE64` | `.github/workflows/release.yml` | Optional release secret | Base64-encoded Windows signing certificate payload. |
| `MMO_WINDOWS_CERT_PASSWORD` | `.github/workflows/release.yml` | Optional release secret | Password used to import the Windows signing certificate. |
| `MMO_WINDOWS_CERT_THUMBPRINT` | `.github/workflows/release.yml` | Optional release secret | Expected certificate thumbprint for safety checking. |
| `MMO_WINDOWS_TIMESTAMP_URL` | `.github/workflows/release.yml` | Optional release input | RFC3161 timestamp URL. Defaults to DigiCert when absent. |
| `MMO_WINDOWS_SIGNING_ENABLED`, `MMO_WINDOWS_CERT_THUMBPRINT_EFFECTIVE`, `MMO_WINDOWS_TIMESTAMP_URL_EFFECTIVE` | Release workflow after secret validation | Derived CI env | Created inside CI after signing setup succeeds or is skipped. Not user-supplied secrets. |

## 7. Trust boundaries and privilege edges

| Boundary | Validation or auth at the boundary | Assumptions the code makes | What can go wrong if the boundary is handled loosely |
| --- | --- | --- | --- |
| User-provided stems, project dirs, session files, and workspace paths -> CLI or desktop workflow | Schema validation for known artifacts, directory checks, path allowlists in some surfaces | Local operator points at the intended files and directories | Wrong paths can mix private data, overwrite local files, or feed malformed artifacts into later stages |
| `MMO_DATA_ROOT`, cache, temp, and plugin env overrides -> resource resolution | `resources.py` checks for required directory layout; plugin loader validates directories and manifests | Operator intends to override built-in packaged data | Wrong roots can silently swap schemas, ontology, presets, or plugin availability if not reviewed carefully |
| Browser dev shell -> local Node HTTP server | Minimal request shape checks and allowlisted artifact path rules | Browser is local and trusted. No network auth layer exists. | Loose path handling could expose local files or execute unintended local side effects through RPC |
| Dev shell -> `mmo gui rpc` subprocess | Request method names and JSON-object params are validated by the RPC layer | Caller is a local trusted client | Bad or unexpected method calls can write project files, update plugin caches, or install plugins |
| Desktop frontend -> bundled sidecar | Local app controls the sidecar command line and file arguments | Packaged app and sidecar come from the same release and local install | Version skew, wrong sidecar payloads, or bad path handling can create explainability gaps between UI and backend artifacts |
| Python engine -> `ffmpeg` or `ffprobe` subprocesses | Tool discovery, explicit env overrides, and command construction in backend helpers | The resolved binaries are the intended local tools | Wrong binaries or missing tools can produce wrong metadata, render failures, or misleading diagnostics |
| Plugin manifests and modules from repo, packaged data, or user dirs -> plugin loading and execution | Plugin manifests are schema-validated and semantic-validated before import. Root ordering is enforced. | Plugin code in allowed roots is trusted enough to import and execute locally | Unreviewed plugin code can affect render behavior, UI metadata, and local filesystem side effects |
| Render artifact files -> dev-shell audio streaming | Allowlisted filenames, path checks, and project-root checks guard `/api/audio-stream` | `render_execute.json` points to intended audio files | If path allowlists are bypassed, the server could expose arbitrary local audio or other files |
| CI and release jobs -> signing secrets and artifact publishing | GitHub Actions secret scoping, release workflow thumbprint checks, artifact path selection | Workflow definitions and secrets stay correct | Weak secret handling can produce unsigned or wrongly signed installers, or publish the wrong assets |

## 8. Critical data flows

| Flow | Trigger | Main entrypoints | Data stores read or written | Jobs, queues, or external systems | Key trust boundaries crossed |
| --- | --- | --- | --- | --- | --- |
| Packaged desktop workflow `Validate -> Analyze -> Scene -> Render -> Results -> Compare` | User clicks through the shipped desktop app | Tauri frontend + bundled sidecar | Reads project dir, stems, schemas, ontology, plugin data. Writes validation output, `report.json`, `report.scan.json`, `stems_map.json`, `bus_plan.json`, `scene.json`, `scene_lint.json`, `render_manifest.json`, `safe_render_receipt.json`, `render_qa.json`, and `compare_report.json`. | Local sidecar process, `ffmpeg`, `ffprobe`, filesystem | Desktop UI -> sidecar, sidecar -> local tools, user-chosen paths -> project artifacts |
| CLI analyze to scene to render-many | User runs CLI workflow such as `analyze`, `scene`, `render`, or `variants run` | `mmo analyze`, `mmo scene ...`, `mmo render ...`, `mmo variants ...` | Reads stems, run config, and plugin data. Writes analysis, scene, render, QA, listen-pack, and deliverables artifacts. | Local subprocesses and DSP backends, `ffmpeg`, `ffprobe` | User inputs -> CLI, CLI -> plugin loader, CLI -> tool subprocesses |
| Project open, edit, save, load, build GUI, and render run | User or GUI client works from a project root | `mmo project show|save|load|build-gui|write-render-request|render-run` and matching RPC methods | Reads `.mmo_project.json`, sessions, reports, scene and render files. Writes updated project state, session JSON, `ui_bundle.json`, `renders/render_request.json`, `renders/*`, and pack archives. | Local filesystem, sidecar or CLI render helpers, plugin metadata | GUI client -> RPC, project state -> artifact writers |
| Offline plugin market list, update, and install | User inspects or installs a plugin | `mmo plugin list|update|install`, RPC `plugin.market.*` | Reads packaged market index, cached snapshot, installed plugin roots, bundled plugin assets. Writes snapshot cache and copied plugin files into the external user plugin dir or explicit plugin dir. | Cache dir, filesystem, plugin loader | Packaged or cached index -> installer, installer -> user plugin dir |
| Watch-folder automation from changed stem set to render batch | Operator points MMO at a watch folder | `mmo watch ...` | Reads watched stem-set directories and project config. Writes batch output directories and downstream artifacts produced by invoked CLI runs. | Local polling loop, local subprocess launch, render backends | Untrusted folder contents -> watch queue, watch runner -> CLI subprocesses |

## 9. Operational notes

| Topic | Confirmed notes |
| --- | --- |
| CI matrix | `ci.yml` runs Linux, Windows, and macOS jobs across Python `3.12`, `3.13`, and `3.14`, plus serial Linux, GUI, screenshot, docs-manual, and desktop Tauri jobs. |
| Validation flow | CI and release both run `python tools/validate_contracts.py`. CI also runs ontology additive-change validation, golden fixtures, plugin-mode goldens, and repo pytest runners. `policy-validation.yml` adds policy, ontology-ref, plugin-manifest, and fixture checks. |
| Release outputs | `release.yml` builds a manual PDF, Python sdist and wheel, standalone CLI binaries, packaged Tauri bundles, and release artifacts for all supported platforms. |
| Docs site deployment | `pages.yml` uploads `site/` and deploys it to GitHub Pages on pushes to `main` that touch the site or the workflow itself. |
| Screenshot capture and diff | CI installs Playwright, regenerates Tauri screenshots, uploads them for debugging, and runs `tools/check_screenshot_diff.py` against `docs/manual/assets/screenshots`. |
| Determinism | The docs and artifact contracts repeatedly describe reports, scene artifacts, compare outputs, and bus plans as deterministic and diffable. |
| Concurrency and locking | Watch-folder automation keeps a local queue with `pending`, `running`, `succeeded`, and `failed` states. Scene-lock state is stored in `scene_locks.yaml`. No external queue broker or distributed lock service was found. |
| Retry and fallback | No confirmed general runtime retry or backoff framework was found. The dev shell falls back from `mmo` to `python -m mmo` for CLI startup, and resource resolution falls back across override, packaged, and checkout roots. |
| Cleanup and maintenance | Cache and temp roots can be recreated. The plugin-market update rewrites its cached snapshot. No scheduled cleanup job or cron-like maintenance unit was found in the repo. |
| Explicitly absent surfaces | No Dockerfiles, Compose files, Helm charts, Terraform files, Kubernetes manifests, or checked-in `.env.example` were found. No confirmed SQL, NoSQL, or object-storage backend was found. |

## 10. Known gaps and rough edges

- The same workflow is exposed through raw CLI commands, project helpers, GUI
  RPC, the local dev shell, and the packaged desktop app. Backend artifact
  contracts stay authoritative, but a reader still has to inspect multiple
  surfaces to understand who owns each step.
- Artifact ownership is split across project-root files, nested `project/`
  files, and `renders/` outputs. The split is documented, but it is easy to
  misread without checking both the project docs and the backend validators.
- Plugin authority spans repo checkout plugins, packaged fallback plugins, and
  user-installed external plugins. The precedence rules are explicit in code,
  but they are not obvious if a reader only looks at one docs page.
- Release packaging spans Python, Node/Vite, Rust/Tauri, Playwright, and
  optional Windows signing. CI documents the path, but local reproduction still
  requires several toolchains.
- The local dev shell is intentionally not a shipped surface, yet it still
  exposes HTTP endpoints and artifact readers. Docs should keep calling that
  distinction out so future work does not treat it like a product API.
