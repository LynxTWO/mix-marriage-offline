"""Cross-platform resource resolver for MMO packaged data and cache paths.

Priority for data root:
  1. ``MMO_DATA_ROOT`` env var (power-user override).
  2. Packaged data shipped inside the wheel (``mmo/data/``).
  3. Repo-checkout fallback (only when the checkout layout is detected).

Priority for cache directory:
  1. ``MMO_CACHE_DIR`` env var.
  2. ``<repo_root>/.mmo_cache`` when running from a checkout.
  3. OS-appropriate user cache path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# -- internal helpers --------------------------------------------------------

_REQUIRED_SUBDIRS = ("schemas", "ontology", "presets")


def _has_required_subdirs(root: Path) -> bool:
    return all((root / d).is_dir() for d in _REQUIRED_SUBDIRS)


def _packaged_data_path() -> Optional[Path]:
    """Resolve via importlib.resources (Python 3.9+), else Path(__file__)."""
    try:
        from importlib.resources import files as _ir_files

        candidate = Path(str(_ir_files("mmo") / "data"))
    except Exception:
        candidate = Path(__file__).resolve().parent / "data"

    if candidate.is_dir() and _has_required_subdirs(candidate):
        return candidate
    return None


def _repo_checkout_root() -> Optional[Path]:
    """Walk up from this file looking for a repo-checkout layout."""
    here = Path(__file__).resolve().parent  # src/mmo
    # Expected layout: <repo>/src/mmo/resources.py  ->  parents[2] == repo
    repo_candidate = here.parents[1]
    markers = ("pyproject.toml", "schemas", "ontology", "presets")
    if all((repo_candidate / m).exists() for m in markers):
        return repo_candidate
    return None


# -- public API --------------------------------------------------------------


def data_root() -> Path:
    """Return the directory containing schemas/, ontology/, presets/.

    Raises ``RuntimeError`` if no valid data root can be found.
    """
    # 1. Env override.
    env = os.environ.get("MMO_DATA_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if _has_required_subdirs(p):
            return p
        raise RuntimeError(
            f"MMO_DATA_ROOT={env!r} does not contain the required "
            f"subdirectories: {', '.join(_REQUIRED_SUBDIRS)}"
        )

    # 2. Packaged data.
    pkg = _packaged_data_path()
    if pkg is not None:
        return pkg

    # 3. Repo-checkout fallback.
    repo = _repo_checkout_root()
    if repo is not None:
        return repo

    raise RuntimeError(
        "Cannot locate MMO data files.  Set MMO_DATA_ROOT or reinstall the package."
    )


def schemas_dir() -> Path:
    """Return the directory containing JSON schema files."""
    return data_root() / "schemas"


def ontology_dir() -> Path:
    """Return the directory containing ontology YAML files."""
    return data_root() / "ontology"


def presets_dir() -> Path:
    """Return the directory containing preset JSON files."""
    return data_root() / "presets"


def default_cache_dir() -> Path:
    """Return a suitable cache directory for MMO artefacts.

    Priority:
      1. ``MMO_CACHE_DIR`` env var.
      2. ``<repo_root>/.mmo_cache`` when running from a checkout.
      3. OS-appropriate user cache path.
    """
    env = os.environ.get("MMO_CACHE_DIR")
    if env:
        return Path(env).expanduser().resolve()

    repo = _repo_checkout_root()
    if repo is not None:
        return (repo / ".mmo_cache").resolve()

    return _os_cache_dir()


def _os_cache_dir() -> Path:
    """Return a platform-appropriate user cache directory."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base).resolve() / "mmo" / "Cache"
        return Path.home() / "AppData" / "Local" / "mmo" / "Cache"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "mmo"

    # Linux / other POSIX
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg).resolve() / "mmo"
    return Path.home() / ".cache" / "mmo"
