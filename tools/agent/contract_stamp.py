"""Graph contract stamp for the agent REPL harness.

The contract stamp binds a graph artifact to the git commit that produced it,
the scope parameters used, and the effective budget configuration.  It lets
other tools and agents verify they are operating on the correct graph before
making any changes.

Default stamp location: ``.mmo_agent/graph_contract.json`` under the repo root.

Stamp fields (all deterministic, no timestamps)
-----------------------------------------------
- ``version``          (int)  — Schema version; currently 1.
- ``repo_root``        (str)  — Absolute path to the repo root.  Stored as an
  absolute path because a repo-relative path for the root itself would always
  be ``"."`` (not useful for cross-run validation).
- ``git_sha``          (str)  — HEAD commit SHA, or ``"unknown"`` when git is
  unavailable.
- ``git_available``    (bool) — False when git could not be invoked.
- ``graph_path``       (str)  — Graph artifact path, relative to repo_root
  (POSIX separators).
- ``trace_path``       (str)  — Trace NDJSON path, relative to repo_root.
- ``graph_sha256``     (str)  — SHA-256 hex digest of the saved graph JSON.
- ``graph_node_count`` (int)
- ``graph_edge_count`` (int)
- ``run_mode``         (str)  — One of ``"graph-only"``, ``"plan"``,
  ``"patch"``.
- ``scope``            (dict) — preset, scope_paths, diff, diff_cap,
  id_allowlist flags used for the run.
- ``budgets``          (dict) — Effective :class:`BudgetConfig` values.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import subprocess
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

_STAMP_VERSION = 1


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ContractStamp:
    """Immutable provenance record for one graph build.

    All fields are plain JSON-serialisable types so the stamp can be round-
    tripped through :func:`write_contract_stamp` / :func:`read_contract_stamp`
    without any custom encoders.
    """

    version: int
    """Stamp schema version (currently 1)."""

    repo_root: str
    """Absolute path to the repository root (string for JSON portability)."""

    git_sha: str
    """HEAD commit SHA or ``"unknown"``."""

    git_available: bool
    """False when git could not be invoked during the run."""

    graph_path: str
    """Graph artifact path, POSIX-relative to repo_root."""

    trace_path: str
    """Trace NDJSON path, POSIX-relative to repo_root."""

    graph_sha256: str
    """SHA-256 hex digest of the saved graph JSON file."""

    graph_node_count: int
    graph_edge_count: int

    run_mode: str
    """One of ``"graph-only"``, ``"plan"``, ``"patch"``."""

    scope: dict
    """Scope parameters used: preset, scope_paths, diff, diff_cap, id_allowlist."""

    budgets: dict
    """Effective BudgetConfig field values for this run."""


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def get_git_head_sha(root: pathlib.Path) -> str:
    """Return the HEAD commit SHA, or ``"unknown"`` if git is unavailable.

    Emits a warning to stderr when git cannot be found or the command fails.

    Args:
        root: The directory to run ``git rev-parse HEAD`` in.

    Returns:
        40-character hex SHA string, or ``"unknown"``.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            if sha:
                return sha
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    print(
        "[WARNING] git is unavailable or rev-parse HEAD failed; "
        "stamp will have git_available=false.",
        file=sys.stderr,
    )
    return "unknown"


# ---------------------------------------------------------------------------
# SHA-256 helper
# ---------------------------------------------------------------------------

