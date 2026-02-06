from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

LOSSLESS_OUTPUT_FORMATS = ("wav", "flac", "wv")
_CODEC_BY_FORMAT = {
    "flac": "flac",
    "wv": "wavpack",
}


def supported_output_formats() -> set[str]:
    return set(LOSSLESS_OUTPUT_FORMATS)


def transcode_wav_to_format(
    ffmpeg_cmd: Sequence[str],
    wav_path: Path,
    out_path: Path,
    format: str,
) -> None:
    fmt = format.strip().lower()
    if fmt == "wav":
        raise ValueError("Format 'wav' does not require transcoding.")

    codec = _CODEC_BY_FORMAT.get(fmt)
    if codec is None:
        supported = ", ".join(sorted(supported_output_formats()))
        raise ValueError(f"Unsupported output format: {format!r}. Supported: {supported}.")

    if not ffmpeg_cmd:
        raise ValueError("ffmpeg command is empty.")

    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = list(ffmpeg_cmd) + [
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(wav_path),
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-metadata",
        "creation_time=",
        "-metadata",
        "encoder=",
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-threads",
        "1",
        "-c:a",
        codec,
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return

    message = completed.stderr.strip() or completed.stdout.strip()
    if message:
        raise ValueError(f"ffmpeg encode failed: {message}")
    raise ValueError(f"ffmpeg encode failed with exit code {completed.returncode}")
