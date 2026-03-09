# Troubleshooting and common failures

If something fails, do not guess.
Run the doctor.

Environment checks.
mmo env doctor --format text

PDF export fails.
Install the PDF extra:
pip install .[pdf]

Truth meters fail.
NumPy is part of the base install now.
Repair the source environment:
pip install .

FLAC or WavPack metadata warnings.
Install FFmpeg/ffprobe, or set MMO_FFMPEG_PATH and MMO_FFPROBE_PATH.

Scan reports “stems not aligned.”
Re-export stems with consistent start time and duration.
Do not trim silence differently per stem.

Watch-folder misses a set.
Increase --settle-seconds so partial copies are not processed early.

Safe-render says “blocked.”
That means your current authority profile or locks stopped a risky action.
Use `--dry-run` to inspect what would happen.
Use `--approve` only when you intentionally accept the change.

Safe-render reports `ISSUE.RENDER.NO_OUTPUTS`.
No audio outputs were written.
If you see NO_OUTPUTS, install/enable MIXDOWN_BASELINE renderer.
Use `--allow-empty-outputs` only if you intentionally want a no-output pass.

GUI live-log error codes.
[GUI.E2000] stage_failed — a pipeline stage exited with a nonzero return code.
  The log line includes `stage=<name>` and `rc=<code>` to identify which stage failed.
  A follow-up `first_error_line` entry shows the first "error:" or "Traceback" line from output.
[GUI.E2001] spawn_failed — the GUI could not launch the subprocess at all.
  Check that the mmo package is installed and the executable path is valid.
[GUI.STAGE] `<stage>` starting. / completed ok. — informational stage anchors for orientation.

Windows: unrecognized arguments with -m mmo.
If the GUI live log shows `error: unrecognized arguments: -m mmo analyze ...` you are on
a broken build (v1.1.0 Windows GUI). Upgrade to v1.1.1 or later.
The v1.1.1 GUI executable handles `-m mmo <subcommand>` directly, matching the frozen
build's internal invocation pattern.

Windows: default plugins folder.
On Windows the GUI and CLI resolve the default user plugin directory to:
  %LOCALAPPDATA%\mmo\plugins  (e.g. C:\Users\you\AppData\Local\mmo\plugins)
If LOCALAPPDATA is not set, APPDATA and then USERPROFILE are tried.
The old behaviour (v1.1.0 and earlier) fell back to a system path (System32/plugins) in
some packaged builds. v1.1.1 fixes this.
Override at any time with the MMO_PLUGIN_DIR environment variable.

Pro notes.
If you are debugging determinism, keep artifact folders and compare them.
Use `mmo compare` between reports to see what changed.
