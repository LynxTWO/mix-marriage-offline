# Fixtures

Fixtures are deterministic inputs used for tests and CI.

## Folders

- `fixtures/public_session/`: public 7.1.4 example session fixture used by
  `tests/test_full_determinism.py` to verify byte-stable safe-render outputs
  for SMPTE and FILM ordering.
- `fixtures/immersive/`: deterministic immersive fixture for `mmo safe-render --demo`.
- `fixtures/sessions/`: session-validation fixtures (issue-ID expectations).
- `fixtures/policies/`: policy YAML fixtures (downmix packs, registry validation).

See `docs/05-fixtures-and-ci.md` for overall fixture philosophy.
