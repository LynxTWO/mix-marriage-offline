# fixtures/golden_path_small/

Deterministic tiny stem fixture for immersive golden-path CI coverage.

## Contents

- `stems/`:
  - `kick.wav` (mono)
  - `snare.wav` (mono)
  - `bass_di.wav` (mono)
  - `pad_stereo_wide.wav` (stereo)
  - `sfx_stereo.wav` (stereo)
- `generate_stems.py`: deterministic stem generator used to (re)build `stems/`.
- `expected_golden_hashes.json`: expected scene-template choice, channel-count
  contract, and deterministic WAV hashes used by the golden-path integration
  test.

## Regenerate stems

```bash
python fixtures/golden_path_small/generate_stems.py
```