def _compute_sha256(path: pathlib.Path) -> str:
    """Return the SHA-256 hex digest of the file at *path*."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Stamp construction
# ---------------------------------------------------------------------------

def make_contract_stamp(
    *,
    repo_root: pathlib.Path,
    git_sha: str,
    git_available: bool,
    graph_path: pathlib.Path,
    trace_path: pathlib.Path,
    graph: dict,
    run_mode: str,
    scope: dict,
    budgets_config: dict,
) -> ContractStamp:
    """Construct a :class:`ContractStamp` from run parameters.

    *graph_path* must already exist on disk so its SHA-256 can be computed.

    Args:
        repo_root: Absolute path to the repository root.
        git_sha: HEAD SHA (from :func:`get_git_head_sha`).
        git_available: Whether git was reachable.
        graph_path: Path to the saved graph artifact (used to compute sha256).
        trace_path: Path to the trace NDJSON file.
        graph: The graph dict (provides node/edge counts).
        run_mode: One of ``"graph-only"``, ``"plan"``, ``"patch"``.
        scope: Dict of scope parameters used during the run.
        budgets_config: Dict of BudgetConfig fields (e.g. from
            ``dataclasses.asdict(config)``).

    Returns:
        A populated :class:`ContractStamp`.
    """
    resolved_root = repo_root.resolve()

    graph_sha256 = _compute_sha256(graph_path) if graph_path.exists() else ""

    def _rel(p: pathlib.Path) -> str:
        """Return *p* relative to *resolved_root* as a POSIX string, or abs."""
        try:
            return p.resolve().relative_to(resolved_root).as_posix()
        except ValueError:
            return str(p)

    # Ensure scope_paths is sorted for determinism
    scope_normalised = dict(scope)
    if isinstance(scope_normalised.get("scope_paths"), list):
        scope_normalised["scope_paths"] = sorted(scope_normalised["scope_paths"])

    return ContractStamp(
        version=_STAMP_VERSION,
        repo_root=str(resolved_root),
        git_sha=git_sha,
        git_available=git_available,
        graph_path=_rel(graph_path),
        trace_path=_rel(trace_path),
        graph_sha256=graph_sha256,
        graph_node_count=len(graph.get("nodes", [])),
        graph_edge_count=len(graph.get("edges", [])),
        run_mode=run_mode,
        scope=scope_normalised,
        budgets=budgets_config,
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def write_contract_stamp(path: pathlib.Path, stamp: ContractStamp) -> None:
    """Write *stamp* to *path* as deterministic JSON (sorted keys, 2-space indent).

    Creates parent directories as needed.

    Args:
        path: Destination ``.json`` file path.
        stamp: The stamp to serialise.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dataclasses.asdict(stamp), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_contract_stamp(path: pathlib.Path) -> ContractStamp:
    """Read and deserialise a contract stamp from *path*.

    Args:
        path: Path to a ``.json`` stamp file written by :func:`write_contract_stamp`.

    Returns:
        :class:`ContractStamp` populated from the file.

    Raises:
        OSError: If the file cannot be read.
        json.JSONDecodeError: If the file is not valid JSON.
        TypeError: If required fields are missing or have wrong types.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return ContractStamp(**raw)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_contract_stamp(
    stamp: ContractStamp,
    repo_root: pathlib.Path,
    graph_path: pathlib.Path,
) -> list[str]:
    """Validate a stamp against the current repository state.

    Performs four checks:

    1. ``stamp.repo_root`` matches the resolved *repo_root*.
    2. ``stamp.git_sha`` matches the current HEAD (when
       ``stamp.git_available`` is True and git is reachable).
    3. The graph file at *graph_path* exists and its SHA-256 matches
       ``stamp.graph_sha256``.
    4. ``stamp.budgets`` is a non-empty dict.

    Args:
        stamp: The stamp to validate.
        repo_root: Actual repository root to compare against.
        graph_path: Path to the graph artifact to verify.

    Returns:
        List of human-readable validation error strings.
        An **empty list** means the stamp is fully valid.
    """
    errors: list[str] = []

    # 1. Repo root match
    actual_root = str(repo_root.resolve())
    if stamp.repo_root != actual_root:
        errors.append(
            f"repo_root mismatch: stamp has {stamp.repo_root!r}, "
            f"actual is {actual_root!r}"
        )

    # 2. Git SHA match (only when git was available when the stamp was written)
    if stamp.git_available:
        current_sha = get_git_head_sha(repo_root)
        if current_sha != "unknown" and current_sha != stamp.git_sha:
            errors.append(
                f"git_sha mismatch: stamp has {stamp.git_sha!r}, "
                f"HEAD is now {current_sha!r}"
            )

    # 3. Graph file present and SHA matches
    if not graph_path.exists():
        errors.append(f"graph_path does not exist: {graph_path}")
    else:
        actual_sha = _compute_sha256(graph_path)
        if actual_sha != stamp.graph_sha256:
            errors.append(
                f"graph_sha256 mismatch: stamp has {stamp.graph_sha256[:12]}…, "
                f"actual is {actual_sha[:12]}…"
            )

    # 4. Budgets present
    if not stamp.budgets:
        errors.append("stamp.budgets is empty or missing")

    return errors
