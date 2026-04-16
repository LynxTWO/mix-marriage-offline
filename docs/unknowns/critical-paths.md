# Critical Path Unknowns

<!-- markdownlint-disable-file MD013 -->

This file records unresolved questions from comment-only critical-path passes.
Add entries here instead of guessing when a risky code path cannot be explained
confidently from repo evidence.

Status for the 2026-04-16 pass: no unresolved critical-path questions remained
after inspection.

Status for the 2026-04-16 render-gates pass: no unresolved critical-path
questions remained after inspection.

Status for the 2026-04-16 artifact-and-compare pass: no unresolved
critical-path questions remained after inspection.

Status for the 2026-04-16 project-session pass: no unresolved critical-path
questions remained after inspection.

Status for the 2026-04-16 analysis-and-intake pass: no unresolved
critical-path questions remained after inspection.

Status for the 2026-04-16 scene-binding pass: no unresolved critical-path
questions remained after inspection.

Status for the 2026-04-16 scene-consumer pass: no unresolved critical-path
questions remained after inspection.

Status for the 2026-04-16 DSP and recall-export pass: no unresolved
critical-path questions remained after inspection.

Status for the 2026-04-16 render-execution and downmix-QA pass: no open
question remained in this slice.

Status for the 2026-04-16 PDF report exporter pass: no open question remained
in this slice.

Status for the 2026-04-16 corrective-renderer pass: no open question remained
in this slice.

Status for the 2026-04-16 recall-and-downmix-exporter pass: no open question
remained in this slice.

Status for the 2026-04-16 PDF manual exporter pass: no open question remained
in this slice.

Status for the 2026-04-16 dev-shell bridge pass: no open question remained in
this slice.

Status for the 2026-04-16 packaged desktop frontend pass: no open question
remained in this slice.

Status for the 2026-04-16 desktop native-shell and smoke pass: no open
question remained in this slice.

Status for the 2026-04-16 browser-state dev-shell pass: no open question
remained in this slice.

