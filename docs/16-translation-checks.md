# Translation Checks

This guide explains MMO translation checks and how to run them in CLI and render-many flows.

## What Translation Checks Are

Translation checks are deterministic playback simulations that score how well a stereo print is expected to hold up across common listening contexts.

- Meter-only: checks read the rendered WAV and compute mono and spectral metrics; they do not run adaptive processing or auto-fix audio.
- Non-enforcing: checks are advisory and emit `translation_results` (plus issues when needed), but they do not act as blocking gates by themselves.
- Deterministic: same input WAV + same profiles produce the same scores and issue evidence.

Current check scope:

- Input format: mono/stereo WAV (`.wav`/`.wave`)
- Score range: integer `0..100`
- Default low-score threshold: `70` (unless a profile overrides it)

## Default Profiles

The default registry is `ontology/translation_profiles.yaml`:

- `TRANS.MONO.COLLAPSE`: phase cancellation and center-energy retention when folding stereo to mono.
- `TRANS.DEVICE.PHONE`: small single-speaker behavior, midrange translation, and collapse resilience.
- `TRANS.DEVICE.SMALL_SPEAKER`: compact consumer speaker stress check for intelligibility and balance drift.
- `TRANS.DEVICE.EARBUDS`: upper-mid comfort plus vocal presence on compact drivers.
- `TRANS.DEVICE.CAR`: low-end focus, vocal readability, and harshness risk in noisy playback.

Each profile defines:

- `default_thresholds`: conservative limits (for example correlation floor and spectral ratio ceilings).
- `scoring`: weighted components (`mono_compatibility`, `spectral_balance`, `vocal_clarity`, `low_end_translation`, `fatigue_risk`).
- `intent` and `notes`: UI/help-facing context for why the profile exists.

## Scoring (0-100, Conservative)

MMO scores each selected profile independently:

1. Start from `100`.
2. Compute deterministic penalties from measured deltas vs profile thresholds.
3. Apply profile scoring weights to those penalties.
4. Subtract weighted penalty from `100`.
5. Round to integer and clamp into `0..100`.

Conservative behavior details:

- Penalties only grow when measurements move past thresholds.
- Any score below threshold produces `ISSUE.TRANSLATION.PROFILE_SCORE_LOW`.
- Severity scales with score gap below threshold.

## CLI Usage

List profiles:

```bash
mmo translation list --format text
mmo translation list --format json
```

Show a specific profile:

```bash
mmo translation show TRANS.MONO.COLLAPSE --format text
mmo translation show TRANS.MONO.COLLAPSE --format json
```

Run checks from a WAV:

```bash
mmo translation run --audio out/stereo.wav --profiles TRANS.MONO.COLLAPSE,TRANS.DEVICE.PHONE --format text
mmo translation run --audio out/stereo.wav --profiles TRANS.MONO.COLLAPSE,TRANS.DEVICE.PHONE --format json
```

Optional outputs:

```bash
mmo translation run --audio out/stereo.wav --profiles TRANS.MONO.COLLAPSE --out out/translation_results.json --format json
mmo translation run --audio out/stereo.wav --profiles TRANS.MONO.COLLAPSE --report-in out/report.json --report-out out/report.with_translation.json --format json
```

Notes:

- `--profiles` is required for `translation run`.
- `--report-in` and `--report-out` must be provided together.

## Render-Many Integration

You can run translation checks during `run --render-many`:

```bash
mmo run --stems stems --out out --render-many --targets TARGET.STEREO.2_0 --translation
```

With explicit profile selection:

```bash
mmo run --stems stems --out out --render-many --targets TARGET.STEREO.2_0 --translation --translation-profiles TRANS.MONO.COLLAPSE,TRANS.DEVICE.PHONE,TRANS.DEVICE.SMALL_SPEAKER
```

Behavior:

- `--translation` with no profile list uses default render-many profiles:
  - `TRANS.MONO.COLLAPSE`
  - `TRANS.DEVICE.PHONE`
  - `TRANS.DEVICE.SMALL_SPEAKER`
- Results are patched into report/bundle payloads as `translation_results` when a stereo deliverable is present.

## Interpreting Issues and Evidence

When a profile score is below threshold, MMO emits:

- `issue_id`: `ISSUE.TRANSLATION.PROFILE_SCORE_LOW`
- `message`: includes profile ID, score, and threshold
- `target.scope`: `session`

Common evidence IDs:

- `EVID.ISSUE.SCORE` (`UNIT.RATIO`): normalized score ratio (`score / 100`).
- `EVID.SPECTRAL.BAND_ENERGY_DB` (`UNIT.DB`): band-ratio evidence for device profiles.
- `EVID.ISSUE.MEASURED_VALUE` (`UNIT.DB`): mono-loss metric for mono-collapse profile.
- `EVID.SEGMENT.START_S` and `EVID.SEGMENT.END_S` (`UNIT.S`): worst mono-loss segment bounds.

Evidence fields are intentionally explicit:

- `value`: measured value used in scoring.
- `where`: optional location/band metadata.
- `why`: deterministic explanation tied to profile thresholds.
