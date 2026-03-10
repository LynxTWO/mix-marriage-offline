Deterministic safe-render fallback regression fixture.

- `report.json` and `scene.json` use `__FIXTURE_STEMS_DIR__` as a placeholder.
- Tests materialize that placeholder to the absolute `stems/` path at runtime.
- The ambience bed enables decorrelated bed widening so the full fallback
  sequence can run through surround, height, decorrelation, widener disable,
  front-bias, and safety-collapse steps.
