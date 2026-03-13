# Safe-Render Baseline Stems

Deterministic WAV stems for safe-render baseline mixdown tests.

Files:

- `kick_mono.wav` (mono, 48 kHz, 0.2 s)
- `music_stereo.wav` (stereo, 48 kHz, 0.2 s)
- `vox_mono.wav` (mono, 48 kHz, 0.2 s)

These fixtures are intentionally short and low-level so baseline render tests
can verify output existence, headroom policy, and hash determinism quickly.
