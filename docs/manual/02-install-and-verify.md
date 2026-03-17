# Install and verify

Start with the packaged desktop app unless you specifically want the CLI or a
source checkout.

## Packaged desktop path

Download the release asset for your OS from GitHub Releases:

- Windows: installer
- macOS: app bundle
- Linux: AppImage

Also available in the release:

- standalone CLI binaries for automation or terminal-heavy workflows

After install:

1. Launch MMO.
2. If you want a quick health check, run `Doctor`.
3. Choose your `stems folder`.
4. Choose your `workspace`.

Plain-language reminder:

- `stems folder`: the exported audio tracks from your DAW
- `workspace`: MMO's session notebook where it writes every report, scene,
  render, and receipt

If the desktop app opens but no stage will run, that usually means the packaged
audio helper did not launch correctly. Run `Doctor` first. If `Doctor` also
fails, reinstall the release build.

## Source and CLI path

MMO requires Python `3.12+` for source installs.

Install the base package:

```sh
pip install .
```

Optional extras:

```sh
pip install .[pdf]
pip install .[watch]
```

## Runtime tools

For real audio work, MMO expects:

- `ffmpeg`
- `ffprobe`

Why those matter:

- MMO uses them like a translator and tape machine. They help MMO read audio
  files, inspect metadata, and write delivery files safely.

If they are not on `PATH`, set:

- `MMO_FFMPEG_PATH=/path/to/ffmpeg`
- `MMO_FFPROBE_PATH=/path/to/ffprobe`

## Verify the install

CLI check:

```sh
mmo --help
mmo env doctor --format text
```

Desktop check:

1. Launch the app.
2. Run `Doctor`.
3. Confirm the doctor report says the packaged sidecar, plugin registry, and
   environment checks are healthy.

## Optional source extras

- `.[pdf]`: needed only for PDF export
- `.[watch]`: needed only for watch-folder automation

NumPy is part of the base install now, so core meters do not need a separate
extra in a healthy source environment.
