"""Cross-platform resource resolver for MMO packaged data and cache paths.

Priority for data root:
  1. ``MMO_DATA_ROOT`` env var (power-user override).
  2. Packaged data shipped inside the wheel (``mmo/data/``).
  3. Repo-checkout fallback (only when the checkout layout is detected).

Priority for cache directory:
  1. ``MMO_CACHE_DIR`` env var.
  2. ``<repo_root>/.mmo_cache`` when running from a checkout.
  3. OS-appropriate user cache path.

Priority for temporary directory:
  1. ``MMO_TEMP_DIR`` env var.
  2. ``<os_temp>/mmo_tmp/<pid>``.
  3. ``<repo_root>/.mmo_tmp/<pid>`` when running from a checkout.

Convenience loaders (``load_ontology_yaml``, ``load_schema_json``) resolve the
resource via the priority chain above and always read with UTF-8 encoding.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# -- internal helpers --------------------------------------------------------

_REQUIRED_SUBDIRS = ("schemas", "ontology")
_TEMP_DIR_ERROR_MESSAGE = "MMO temporary directory is unavailable."


@dataclass(frozen=True)
class TempDirSelection:
    path: Path
    root: Path
    source: str
    fallback: bool


def _has_required_subdirs(root: Path) -> bool:
    if not all((root / d).is_dir() for d in _REQUIRED_SUBDIRS):
        return False
    return (root / "ontology" / "presets" / "index.json").is_file()


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
    markers = ("pyproject.toml",)
    if all((repo_candidate / marker).exists() for marker in markers) and _has_required_subdirs(
        repo_candidate
    ):
        return repo_candidate
    return None


# -- public API --------------------------------------------------------------


def data_root() -> Path:
    """Return the directory containing schemas/ and ontology/ resources.

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
            "resource layout: schemas/, ontology/, and ontology/presets/index.json"
        )

    # Normal installs should trust bundled data first.
    # Falling through to checkout files here would hide packaging drift.
    pkg = _packaged_data_path()
    if pkg is not None:
        return pkg

    # Repo fallback keeps local checkout workflows usable without MMO_DATA_ROOT.
    # It stays last so installed builds fail loudly when bundled data is missing.
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
    """Return the canonical directory containing built-in preset JSON files."""
    preset_root = data_root() / "ontology" / "presets"
    if not (preset_root / "index.json").is_file():
        raise RuntimeError(f"MMO preset index is missing from {preset_root}.")
    return preset_root


def plugins_dir() -> Path | None:
    """Return the packaged plugin-manifest directory when available."""
    try:
        root = data_root()
    except RuntimeError:
        return None
    candidate = (root / "plugins").resolve()
    if candidate.is_dir():
        return candidate
    return None


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
        # Checkout-local cache keeps test and dev artifacts inside the repo tree.
        # Installed runs should prefer user cache roots over writing near code.
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


def _ensure_real_directory(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
        resolved = path.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(_TEMP_DIR_ERROR_MESSAGE) from exc

    if not resolved.is_dir():
        raise RuntimeError(_TEMP_DIR_ERROR_MESSAGE)
    probe = resolved / f".mmo_temp_probe_{os.getpid()}"
    try:
        # Fail here before long-running render stages write partial outputs.
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise RuntimeError(_TEMP_DIR_ERROR_MESSAGE) from exc
    finally:
        if probe.exists():
            try:
                probe.unlink()
            except OSError:
                pass
    return resolved


def _os_temp_root() -> Path:
    base = Path(tempfile.gettempdir()).expanduser()
    pid_text = str(os.getpid())
    if base.name == pid_text and base.parent.name == "mmo_tmp":
        return base.parent
    if base.name == "mmo_tmp":
        return base
    return base / "mmo_tmp"


def _temp_dir_candidates() -> list[tuple[str, Path, Path]]:
    candidates: list[tuple[str, Path, Path]] = []
    env = os.environ.get("MMO_TEMP_DIR")
    if env:
        env_path = Path(env).expanduser()
        candidates.append(("env:MMO_TEMP_DIR", env_path, env_path))

    # Prefer per-process OS temp before repo-local temp so parallel runs do not
    # fight over one shared checkout directory unless every earlier option fails.
    os_temp_root = _os_temp_root()
    candidates.append(("os_temp", os_temp_root / str(os.getpid()), os_temp_root))

    repo = _repo_checkout_root()
    if repo is not None:
        repo_temp_root = repo / ".mmo_tmp"
        candidates.append(("repo_local", repo_temp_root / str(os.getpid()), repo_temp_root))

    return candidates


def temp_dir_selection() -> TempDirSelection:
    for index, (source, candidate_path, candidate_root) in enumerate(_temp_dir_candidates()):
        try:
            resolved = _ensure_real_directory(candidate_path)
        except RuntimeError:
            continue
        return TempDirSelection(
            path=resolved,
            root=candidate_root.resolve(),
            source=source,
            fallback=index > 0,
        )
    raise RuntimeError(_TEMP_DIR_ERROR_MESSAGE)


def default_temp_dir() -> Path:
    """Return a writable temporary directory selected from ordered candidates."""
    return temp_dir_selection().path


def temp_dir() -> Path:
    """Alias for :func:`default_temp_dir`."""
    return default_temp_dir()


# -- convenience loaders -----------------------------------------------------


def load_ontology_yaml(filename: str) -> Any:
    """Load and parse a YAML file from the ontology directory.

    ``filename`` may include sub-directories, e.g. ``"policies/gates.yaml"``.
    The file is located via the established priority chain (env override,
    packaged wheel data, repo-checkout fallback) and read as UTF-8.

    Raises ``RuntimeError`` if the ontology directory cannot be resolved.
    Raises ``FileNotFoundError`` if the file does not exist within the directory.
    Raises ``ImportError`` if PyYAML is not installed.
    """
    try:
        import yaml  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required to load ontology YAML files.  "
            "Install it with: pip install PyYAML"
        ) from exc

    path = ontology_dir() / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Ontology file not found: {path}"
        )
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_schema_json(filename: str) -> Any:
    """Load and parse a JSON schema file from the schemas directory.

    ``filename`` may include sub-directories, e.g. ``"report.schema.json"``.
    The file is located via the established priority chain (env override,
    packaged wheel data, repo-checkout fallback) and read as UTF-8.

    Raises ``RuntimeError`` if the schemas directory cannot be resolved.
    Raises ``FileNotFoundError`` if the file does not exist within the directory.
    """
    path = schemas_dir() / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Schema file not found: {path}"
        )
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)
