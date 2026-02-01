from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional


def resolve_ffmpeg_cmd() -> Optional[List[str]]:
    env_path = os.environ.get("MMO_FFMPEG_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            if candidate.suffix.lower() == ".py":
                return [sys.executable, str(candidate)]
            return [str(candidate)]
        return None

    found = shutil.which("ffmpeg")
    if not found:
        return None
    return [found]
