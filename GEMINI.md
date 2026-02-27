# GEMINI: Repo context preamble (MMO)

You are working in the Mix Marriage Offline (MMO) repository.

Read these first (source of truth):
1) PROJECT_WHEN_COMPLETE.md (finish line and Definition of Done)
2) AGENTS.md (repo workflow, commands, constraints)
3) docs/ (architecture + contracts)
4) ontology/ and schemas/ (canonical IDs and strict validation)

Non-negotiables:
- Offline-first, deterministic behavior, explainability, bounded authority.
- Objective Core contracts cannot be broken by plugins.
- Layout safety and downmix QA gates must be preserved.
- Keep GUI dashboard rendering deterministic (frame + surface snapshot signatures).
- Route runtime progress/cancel/live-log wiring through `mmo.core.progress`
  and keep ETA/runtime diagnostics out of deterministic persisted artifacts.
- Keep `fixtures/public_session/report.7_1_4.json` and
  `tests/test_full_determinism.py` in sync for full-pipeline byte-stability checks.
- Keep watch-folder automation deterministic: debounce event bursts, detect
  changed stem sets by signature, and launch install-safe `python -m mmo run`
  render-many batches.
