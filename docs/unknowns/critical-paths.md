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

| Area, file, line range, or function | Concern | Why it matters | Evidence found so far | Likely owner if known | Next best check | Risk level |
| --- | --- | --- | --- | --- | --- | --- |
| Initial backend comment pass | None in that pass. The selected backend paths were explainable from code, docs, and the system map without inventing behavior. | Keep this file present so future passes have a stable place to record uncertainty instead of burying it in comments. | Reviewed `src/mmo/resources.py`, `src/mmo/core/plugin_loader.py`, `src/mmo/core/plugin_market.py`, `src/mmo/cli_commands/_project.py`, `src/mmo/cli_commands/_gui_rpc.py`, `src/mmo/core/render_engine.py`, `src/mmo/core/watch_folder.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add one row per unresolved behavior as soon as a future pass finds a gap. | Critical |
| Render-gates pass | None in that pass. The render gating and preflight path was explainable from code and repo docs without inventing missing policy behavior. | Keep this file cumulative so later passes can see which critical surfaces were already reviewed and where uncertainty first appeared. | Reviewed `src/mmo/cli_commands/_scene.py`, `src/mmo/core/render_preflight.py`, `src/mmo/core/gates.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add one row per unresolved render-gate or preflight behavior as soon as a future pass finds a gap. | Critical |
| Artifact-and-compare pass | None in that pass. The artifact-integrity and compare paths were explainable from code and repo docs without inventing missing execution or reporting behavior. | Keep this file cumulative so later passes can see which artifact surfaces were already reviewed before moving to project and session state. | Reviewed `src/mmo/core/compare.py`, `src/mmo/core/render_execute.py`, `src/mmo/core/render_reporting.py`, `src/mmo/core/report_builders.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add one row per unresolved artifact or compare behavior as soon as a future pass finds a gap. | Critical |
| Project-session pass | None in that pass. The project persistence and stem source-resolution paths were explainable from code and repo docs without inventing save, load, or relocation behavior. | Keep this file cumulative so later passes can see that project-session portability and overwrite rules were reviewed before moving on to intake and scene binding. | Reviewed `src/mmo/core/config.py`, `src/mmo/core/project_file.py`, `src/mmo/core/session.py`, `src/mmo/core/source_locator.py`, and `docs/architecture/system-map.md`. | not declared in repo | Add one row per unresolved project-session or source-resolution behavior as soon as a future pass finds a gap. | Critical |
| Analysis and intake backend pass | None in this pass. The scan, analyze, classification, and bus-planning path was explainable from code and repo docs without inventing missing intake behavior. | Keep this file cumulative so later passes can see that the raw intake and planner-input path was reviewed before moving on to scene binding and report shaping. | Reviewed `src/mmo/tools/scan_session.py`, `src/mmo/tools/analyze_stems.py`, `src/mmo/tools/run_pipeline.py`, `src/mmo/core/stems_index.py`, `src/mmo/core/stems_classifier.py`, `src/mmo/core/bus_plan.py`, `docs/architecture/system-map.md`, and `docs/architecture/coverage-ledger.md`. | not declared in repo | Add one row per unresolved intake, scene-binding, or report-shaping behavior as soon as a future pass finds a gap. | Critical |
| Scene-binding and precedence pass | None in this pass. The scene-building, draft scaffolding, routing, and lock-precedence path was explainable from code and repo docs without inventing missing authority behavior. | Keep this file cumulative so later passes can see that scene object and bed derivation, routing defaults, and hard-lock render blocking were reviewed before moving on to DSP and exporter behavior. | Reviewed `src/mmo/core/scene_builder.py`, `src/mmo/core/stems_draft.py`, `src/mmo/core/routing.py`, `src/mmo/core/precedence.py`, `docs/architecture/system-map.md`, `docs/architecture/coverage-ledger.md`, `tests/test_scene_builder.py`, `tests/test_scene_builder_bus_plan.py`, and `tests/test_lock_precedence_matrix.py`. | not declared in repo | Add one row per unresolved scene-compatibility helper or downstream scene-consumer behavior as soon as a future pass finds a gap. | Critical |
| Scene-consumer pass | None in this pass. The scene-compatibility checks and primary renderer-side scene consumers were explainable from code and repo docs without inventing missing authority behavior. | Keep this file cumulative so later passes can see that renderer-side scene binding, strict validation, and recommendation blocking were reviewed before moving on to DSP and exporter behavior. | Reviewed `src/mmo/core/profiles.py`, `src/mmo/cli_commands/_renderers.py`, `docs/architecture/system-map.md`, and `docs/architecture/coverage-ledger.md`. | not declared in repo | Add one row per unresolved secondary scene-consumer or DSP behavior as soon as a future pass finds a gap. | Critical |
