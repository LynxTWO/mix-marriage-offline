# Install and verify

Quick path (end users).
Use the one-click release assets when you want “no Python required.”
Those are distributed via GitHub Releases as Windows installer, macOS app bundle, and Linux AppImage.

Quick path (repo checkout / dev).
MMO requires Python 3.12+ for source installs.

Install base:
pip install .

Optional extras:
pip install .[pdf]
pip install .[truth]
pip install .[gui]
pip install .[watch]

Verify the CLI:
mmo --help

Verify the GUI entry point:
mmo-gui --help
(If you installed with `.[gui]`, you can launch the fallback CustomTkinter GUI
as `mmo-gui` until Tauri parity lands. It is deprecated after parity lands.)

FFmpeg and ffprobe (recommended).
MMO can run without FFmpeg for WAV-only workflows.
FFmpeg/ffprobe unlocks richer decode, metadata handling, and some QA flows.

If FFmpeg is not on PATH, set:
MMO_FFMPEG_PATH=/path/to/ffmpeg
MMO_FFPROBE_PATH=/path/to/ffprobe

Confirm your environment:
mmo env doctor --format text

Pro notes.
If your workflow includes FLAC or WavPack inputs, ffprobe is the difference between “best effort” and “full metadata.”
If you want PDF exports, install `.[pdf]` so ReportLab is available.
If you want truth meters, install `.[truth]` so NumPy is available.
If you want watch-folder automation, install `.[watch]` so watchdog is available.
