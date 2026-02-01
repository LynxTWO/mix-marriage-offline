from __future__ import annotations

import subprocess
import sys
from array import array
from pathlib import Path
from typing import Iterator, Sequence


def iter_ffmpeg_float64_samples(
    path: Path, ffmpeg_cmd: Sequence[str], chunk_frames: int = 4096
) -> Iterator[list[float]]:
    if chunk_frames <= 0:
        raise ValueError("chunk_frames must be positive")

    cmd = list(ffmpeg_cmd) + [
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "f64le",
        "-acodec",
        "pcm_f64le",
        "-",
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ValueError(f"ffmpeg failed: {exc}") from exc

    if proc.stdout is None or proc.stderr is None:
        raise ValueError("ffmpeg stdout/stderr not available")

    buffer = b""
    try:
        while True:
            chunk = proc.stdout.read(chunk_frames * 8)
            if not chunk:
                break
            buffer += chunk
            aligned = len(buffer) - (len(buffer) % 8)
            if aligned <= 0:
                continue
            payload = buffer[:aligned]
            buffer = buffer[aligned:]
            samples = array("d")
            samples.frombytes(payload)
            if sys.byteorder == "big":
                samples.byteswap()
            if samples:
                yield samples.tolist()
    finally:
        proc.stdout.close()

    stderr_payload = proc.stderr.read()
    proc.stderr.close()
    returncode = proc.wait()
    if returncode != 0:
        message = stderr_payload.decode("utf-8", errors="replace").strip()
        if message:
            raise ValueError(f"ffmpeg failed: {message}")
        raise ValueError(f"ffmpeg failed with exit code {returncode}")