| Area, file, line range, or function | Concern | Why it matters | Evidence found so far | Likely owner if known | Next best check | Risk level |
| --- | --- | --- | --- | --- | --- | --- |
| Initial backend comment pass | No open question in that pass. The selected backend paths were explainable from code, docs, and the system map without inventing behavior. | Future passes still need one place to record uncertainty instead of burying it in comments. | Reviewed `src/mmo/resources.py`, `src/mmo/core/plugin_loader.py`, `src/mmo/core/plugin_market.py`, `src/mmo/cli_commands/_project.py`, `src/mmo/cli_commands/_gui_rpc.py`, `src/mmo/core/render_engine.py`, `src/mmo/core/watch_folder.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add a row when a later pass finds unresolved behavior. | Critical |
| Render-gates pass | No open question in that pass. The render gating and preflight path was explainable from code and repo docs without inventing missing policy behavior. | The running log should show which critical surfaces were reviewed and where uncertainty first appeared. | Reviewed `src/mmo/cli_commands/_scene.py`, `src/mmo/core/render_preflight.py`, `src/mmo/core/gates.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add a row when a later pass finds a render-gate or preflight gap. | Critical |
| Artifact-and-compare pass | No open question in that pass. The artifact-integrity and compare paths were explainable from code and repo docs without inventing missing execution or reporting behavior. | Later passes need a record that these artifact surfaces were reviewed before project and session work. | Reviewed `src/mmo/core/compare.py`, `src/mmo/core/render_execute.py`, `src/mmo/core/render_reporting.py`, `src/mmo/core/report_builders.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add a row when a later pass finds an artifact or compare gap. | Critical |
| Project-session pass | No open question in that pass. The project persistence and stem source-resolution paths were explainable from code and repo docs without inventing save, load, or relocation behavior. | The log should show that portability and overwrite rules were reviewed before intake and scene binding. | Reviewed `src/mmo/core/config.py`, `src/mmo/core/project_file.py`, `src/mmo/core/session.py`, `src/mmo/core/source_locator.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add a row when a later pass finds a project-session or source-resolution gap. | Critical |
| Analysis and intake backend pass | No open question in this pass. The scan, analyze, classification, and bus-planning path was explainable from code and repo docs without inventing missing intake behavior. | The log should show that raw intake and planner inputs were reviewed before scene binding and report shaping. | Reviewed `src/mmo/tools/scan_session.py`, `src/mmo/tools/analyze_stems.py`, `src/mmo/tools/run_pipeline.py`, `src/mmo/core/stems_index.py`, `src/mmo/core/stems_classifier.py`, `src/mmo/core/bus_plan.py`, `docs/architecture/system-map.md`, and `docs/architecture/coverage-ledger.md`. | not declared in repo | Add a row when a later pass finds an intake, scene-binding, or report-shaping gap. | Critical |
| Scene-binding and precedence pass | No open question in this pass. The scene-building, draft scaffolding, routing, and lock-precedence path was explainable from code and repo docs without inventing missing authority behavior. | The log should show that scene assembly, routing defaults, and hard-lock render blocking were reviewed before DSP and exporter work. | Reviewed `src/mmo/core/scene_builder.py`, `src/mmo/core/stems_draft.py`, `src/mmo/core/routing.py`, `src/mmo/core/precedence.py`, `docs/architecture/system-map.md`, `docs/architecture/coverage-ledger.md`, `tests/test_scene_builder.py`, `tests/test_scene_builder_bus_plan.py`, and `tests/test_lock_precedence_matrix.py`. | not declared in repo | Add a row when a later pass finds a scene helper or downstream scene-consumer gap. | Critical |
| Scene-consumer pass | No open question in this pass. The scene-compatibility checks and primary renderer-side scene consumers were explainable from code and repo docs without inventing missing authority behavior. | The log should show that renderer-side scene binding, strict validation, and recommendation blocking were reviewed before DSP work. | Reviewed `src/mmo/core/profiles.py`, `src/mmo/cli_commands/_renderers.py`, `docs/architecture/system-map.md`, and `docs/architecture/coverage-ledger.md`. | not declared in repo | Add a row when a later pass finds a secondary scene-consumer or DSP gap. | Critical |
| DSP and recall-export pass | No open question in this pass. The decode, resampling, downmix, transcode, export-finalization, and recall-sheet evidence paths were explainable from code and repo docs without inventing missing DSP authority behavior. | The log should show that irreversible audio-output boundaries and the main CSV evidence export were reviewed before renderer-plugin and render-audio work. | Reviewed `src/mmo/dsp/backends/ffmpeg_discovery.py`, `src/mmo/dsp/backends/ffprobe_meta.py`, `src/mmo/dsp/backends/ffmpeg_decode.py`, `src/mmo/dsp/decoders.py`, `src/mmo/dsp/sample_rate.py`, `src/mmo/dsp/downmix.py`, `src/mmo/dsp/transcode.py`, `src/mmo/dsp/export_finalize.py`, `src/mmo/exporters/recall_sheet.py`, `docs/architecture/system-map.md`, and `docs/architecture/coverage-ledger.md`. | not declared in repo | Add a row when a later pass finds a renderer-plugin, render-audio, or richer exporter gap. | Critical |
| Render execution and downmix-QA pass | No open question in this pass. The shared render executor, downmix QA, and the primary mixdown renderers were explainable from code and repo docs. | This records that the remaining DSP follow-up consumers were reviewed before the richer exporter pass or the next non-DSP trust boundary slice. | Reviewed `src/mmo/core/render_run_audio.py`, `src/mmo/core/downmix_qa.py`, `src/mmo/plugins/renderers/mixdown_renderer.py`, `src/mmo/plugins/renderers/placement_mixdown_renderer.py`, `docs/architecture/system-map.md`, and `docs/architecture/coverage-ledger.md`. | not declared in repo | Add a row when a later pass finds a PDF-exporter or secondary renderer gap. | Critical |
| PDF report exporter pass | No open question in this pass. The report PDF exporter was explainable from code, tests, and repo docs without inventing missing review or fallback behavior. | This records that the richer review PDF now has critical-path notes before any shift to non-DSP trust boundaries. | Reviewed `src/mmo/exporters/pdf_report.py`, `tests/test_exporters.py`, `tests/test_cli_render_report.py`, `tests/test_render_result_contract.py`, `docs/architecture/system-map.md`, and `docs/architecture/coverage-ledger.md`. | not declared in repo | Add a row when a later pass finds a PDF-manual or non-DSP gap. | Critical |
| Corrective renderer pass | No open question in this pass. The shipped corrective renderers and the approval-audit renderer were explainable from code, plugin manifests, tests, and repo docs without inventing missing DSP or approval behavior. | This records that the remaining shipped renderer plugins were reviewed before the exporter follow-up pass or the next non-DSP trust boundary slice. | Reviewed `src/mmo/plugins/renderers/gain_trim_renderer.py`, `src/mmo/plugins/renderers/compressor_renderer.py`, `src/mmo/plugins/renderers/limiter_renderer.py`, `src/mmo/plugins/renderers/parametric_eq_renderer.py`, `src/mmo/plugins/renderers/safe_renderer.py`, `tests/test_gain_trim_renderer_multiformat.py`, `tests/test_corrective_plugins.py`, `tests/test_mastering_bus.py`, `tests/test_resolver_pipeline.py`, `tests/test_spectral_plugins.py`, `tests/test_cli_safe_render.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add a row when a later pass finds an exporter or non-DSP gap. | Critical |
| Recall and downmix exporter pass | No open question in this pass. The recall CSV, downmix QA CSV and PDF, and shared export truncation helpers were explainable from code, tests, and repo docs without inventing missing evidence or formatting behavior. | This records that the remaining shipped render-review exporters were reviewed before any shift away from the DSP and exporter slice. | Reviewed `src/mmo/exporters/csv_recall.py`, `src/mmo/exporters/downmix_qa_csv.py`, `src/mmo/exporters/downmix_qa_pdf.py`, `src/mmo/exporters/pdf_utils.py`, `tests/test_exporters.py`, `tests/test_downmix_qa_exports.py`, `tests/test_cli_report.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add a row when a later pass finds a manual-export or non-DSP gap. | Critical |
| PDF manual exporter pass | No open question in this pass. The user-manual PDF builder was explainable from code, CLI wrappers, tests, and repo docs without inventing missing document-build or appendix behavior. | This records that the last deferred exporter path was reviewed before the next pass moves to the local dev-shell bridge or another non-DSP trust boundary. | Reviewed `src/mmo/exporters/pdf_manual.py`, `src/mmo/tools/build_user_manual.py`, `tools/validate_user_manual.py`, `tests/test_validate_user_manual.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add a row when a later pass finds a dev-shell or manual-build gap. | Critical |
| Dev-shell bridge pass | No open question in this pass. The local HTTP bridge, CLI fallback launcher, and RPC subprocess client were explainable from code, tests, and repo docs without inventing missing trust-boundary behavior. | This records that the local dev-shell trust boundary was reviewed before a later pass moves into browser-side state or the shipped desktop frontend. | Reviewed `gui/server.mjs`, `gui/lib/mmo_cli_runner.mjs`, `gui/lib/rpc_process_client.mjs`, `gui/tests/mmo_cli_runner.test.mjs`, `gui/tests/rpc_process_client.test.mjs`, `gui/tests/server_audio_stream.test.mjs`, `docs/12-gui-dev.md`, and `docs/architecture/system-map.md`. | not declared in repo | Add a row when a later pass finds a frontend-state or packaged-desktop gap. | Critical |
| Packaged desktop frontend pass | No open question in this pass. The packaged desktop state, sidecar handoff, and recent-path persistence rules were explainable from code, tests, and repo docs without inventing missing trust-boundary behavior. | This records that the shipped desktop frontend entrypoint was reviewed before a later pass moves into native shell and sidecar packaging details. | Reviewed `gui/desktop-tauri/src/main.ts`, `gui/desktop-tauri/src/mmo-sidecar.ts`, `gui/desktop-tauri/src/desktop-paths.ts`, `gui/desktop-tauri/tests/capture-screenshots.spec.ts`, `gui/desktop-tauri/tests/design-system.spec.ts`, `gui/desktop-tauri/tests/status-display.spec.ts`, and `docs/architecture/system-map.md`. | not declared in repo | Add a row when a later pass finds a native-shell or browser-state gap. | Critical |
| Desktop native-shell and smoke pass | No open question in this pass. The native smoke command, sidecar staging, packaged bundle discovery, and MSI version guard were explainable from code, tests, and repo docs without inventing missing packaging behavior. | This records that the remaining packaged desktop trust boundary was reviewed before a later pass moves to browser-side frontend state. | Reviewed `gui/desktop-tauri/src-tauri/src/lib.rs`, `gui/desktop-tauri/src-tauri/Cargo.toml`, `tools/prepare_tauri_sidecar.py`, `gui/desktop-tauri/scripts/prepare-sidecar.mjs`, `tools/smoke_packaged_desktop.py`, `tools/validate_msi_version.py`, `tests/test_prepare_tauri_sidecar.py`, `tests/test_packaged_desktop_smoke.py`, `tests/test_packaged_smoke_goldens.py`, `tests/test_tauri_desktop_workflow.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add a row when a later pass finds a browser-state or release-workflow gap. | Critical |
| Browser-state dev-shell pass | No open question in this pass. The browser controller for RPC calls, project hydration, scene-lock editing, render-artifact views, and audition preview was explainable from code, tests, and repo docs without inventing missing frontend-state behavior. | This records that the main browser-side trust boundary was reviewed after the local bridge and desktop packaging passes, before any later helper-only cleanup or another non-comment review slice. | Reviewed `gui/web/app.js`, `gui/web/index.html`, `gui/package.json`, `gui/tests/run_tests.mjs`, `gui/tests/dashboard_visuals.test.mjs`, `gui/tests/plugin_forms.test.mjs`, `gui/tests/headphone_preview_meter.test.mjs`, `gui/tests/audition_loudness.test.mjs`, `gui/tests/audition_overlays.test.mjs`, `docs/12-gui-dev.md`, and `docs/architecture/system-map.md`. | not declared in repo | Add a row when a later pass finds a browser-helper or release-workflow gap. | Critical |
