from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

LOSSLESS_OUTPUT_FORMATS = ("wav", "flac", "wv", "aiff", "alac")
_FFMPEG_ENCODE_ARGS_BY_FORMAT: dict[str, tuple[str, ...]] = {
    "flac": ("-c:a", "flac"),
    "wv": ("-c:a", "wavpack"),
    "aiff": ("-f", "aiff", "-c:a", "pcm_s24be"),
    "alac": ("-c:a", "alac", "-f", "ipod"),
}
_FFMPEG_DETERMINISM_FLAGS: tuple[str, ...] = (
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
)


def supported_output_formats() -> set[str]:
    return set(LOSSLESS_OUTPUT_FORMATS)


def ffmpeg_determinism_flags(*, for_wav: bool = False) -> tuple[str, ...]:
    """Return deterministic ffmpeg flags shared across render outputs."""
    # Keep signature extensible if future WAV-only determinism flags are added.
    _ = for_wav
    return _FFMPEG_DETERMINISM_FLAGS


def _path_arg(path: Path) -> str:
    return path.resolve().as_posix()


def build_ffmpeg_transcode_command(
    ffmpeg_cmd: Sequence[str],
    wav_path: Path,
    out_path: Path,
    format: str,
) -> list[str]:
    """Build deterministic ffmpeg command args for a non-WAV output format."""
    fmt = format.strip().lower()
    encode_args = _FFMPEG_ENCODE_ARGS_BY_FORMAT.get(fmt)
    if encode_args is None:
        supported = ", ".join(sorted(supported_output_formats()))
        raise ValueError(f"Unsupported output format: {format!r}. Supported: {supported}.")
    if not ffmpeg_cmd:
        raise ValueError("ffmpeg command is empty.")

    return list(ffmpeg_cmd) + [
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        _path_arg(wav_path),
        *ffmpeg_determinism_flags(for_wav=False),
        *encode_args,
        _path_arg(out_path),
    ]


def transcode_wav_to_format(
    ffmpeg_cmd: Sequence[str],
    wav_path: Path,
    out_path: Path,
    format: str,
    *,
    command_recorder: list[list[str]] | None = None,
) -> None:
    fmt = format.strip().lower()
    if fmt == "wav":
        raise ValueError("Format 'wav' does not require transcoding.")

    output_path = Path(out_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_transcode_command(ffmpeg_cmd, wav_path, output_path, fmt)
    if command_recorder is not None:
        command_recorder.append(list(command))
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
