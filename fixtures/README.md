# Fixtures

Fixtures are deterministic inputs used for tests and CI.

## Folders

- `fixtures/public_session/`: public 7.1.4 example session fixture used by
  `tests/test_full_determinism.py` to verify byte-stable safe-render outputs
  for SMPTE and FILM ordering.
- `fixtures/golden_path_small/`: tiny generated stem fixture (mixed mono/stereo)
  with expected channel-count and WAV-hash snapshots for immersive
  `classify -> bus-plan -> scene -> safe-render --render-many` CI coverage.
- `fixtures/stems_small/`: compact, redistributable stem-name corpus modeled
  from real-world naming patterns (numeric suffixes, compound instrument/vocal
  tokens, synth/SFX variants) used for stems->bus-plan->scene regression tests.
- `fixtures/expected_bus_plan.json`: deterministic expected bus-plan snapshots
  for each `fixtures/stems_small/*` session.
- `fixtures/expected_scene.json`: deterministic expected scene snapshots for
  each `fixtures/stems_small/*` session.
- `fixtures/immersive/`: deterministic immersive fixture for `mmo safe-render --demo`.
- `fixtures/render/`: deterministic render-plan/report fixtures for export-contract
  regression checks (including dual-LFE x.2 edge cases such as `5.2`, `7.2`,
  and `7.2.4`).
- `fixtures/sessions/`: session-validation fixtures (issue-ID expectations).
- `fixtures/policies/`: policy YAML fixtures (downmix packs, registry validation).

See `docs/05-fixtures-and-ci.md` for overall fixture philosophy.
