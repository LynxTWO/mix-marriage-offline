# Install and verify

Quick path (end users). Use the one-click release assets when you want “no
Python required.” GitHub Releases publish the Tauri desktop app as a Windows
installer, macOS app bundle, and Linux AppImage, plus standalone CLI binaries
for automation or headless workflows.

Quick path (repo checkout / dev). MMO requires Python 3.12+ for source installs.

Install base: pip install .

Optional extras: pip install .[pdf] pip install .[watch]

Verify the CLI: mmo --help

Desktop note. The old CustomTkinter `mmo-gui` path is retired. Desktop app
distribution is the Tauri bundle; standalone binaries are CLI-only.

FFmpeg and ffprobe (required for core audio workflows). MMO expects
FFmpeg/ffprobe for render, decode, metadata handling, and QA on real-world
sessions. If you only need ontology/docs tooling, those commands can still run
without them.

If FFmpeg is not on PATH, set: MMO_FFMPEG_PATH=/path/to/ffmpeg
MMO_FFPROBE_PATH=/path/to/ffprobe

Confirm your environment: mmo env doctor --format text

Pro notes. If your workflow includes FLAC or WavPack inputs, ffprobe is the
difference between “best effort” and “full metadata.” If you want PDF exports,
install `.[pdf]` so ReportLab is available. NumPy now ships with the base
install, so truth meters work in a healthy source environment without a separate
extra. If you want watch-folder automation, install `.[watch]` so watchdog is
available.
