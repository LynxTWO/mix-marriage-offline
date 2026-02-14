"""Render per-bus-group audition WAV bounces from a classified stems_map.

Deterministic renderer that creates short WAV previews grouped by bus_group,
plus a stable manifest.json describing all outputs and any warnings.

Slug rules for output filenames:
  - Lowercase the bus_group_id.
  - Replace any character that is not [a-z0-9] with underscore.
  - Collapse consecutive underscores to one.
  - Strip leading/trailing underscores.
  - Example: "DRUMS" -> "drums", "FX/SEND" -> "fx_send".

Rendering rules:
  - Groups sorted by bus_group_id (lexicographic).
  - Stems within a group sorted by rel_path (lexicographic).
  - Target sample rate + channels chosen from the first renderable file in
    the group (by sorted order).
  - Mono files upmixed to stereo by duplicating the channel.
  - Files with >2 channels or mismatched sample rate are skipped with warning.
  - Frames read as int16, accumulated in int32, clamped to int16 on output.
  - Source shorter than segment_seconds is padded with silence.
  - Source longer than segment_seconds is truncated.
"""

from __future__ import annotations

import array
import json
import re
import wave
from pathlib import Path, PurePosixPath
from typing import Any


def _slug(bus_group_id: str) -> str:
    """Deterministic slug from a bus_group_id for filenames."""
    result = bus_group_id.lower()
    result = re.sub(r"[^a-z0-9]", "_", result)
    result = re.sub(r"_+", "_", result)
    return result.strip("_") or "unknown"


def _posix(p: Path) -> str:
    """Normalise path to forward slashes."""
    return PurePosixPath(p).as_posix()


def _read_wav_frames(
    wav_path: Path,
    segment_frames: int,
    target_rate: int,
    target_channels: int,
) -> tuple[list[int] | None, str | None]:
    """Read up to *segment_frames* from a WAV, returning int16 samples or skip reason.

    Returns (samples_list, None) on success or (None, reason_string) on skip.
    The returned list has exactly segment_frames * target_channels int16 values.
    """
    try:
        with wave.open(str(wav_path), "rb") as wf:
            src_channels = wf.getnchannels()
            src_rate = wf.getframerate()
            src_width = wf.getsampwidth()

            if src_width != 2:
                return None, f"unsupported sample width {src_width} (need 16-bit)"

            if src_rate != target_rate:
                return None, f"sample rate {src_rate} != target {target_rate}"

            if src_channels > 2:
                return None, f"unsupported channel count {src_channels} (max 2)"

            available = wf.getnframes()
            read_count = min(available, segment_frames)
            raw = wf.readframes(read_count)
    except Exception as exc:
        return None, f"read error: {exc}"

    samples = array.array("h")
    samples.frombytes(raw)

    total_needed = segment_frames * target_channels
    out: list[int] = [0] * total_needed

    for i in range(read_count):
        if src_channels == 1 and target_channels == 2:
            val = samples[i]
            out[i * 2] = val
            out[i * 2 + 1] = val
        elif src_channels == 2 and target_channels == 2:
            out[i * 2] = samples[i * 2]
            out[i * 2 + 1] = samples[i * 2 + 1]
        elif src_channels == 1 and target_channels == 1:
            out[i] = samples[i]
        elif src_channels == 2 and target_channels == 1:
            out[i] = (samples[i * 2] + samples[i * 2 + 1]) // 2
        else:
            return None, f"channel mapping {src_channels}->{target_channels} unsupported"

    return out, None


