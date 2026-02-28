"""Tests for FFmpeg layout-string export mapping."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from mmo.dsp import transcode as _transcode


def test_build_ffmpeg_transcode_command_includes_channel_layout() -> None:
    command = _transcode.build_ffmpeg_transcode_command(
        ["ffmpeg"],
        Path("in.wav"),
        Path("out.flac"),
        "flac",
        channel_layout="FL+FR+FC+LFE+LFE2+SL+SR",
    )
    assert "-channel_layout" in command
    idx = command.index("-channel_layout")
    assert command[idx + 1] == "FL+FR+FC+LFE+LFE2+SL+SR"


def test_ffmpeg_supports_lfe2_layout_strings_detects_support() -> None:
    _transcode._FFMPEG_LFE2_LAYOUT_SUPPORT_CACHE.clear()
    completed = subprocess.CompletedProcess(
        args=["ffmpeg", "-layouts"],
        returncode=0,
        stdout="Individual channels: FL FR FC LFE LFE2",
        stderr="",
    )
    with patch("mmo.dsp.transcode.subprocess.run", return_value=completed):
        assert _transcode.ffmpeg_supports_lfe2_layout_strings(["ffmpeg"]) is True


def test_ffmpeg_supports_lfe2_layout_strings_detects_absence() -> None:
    _transcode._FFMPEG_LFE2_LAYOUT_SUPPORT_CACHE.clear()
    completed = subprocess.CompletedProcess(
        args=["ffmpeg", "-layouts"],
        returncode=0,
        stdout="Individual channels: FL FR FC LFE",
        stderr="",
    )
    with patch("mmo.dsp.transcode.subprocess.run", return_value=completed):
        assert _transcode.ffmpeg_supports_lfe2_layout_strings(["ffmpeg"]) is False
