# Troubleshooting and common failures

If something fails, do not guess.
Run the doctor.

Environment checks.
mmo env doctor --format text

PDF export fails.
Install the PDF extra:
pip install .[pdf]

Truth meters fail.
Install the truth extra:
pip install .[truth]

FLAC or WavPack metadata warnings.
Install FFmpeg, or set MMO_FFPROBE_PATH.

Scan reports “stems not aligned.”
Re-export stems with consistent start time and duration.
Do not trim silence differently per stem.

Watch-folder misses a set.
Increase --settle-seconds so partial copies are not processed early.

Safe-render says “blocked.”
That means your current authority profile or locks stopped a risky action.
Use `--dry-run` to inspect what would happen.
Use `--approve` only when you intentionally accept the change.

Pro notes.
If you are debugging determinism, keep artifact folders and compare them.
Use `mmo compare` between reports to see what changed.