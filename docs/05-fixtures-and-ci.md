# docs/05-fixtures-and-ci.md

## Fixtures and CI
### How MMO stays trustworthy as it evolves.

---

## 1) Why fixtures exist
Audio tooling fails in two common ways:
- subtle regressions (a “small change” quietly breaks detection)
- untestable logic (“it sounds better” without measurable outcomes)

MMO is built to be measurable and repeatable.  
Fixtures are the foundation of that promise.

A **fixture** is a deterministic test session with known problems, stored as stems and expected outputs.

Fixtures enable:
- regression testing
- benchmark comparisons over time
- contributor onboarding (“run the fixtures, see what changes”)
- confidence in core changes and plugin changes

---

## 2) Fixture philosophy
### 2.1 Prefer synthetic or freely licensed audio
To keep the repository legally clean:
- Prefer synthetic signals and generated stems (tones, noise, impulses, simple mixes).
- If real audio is included, it must be clearly licensed for redistribution.

### 2.2 Test problems, not “taste”
Fixtures should target technical conditions:
- mud in 200–500 Hz
- harshness in 2–5 kHz
- persistent resonances
- masking between vocal and guitars
- mono collapse/phase cancellation
- sub-only bass (phone translation failure)
- surround downmix intelligibility loss

We do not attempt to encode “the perfect mix.”  
We encode detectable, measurable failure modes.

### 2.3 Allow ranges, not exact numbers
Audio metrics can vary slightly across platforms and libraries.  
Fixture expectations should use tolerances (for example ±0.5 LUFS).

---

## 3) Fixture directory layout
Recommended structure:

```
fixtures/
  README.md
  generate/
    make_mud_fixture.py
    make_harsh_fixture.py
  sessions/
    mud_demo/
      stems/
        VOCAL_LEAD__demo.wav
        GTR_L__demo.wav
        GTR_R__demo.wav
        ...
      expected/
        expected_issues.json
        expected_features.json
        expected_translation.json
        expected_recommendations.json
    harsh_demo/
      stems/
      expected/
```

Generated fixtures should be reproducible from scripts in `fixtures/generate/`.

---

## 4) What a fixture “expects”
Each fixture should specify expectations at three layers:

### 4.1 Validation expectations
- sample rate consistency
- stem alignment
- length checks
- role parsing correctness

### 4.2 Measurement expectations
- LUFS integrated in a tolerance band
- true peak in a tolerance band
- band energy characteristics (directional expectations)

### 4.3 Detection expectations
- specific issue IDs appear (ontology IDs)
- minimum severity thresholds (or severity band ranges)
- evidence includes reasonable time/frequency ranges
- confidence meets minimum level for the known condition

Optionally:
- recommendation expectations (actions exist and include required params)
- translation score expectations (phone profile should fail, etc.)

---

## 5) CI goals
CI exists to ensure:
- core “truth layer” changes do not regress fixtures
- plugin outputs remain schema-valid
- ontology changes remain consistent and non-breaking
- code style and typing do not degrade

Minimum CI checks:
- lint (ruff/black or similar)
- type checks (mypy optional early)
- unit tests (pytest)
- fixture tests (pytest)
- ontology validation (YAML consistency + ID uniqueness)

---

## 6) Regression rules (what blocks a PR)
### 6.1 Core changes (high bar)
Any change in:
- meters
- validation
- gates
- schemas
- ontology rules
must pass all fixtures and unit tests.

If fixture outcomes change:
- the PR must explain why
- the expected outputs must be updated intentionally
- maintainers must review with extra caution

### 6.2 Plugin changes (moderate bar)
Plugins must:
- pass schema and ontology validation
- include at least one fixture proving behavior
- avoid breaking other plugins through ID misuse

---

## 7) How to add a fixture (contributor workflow)
1) Decide the target failure mode (mud, harshness, etc.)
2) Add a generator script or a stems folder:
   - generator preferred for reproducibility
3) Include stems in `fixtures/sessions/<name>/stems/`
4) Run MMO to produce a report and capture expected outputs:
   - `expected_issues.json` should include issue IDs and severity bands
   - `expected_features.json` should include key meters and tolerances
5) Add or update a test in `tests/test_fixtures.py`
6) Document the fixture in `fixtures/README.md`

---

## 8) Suggested fixtures (starter set)
### Stereo fixtures
- `mud_demo`: boosted 250 Hz on multiple stems
- `harsh_demo`: narrow boost around 3–4 kHz on vocal/cymbals
- `resonance_demo`: persistent narrow peaks in one stem
- `mono_collapse_demo`: phasey widened synth that cancels in mono
- `sub_only_bass_demo`: bass lives only below 60 Hz, fails phone translation

### Surround fixtures (later milestones)
- `downmix_dialogue_loss_5_1_demo`: center content cancels/vanishes on stereo fold-down
- `lfe_overuse_demo`: too much bass routed to LFE

---

## 9) Test implementation guidance
### 9.1 Use tolerance-based assertions
Examples:
- LUFS within ±0.5
- true peak within ±0.5 dBTP
- severity ≥ threshold or within a band

### 9.2 Prefer “presence” assertions for issues
- assert `ISSUE.SPECTRAL.MUD` exists
- assert evidence includes 200–500 Hz
- assert severity ≥ 70 for fixture

Avoid brittle exact-value comparisons unless necessary.

---

## 10) CI configuration notes
A minimal GitHub Actions workflow should:
- install dependencies
- run `pytest`
- validate ontology YAML
- fail fast on schema validation errors

When the project grows:
- add caching
- add matrix builds for Windows/macOS/Linux
- add optional performance benchmarks (non-blocking initially)

---

## 11) What’s next
After this doc:
- write `fixtures/README.md`
- implement fixture generators for mud and harshness
- implement `tests/test_fixtures.py` using tolerance-based checks
- add ontology validation tests to CI


## Policy fixtures

Policy integrity is validated separately from audio analysis.

- `fixtures/policies/` contains deterministic cases for registry and policy-pack validation.
- These cases should be runnable in CI without any audio files.
- Expected outputs should be expressed as `ISSUE.VALIDATION.*` IDs (see `docs/08-policy-validation.md`).