def _probe_wav(wav_path: Path) -> tuple[int, int, int] | None:
    """Return (channels, sample_rate, sample_width) or None if unreadable."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            return wf.getnchannels(), wf.getframerate(), wf.getsampwidth()
    except Exception:
        return None


def _clamp16(value: int) -> int:
    if value > 32767:
        return 32767
    if value < -32768:
        return -32768
    return value


def render_audition_pack(
    stems_map: dict[str, Any],
    stems_dir: Path,
    out_dir: Path,
    *,
    segment_seconds: float = 30.0,
) -> dict[str, Any]:
    """Render per-bus-group audition WAVs and return a manifest dict.

    Parameters
    ----------
    stems_map : dict
        A validated stems_map payload (version 0.1.0).
    stems_dir : Path
        Root directory where stem audio files live.
    out_dir : Path
        Parent output directory.  Files are written to out_dir/stems_auditions/.
    segment_seconds : float
        Duration of each audition bounce in seconds (default 30).

    Returns
    -------
    dict
        The manifest payload (also written as manifest.json).
        Includes ``ok: True`` on success or ``ok: False`` with error details.
    """
    version = stems_map.get("version")
    if version != "0.1.0":
        raise ValueError(f"Unsupported stems_map version: {version!r}")

    assignments = stems_map.get("assignments")
    if not isinstance(assignments, list):
        raise ValueError("stems_map has no 'assignments' list")

    audition_dir = out_dir / "stems_auditions"
    audition_dir.mkdir(parents=True, exist_ok=True)

    # Group assignments by bus_group
    groups: dict[str, list[dict[str, Any]]] = {}
    for assignment in assignments:
        bg = assignment.get("bus_group")
        if not isinstance(bg, str) or not bg:
            bg = "_UNGROUPED"
        groups.setdefault(bg, []).append(assignment)

    # Sort groups by bus_group_id, stems within each group by rel_path
    sorted_group_ids = sorted(groups.keys())
    for gid in sorted_group_ids:
        groups[gid] = sorted(
            groups[gid],
            key=lambda a: (a.get("rel_path", ""), a.get("file_id", "")),
        )

    manifest_groups: list[dict[str, Any]] = []
    all_warnings: list[str] = []
    rendered_count = 0
    total_missing = 0

    for bus_group_id in sorted_group_ids:
        group_assignments = groups[bus_group_id]
        slug = _slug(bus_group_id)
        wav_name = f"{slug}.wav"
        wav_path = audition_dir / wav_name

        stems_included: list[str] = []
        stems_missing: list[str] = []
        stems_skipped: list[dict[str, str]] = []
        renderable_paths: list[tuple[str, Path]] = []

        target_rate: int | None = None
        target_channels: int | None = None

        for a in group_assignments:
            rel = a.get("rel_path", "")
            fpath = stems_dir / rel
            if not fpath.is_file():
                stems_missing.append(rel)
                total_missing += 1
                all_warnings.append(
                    f"Missing file: {rel} (group {bus_group_id})"
                )
                continue
            info = _probe_wav(fpath)
            if info is None:
                stems_skipped.append({
                    "rel_path": rel,
                    "reason": "unreadable WAV",
                })
                all_warnings.append(
                    f"Skipped unreadable: {rel} (group {bus_group_id})"
                )
                continue
            ch, rate, width = info
            if width != 2:
                stems_skipped.append({
                    "rel_path": rel,
                    "reason": f"unsupported sample width {width}",
                })
                all_warnings.append(
                    f"Skipped non-16-bit: {rel} (group {bus_group_id})"
                )
                continue
            if ch > 2:
                stems_skipped.append({
                    "rel_path": rel,
                    "reason": f"unsupported channel count {ch}",
                })
                all_warnings.append(
                    f"Skipped >2 channels: {rel} (group {bus_group_id})"
                )
                continue

            # Set target from first renderable
            if target_rate is None:
                target_rate = rate
                target_channels = ch if ch <= 2 else 2

            # Check sample rate match
            if rate != target_rate:
                stems_skipped.append({
                    "rel_path": rel,
                    "reason": f"sample rate {rate} != target {target_rate}",
                })
                all_warnings.append(
                    f"Skipped rate mismatch: {rel} ({rate} != {target_rate}, "
                    f"group {bus_group_id})"
                )
                continue

            renderable_paths.append((rel, fpath))
            stems_included.append(rel)

        group_entry: dict[str, Any] = {
            "bus_group_id": bus_group_id,
            "output_wav": _posix(Path(wav_name)),
            "stems_included": sorted(stems_included),
            "stems_missing": sorted(stems_missing),
            "stems_skipped_mismatch": sorted(
                stems_skipped, key=lambda s: s.get("rel_path", "")
            ),
        }

        if not renderable_paths or target_rate is None or target_channels is None:
            all_warnings.append(
                f"Group {bus_group_id}: no renderable stems"
            )
            group_entry["output_wav"] = ""
            manifest_groups.append(group_entry)
            continue

        # Mix stems
        segment_frames = int(segment_seconds * target_rate)
        total_samples = segment_frames * target_channels
        mix_buf: list[int] = [0] * total_samples  # int32 accumulator

        read_failures: list[str] = []
        for rel, fpath in renderable_paths:
            frames, skip_reason = _read_wav_frames(
                fpath, segment_frames, target_rate, target_channels,
            )
            if frames is None:
                read_failures.append(rel)
                stems_skipped.append({
                    "rel_path": rel,
                    "reason": skip_reason or "unknown read error",
                })
                all_warnings.append(
                    f"Read failed: {rel} ({skip_reason}, group {bus_group_id})"
                )
                continue

            for j in range(total_samples):
                mix_buf[j] += frames[j]

        # Remove read failures from included list
        if read_failures:
            fail_set = set(read_failures)
            stems_included = [s for s in stems_included if s not in fail_set]

        # Clamp to int16
        clamped = array.array("h", (_clamp16(v) for v in mix_buf))

        # Write output WAV
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(target_channels)
            wf.setsampwidth(2)
            wf.setframerate(target_rate)
            wf.writeframes(clamped.tobytes())

        # Update entry with final included/skipped lists
        group_entry["stems_included"] = sorted(stems_included)
        group_entry["stems_skipped_mismatch"] = sorted(
            stems_skipped, key=lambda s: s.get("rel_path", "")
        )
        manifest_groups.append(group_entry)
        rendered_count += 1

    manifest: dict[str, Any] = {
        "segment_seconds": segment_seconds,
        "stems_dir": _posix(stems_dir),
        "groups": sorted(manifest_groups, key=lambda g: g["bus_group_id"]),
        "warnings": sorted(all_warnings),
        "rendered_groups_count": rendered_count,
        "attempted_groups_count": len(sorted_group_ids),
    }

    if rendered_count == 0:
        return {
            "ok": False,
            "error_code": "NO_RENDERABLE_GROUPS",
            "missing_files_count": total_missing,
            "groups_attempted_count": len(sorted_group_ids),
        }

    # Write manifest
    manifest_path = audition_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "ok": True,
        "out_dir": _posix(audition_dir),
        "manifest_path": _posix(manifest_path),
        "manifest": manifest,
        "rendered_groups_count": rendered_count,
        "attempted_groups_count": len(sorted_group_ids),
        "missing_files_count": total_missing,
        "skipped_mismatch_count": sum(
            len(g.get("stems_skipped_mismatch", []))
            for g in manifest_groups
        ),
    }
