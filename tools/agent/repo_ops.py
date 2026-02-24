"""Safe repository operations for the agent REPL harness.

Every function that reads file contents goes through a budget-aware wrapper
(:func:`_read_file_text`) so that file-read and line-read budgets are enforced
uniformly across all primitives.

All returned collections are sorted for determinism.

Public API:
    list_files                 Glob files under root, sorted by POSIX path.
    read_slice                 Read a line range from a file (budget-tracked).
    grep                       Regex search; uses ripgrep if available, Python fallback.
    parse_py_imports           AST-based import extraction from .py files (absolute imports only).
    parse_relative_py_imports  AST-based relative import extraction; emits py_import_relative edges.
    resolve_module_to_path     Map a dotted module name to a repo-relative file path.
    resolve_relative_import    Resolve a relative import to an absolute dotted module name.
    scan_schema_refs           Extract $ref edges from JSON schema files.
    scan_id_refs               Detect MMO canonical ID references in any text file.
    build_id_allowlist         Build an allowlist of real IDs from ontology YAML files.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess
from typing import NamedTuple, Optional

from .budgets import Budgets, BudgetExceededError
from .trace import Tracer


# ---------------------------------------------------------------------------
# MMO canonical ID patterns
# Canonical form:  PREFIX.SOMETHING  (uppercase, dot-separated)
# Snake-case aliases from spec: action_, issue_, lock_, layout_, etc.
# ---------------------------------------------------------------------------
_CANONICAL_PREFIXES = (
    "ACTION", "ISSUE", "LAYOUT", "PARAM", "UNIT", "EVID",
    "FEATURE", "ROLE", "GATE", "SPK", "TRANS", "POLICY", "LOCK",
)

_ID_PATTERNS: list[re.Pattern[str]] = [
    # Canonical uppercase dot-notation: ACTION.EQ.BELL_CUT, LAYOUT.2_0, …
    re.compile(
        r"\b(" + "|".join(_CANONICAL_PREFIXES) + r")\.[A-Z0-9][A-Z0-9_.]*"
    ),
    # Snake-case aliases mentioned in the spec
    re.compile(
        r"\b(action|issue|lock|layout|param|unit|evidence|feature|role|gate|downmix)_\w+"
    ),
]

# For allowlist building: match a canonical ID as a complete string
_CANONICAL_ID_EXACT_RE = re.compile(
    r"^("
    + "|".join(_CANONICAL_PREFIXES)
    + r")\.[A-Z0-9][A-Z0-9_.]*$"
)

# For allowlist building: find canonical IDs anywhere in text
_CANONICAL_ID_RE = re.compile(
    r"\b(" + "|".join(_CANONICAL_PREFIXES) + r")\.[A-Z0-9][A-Z0-9_.]*"
)

# ---------------------------------------------------------------------------
# Upgrade 1: import-to-file resolution
# ---------------------------------------------------------------------------

# Relative directories under repo root where Python packages may live.
# Tried in order; first match wins (after priority).
_IMPORT_PREFIX_DIRS: tuple[str, ...] = ("", "src")


# ---------------------------------------------------------------------------
# Relative import support helpers
# ---------------------------------------------------------------------------

def _get_package_parts(src_posix: str) -> list[str]:
    """Return the dotted package path components for *src_posix*.

    Given the POSIX-relative path of a Python source file, strips the
    package prefix directory (``"src/"`` or repo root) and returns the
    directory components that form the package name.

    Examples::

        _get_package_parts("src/mmo/core/plan.py")  # → ["mmo", "core"]
        _get_package_parts("tools/agent/run.py")    # → ["tools", "agent"]

    The search order tries longer prefixes first so that ``src/`` is
    preferred over the empty-prefix fallback.
    """
    # Try non-empty prefixes first (longest-prefix match is more specific).
    for prefix in sorted(_IMPORT_PREFIX_DIRS, key=len, reverse=True):
        if not prefix:
            continue
        prefix_posix = prefix + "/"
        if src_posix.startswith(prefix_posix):
            inner = src_posix[len(prefix_posix):]
            import pathlib as _pathlib
            parts = _pathlib.PurePosixPath(inner).parts
            return list(parts[:-1])  # directory components only, no filename

    # Empty-prefix fallback: file lives directly under the repo root.
    import pathlib as _pathlib
    parts = _pathlib.PurePosixPath(src_posix).parts
    return list(parts[:-1])


def resolve_relative_import(
    src_posix: str,
    level: int,
    module: Optional[str],
) -> Optional[str]:
    """Resolve a Python relative import to an absolute dotted module name.

    Uses the POSIX-relative path of the importing file and the ``level``
    (number of leading dots) to determine the base package, then appends
    *module* to form the resolved name.

    Resolution rules:

    * ``level = 1`` → base is the immediate package of the source file.
    * ``level = 2`` → base is one package level above (``from .. import X``).
    * ``level = N`` → base is ``N - 1`` levels above the package.

    Args:
        src_posix: POSIX-relative path of the importing ``.py`` file
                   (e.g. ``"src/mmo/core/plan.py"``).
        level:     Number of leading dots in the relative import (``>= 1``).
        module:    Module part after the dots (e.g. ``"utils"`` for
                   ``from .utils import X``).  ``None`` or ``""`` when
                   importing directly from the package (``from . import X``).

    Returns:
        Resolved dotted module name (e.g. ``"mmo.core.utils"``), or ``None``
        if resolution fails (e.g. the ascent goes past the package root).

    Examples::

        # from .utils import Foo  in src/mmo/core/plan.py
        resolve_relative_import("src/mmo/core/plan.py", 1, "utils")
        # → "mmo.core.utils"

        # from ..base import Bar  in src/mmo/core/plan.py
        resolve_relative_import("src/mmo/core/plan.py", 2, "base")
        # → "mmo.base"

        # from . import something  in src/mmo/core/plan.py
        resolve_relative_import("src/mmo/core/plan.py", 1, None)
        # → "mmo.core"
    """
    if level <= 0:
        return None

    pkg_parts = _get_package_parts(src_posix)

    # level=1: stay in current package (no ascent needed)
    # level=2: go one package up, etc.
    ascent = level - 1
    if ascent > len(pkg_parts):
        return None  # can't ascend past the root

    base_parts = pkg_parts[: len(pkg_parts) - ascent]

    if module:
        combined = base_parts + module.split(".")
    else:
        combined = base_parts

    if not combined:
        return None

    return ".".join(combined)


# ---------------------------------------------------------------------------
# Named return types
# ---------------------------------------------------------------------------

class GrepHit(NamedTuple):
    """One line matching a grep pattern."""

    file: str
    """POSIX-relative path from repo root."""
    line: int
    """1-based line number."""
    text: str
    """Stripped line content."""


class ImportEdge(NamedTuple):
    """A Python import dependency edge."""

    src: str
    """Source file (POSIX-relative path)."""
    dst: str
    """Imported module (dotted name, e.g. ``mmo.core.render_plan``)."""
    evidence: str
    """Always ``"ast_import"`` for AST-derived edges."""


class SchemaRefEdge(NamedTuple):
    """A JSON schema ``$ref`` edge."""

    src: str
    """Schema file containing the ``$ref`` (POSIX-relative path)."""
    dst: str
    """Resolved destination: another schema file path or ``"<src>#<def_key>"``."""
    evidence: str
    """The raw ``$ref`` string."""


class IdRefEdge(NamedTuple):
    """A reference to an MMO canonical ID found in a text file."""

    src: str
    """File containing the reference (POSIX-relative path)."""
    dst: str
    """The matched ID string (e.g. ``"ACTION.UTILITY.GAIN"``)."""
    evidence: str
    """Up to 80-char snippet surrounding the match."""


class RelativeImportEdge(NamedTuple):
    """A Python relative import dependency edge.

    Produced by :func:`parse_relative_py_imports` for ``from . import X``
    and ``from .X import Y`` style imports.  The ``dst`` is the resolved
    absolute dotted module name when resolution succeeds, or the raw relative
    notation (e.g. ``".utils"``, ``"..base"``) when resolution fails.
    """

    src: str
    """Source file (POSIX-relative path)."""
    dst: str
    """Resolved absolute module name (e.g. ``"mmo.core.utils"``) or raw
    relative notation (e.g. ``".utils"``) when unresolvable."""
    evidence: str
    """Raw relative import notation, e.g. ``".utils"``, ``"..base.foo"``."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _collect_ids_from_yaml_obj(obj: object, ids: set[str]) -> None:
    """Recursively collect canonical MMO ID strings from a YAML-parsed object."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if isinstance(key, str) and _CANONICAL_ID_EXACT_RE.match(key):
                ids.add(key)
            _collect_ids_from_yaml_obj(val, ids)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_ids_from_yaml_obj(item, ids)
    elif isinstance(obj, str) and _CANONICAL_ID_EXACT_RE.match(obj):
        ids.add(obj)


def _read_file_text(
    path: pathlib.Path,
    budgets: Budgets,
    tracer: Tracer,
) -> str:
    """Read a text file, charge budgets, and return its content.

    Returns an empty string (and emits a trace event) on OSError.
    Raises :class:`~budgets.BudgetExceededError` if file or line limits are hit.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        tracer.emit("read_error", error=str(exc), path=str(path))
        return ""
    line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    budgets.charge_file_read(line_count)
    tracer.emit("file_read", lines=line_count, path=str(path))
    return text


def _walk_json_refs(obj: object, refs: list[str]) -> None:
    """Recursively collect all ``$ref`` string values from a JSON object."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "$ref" and isinstance(val, str):
                refs.append(val)
            else:
                _walk_json_refs(val, refs)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json_refs(item, refs)


# ---------------------------------------------------------------------------
# Public primitives
# ---------------------------------------------------------------------------

def list_files(
    root: pathlib.Path,
    pattern: str,
    budgets: Budgets,
    tracer: Tracer,
) -> list[pathlib.Path]:
    """Return all files matching *pattern* under *root*, sorted by POSIX path.

    Charges one logical step. Does **not** count as a file read (no content read).

    Args:
        root: Directory to search recursively.
        pattern: Glob pattern (e.g. ``"*.py"``).
        budgets: Budget tracker; raises on step overflow.
        tracer: Trace sink.

    Returns:
        Sorted list of matching absolute paths.
    """
    budgets.charge_step()
    matches = sorted(root.rglob(pattern), key=lambda p: p.as_posix())
    tracer.emit("list_files", count=len(matches), pattern=pattern, root=str(root))
    return matches


def read_slice(
    path: pathlib.Path,
    start: int,
    end: int,
    budgets: Budgets,
    tracer: Tracer,
) -> str:
    """Read lines ``[start, end)`` from *path* (0-indexed, exclusive end).

    Charges one step plus one file read with the full line count.

    Args:
        path: File to read.
        start: First line index (0-based).
        end: Exclusive end line index.
        budgets: Budget tracker.
        tracer: Trace sink.

    Returns:
        The requested line range joined with newlines.
    """
    budgets.charge_step()
    text = _read_file_text(path, budgets, tracer)
    lines = text.splitlines()
    return "\n".join(lines[start:end])


def grep(
    pattern: str,
    root: pathlib.Path,
    glob: str,
    budgets: Budgets,
    tracer: Tracer,
) -> list[GrepHit]:
    """Search for *pattern* in files matching *glob* under *root*.

    Uses ripgrep (``rg``) if it is on ``$PATH``, otherwise falls back to a
    pure-Python implementation.  Results are sorted by ``(file, line)`` for
    determinism.

    Args:
        pattern: Regular expression pattern.
        root: Directory to search.
        glob: File glob filter (e.g. ``"*.py"``).
        budgets: Budget tracker; raises on step or grep-hit overflow.
        tracer: Trace sink.

    Returns:
        Sorted list of :class:`GrepHit` namedtuples.
    """
    budgets.charge_step()
    hits: list[GrepHit] = []

    # Try ripgrep first
    try:
        result = subprocess.run(
            ["rg", "--line-number", "--no-heading", "-g", glob, "--", pattern, str(root)],
            capture_output=True,
            encoding="utf-8",
            text=True,
        )
        if result.returncode in (0, 1):  # 1 = no matches (not an error)
            for raw in result.stdout.splitlines():
                parts = raw.split(":", 2)
                if len(parts) == 3:
                    fpath, lineno, content = parts
                    try:
                        rel = pathlib.Path(fpath).relative_to(root).as_posix()
                    except ValueError:
                        rel = fpath
                    hits.append(GrepHit(rel, int(lineno), content.strip()))
            hits.sort()
            budgets.charge_grep_hits(len(hits))
            tracer.emit("grep", glob=glob, hits=len(hits), pattern=pattern, tool="rg")
            return hits
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    # Pure-Python fallback
    compiled = re.compile(pattern)
    for path in sorted(root.rglob(glob), key=lambda p: p.as_posix()):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = str(path)
        for i, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line):
                hits.append(GrepHit(rel, i, line.strip()))

    hits.sort()
    budgets.charge_grep_hits(len(hits))
    tracer.emit("grep", glob=glob, hits=len(hits), pattern=pattern, tool="python")
    return hits


def parse_py_imports(
    path: pathlib.Path,
    root: pathlib.Path,
    budgets: Budgets,
    tracer: Tracer,
) -> list[ImportEdge]:
    """Extract **absolute** Python import edges from *path* using the AST.

    Handles both ``import X`` and absolute ``from X import Y`` forms.
    Relative imports (``from . import X``, ``from .X import Y``, etc.) are
    intentionally skipped here — use :func:`parse_relative_py_imports` to
    obtain those as :class:`RelativeImportEdge` namedtuples.

    Returns edges sorted and deduplicated.

    Args:
        path: The ``.py`` file to parse.
        root: Repo root for computing the POSIX-relative ``src`` field.
        budgets: Budget tracker (charges one file read).
        tracer: Trace sink.

    Returns:
        Sorted, deduplicated list of :class:`ImportEdge` namedtuples.
    """
    text = _read_file_text(path, budgets, tracer)
    if not text:
        return []
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = str(path)

    edges: set[ImportEdge] = set()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        tracer.emit("parse_error", kind="syntax", path=rel)
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                edges.add(ImportEdge(rel, alias.name, "ast_import"))
        elif isinstance(node, ast.ImportFrom):
            # Skip relative imports (level > 0): handled by parse_relative_py_imports.
            if (node.level or 0) > 0:
                continue
            module = node.module or ""
            if module:
                edges.add(ImportEdge(rel, module, "ast_import"))

    return sorted(edges)


def parse_relative_py_imports(
    path: pathlib.Path,
    root: pathlib.Path,
    budgets: Budgets,
    tracer: Tracer,
) -> list[RelativeImportEdge]:
    """Extract **relative** Python import edges from *path* using the AST.

    Handles ``from . import X``, ``from .X import Y``, ``from .. import X``,
    and similar relative forms (``ast.ImportFrom`` nodes with ``level >= 1``).

    For each relative import:

    * When ``from .module import X`` (``node.module`` is set): one edge whose
      ``dst`` is the resolved absolute module name (e.g. ``"mmo.core.module"``)
      if resolvable, or the raw relative notation (e.g. ``".module"``) if not.
      The ``evidence`` is always the raw relative notation.

    * When ``from . import X, Y`` (``node.module`` is empty): one edge per
      imported *name*.  Each edge's ``dst`` is the resolved module obtained by
      appending the name to the current package (e.g. ``"mmo.core.X"``), or
      the raw relative notation (e.g. ``".X"``) if unresolvable.

    Budget: charges **one file read** (same as :func:`parse_py_imports`).

    Args:
        path: The ``.py`` file to parse.
        root: Repo root for computing the POSIX-relative ``src`` field.
        budgets: Budget tracker (charges one file read).
        tracer: Trace sink.

    Returns:
        Sorted, deduplicated list of :class:`RelativeImportEdge` namedtuples.
    """
    text = _read_file_text(path, budgets, tracer)
    if not text:
        return []
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = str(path)

    edges: set[RelativeImportEdge] = set()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        tracer.emit("parse_error", kind="syntax", path=rel)
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        level = node.level or 0
        if level <= 0:
            continue  # absolute import — handled by parse_py_imports

        module = node.module or ""
        dots = "." * level

        if module:
            # from .module import X  →  one edge targeting the module
            raw = dots + module
            resolved = resolve_relative_import(rel, level, module)
            dst = resolved if resolved is not None else raw
            edges.add(RelativeImportEdge(rel, dst, raw))
        else:
            # from . import X, Y  →  one edge per imported name
            for alias in node.names:
                name = alias.name
                raw = dots + name
                resolved = resolve_relative_import(rel, level, name)
                dst = resolved if resolved is not None else raw
                edges.add(RelativeImportEdge(rel, dst, raw))

    return sorted(edges)


def resolve_module_to_path(module: str, root: pathlib.Path) -> Optional[str]:
    """Resolve a dotted module name to a repo-relative POSIX file path under *root*.

    Searches for the module file under *root* using these prefix directories:
    ``""`` (root itself) and ``"src"`` (src-layout).

    Resolution priority (lowest wins):
        0. Direct ``.py`` file — e.g. ``src/mmo/core/listen_pack.py``
        1. Package ``__init__.py`` — e.g. ``src/mmo/core/__init__.py``

    Within the same priority tier, shortest POSIX path wins; ties broken
    lexicographically for determinism.  Only filesystem existence checks are
    performed — **no file reads, no budget charges**.

    Args:
        module: Dotted module name (e.g. ``"mmo.core.listen_pack"``).
        root: Repo root directory to search within.

    Returns:
        POSIX-relative path from *root*, or ``None`` if no file found under
        *root* (i.e. the module is a third-party or stdlib package).
    """
    if not module:
        return None
    parts = module.split(".")
    candidates: list[tuple[int, int, str]] = []  # (priority, path_len, posix)

    for prefix in _IMPORT_PREFIX_DIRS:
        base = root / prefix if prefix else root

        # Priority 0: direct .py file  (e.g. mmo/core/listen_pack.py)
        if len(parts) == 1:
            py_file = base / (parts[0] + ".py")
        else:
            py_file = base.joinpath(*parts[:-1], parts[-1] + ".py")
        if py_file.is_file():
            try:
                posix = py_file.relative_to(root).as_posix()
                candidates.append((0, len(posix), posix))
            except ValueError:
                pass

        # Priority 1: package __init__.py  (e.g. mmo/core/__init__.py)
        init_file = base.joinpath(*parts, "__init__.py")
        if init_file.is_file():
            try:
                posix = init_file.relative_to(root).as_posix()
                candidates.append((1, len(posix), posix))
            except ValueError:
                pass

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def build_id_allowlist(
    ontology_root: pathlib.Path,
    budgets: Budgets,
    tracer: Tracer,
) -> frozenset[str]:
    """Build a frozenset of canonical MMO IDs from YAML files under *ontology_root*.

    Parsing strategy:

    * Uses :mod:`yaml` (PyYAML) for structural parsing when available.
    * Falls back to a regex scan of each file on parse failure or
      ``ImportError``.
    * If *ontology_root* does not exist, returns an empty frozenset immediately
      (callers should then fall back to regex mode for ``scan_id_refs``).

    Budget charges: one file read per YAML file scanned.  Stops early if the
    budget is exceeded; warns via the tracer.

    Args:
        ontology_root: Directory containing ``.yaml`` / ``.yml`` files.
        budgets: Budget tracker.
        tracer: Trace sink.

    Returns:
        Frozenset of canonical ID strings.  An empty frozenset means the
        allowlist could not be built — callers should fall back to regex mode.
    """
    if not ontology_root.is_dir():
        tracer.emit(
            "id_allowlist_skip",
            path=str(ontology_root),
            reason="no_ontology_dir",
        )
        return frozenset()

    ids: set[str] = set()
    parse_ok = True

    yaml_files: list[pathlib.Path] = sorted(
        list(ontology_root.rglob("*.yaml")) + list(ontology_root.rglob("*.yml")),
        key=lambda p: p.as_posix(),
    )

    for yaml_path in yaml_files:
        if budgets.is_exceeded:
            break
        try:
            text = _read_file_text(yaml_path, budgets, tracer)
        except BudgetExceededError:
            break
        if not text:
            continue

        try:
            import yaml as _yaml  # noqa: PLC0415

            try:
                data = _yaml.safe_load(text)
                _collect_ids_from_yaml_obj(data, ids)
            except Exception:
                parse_ok = False
                # Fallback: regex scan of raw text
                for m in _CANONICAL_ID_RE.finditer(text):
                    ids.add(m.group(0))
        except ImportError:
            parse_ok = False
            for m in _CANONICAL_ID_RE.finditer(text):
                ids.add(m.group(0))

    tracer.emit(
        "id_allowlist_built",
        count=len(ids),
        parse_ok=parse_ok,
        path=str(ontology_root),
    )
    return frozenset(ids)


def scan_schema_refs(
    path: pathlib.Path,
    root: pathlib.Path,
    budgets: Budgets,
    tracer: Tracer,
) -> list[SchemaRefEdge]:
    """Extract ``$ref`` edges from a JSON schema file.

    Local refs (``#/$defs/…``) produce an intra-file edge whose ``dst`` is
    ``"<rel_path>#<def_key>"``.  Cross-file refs produce an edge whose ``dst``
    is the ref value as-is (e.g. a relative file path).

    Args:
        path: The ``.json`` schema file to parse.
        root: Repo root for computing the POSIX-relative ``src`` field.
        budgets: Budget tracker (charges one file read).
        tracer: Trace sink.

    Returns:
        Sorted, deduplicated list of :class:`SchemaRefEdge` namedtuples.
    """
    text = _read_file_text(path, budgets, tracer)
    if not text:
        return []
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = str(path)

    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        tracer.emit("parse_error", kind="json", path=rel)
        return []

    raw_refs: list[str] = []
    _walk_json_refs(obj, raw_refs)

    edges: set[SchemaRefEdge] = set()
    for ref in raw_refs:
        if ref.startswith("#/"):
            # Local $defs reference: "src#def_key"
            def_key = ref.lstrip("#/").split("/")[-1]
            edges.add(SchemaRefEdge(rel, f"{rel}#{def_key}", ref))
        else:
            # Cross-file or absolute URI reference
            edges.add(SchemaRefEdge(rel, ref, ref))

    return sorted(edges)


def scan_id_refs(
    path: pathlib.Path,
    root: pathlib.Path,
    budgets: Budgets,
    tracer: Tracer,
    allowlist: Optional[frozenset[str]] = None,
) -> list[IdRefEdge]:
    """Scan *path* for MMO canonical ID references.

    Detects both uppercase dot-notation (``ACTION.UTILITY.GAIN``,
    ``LAYOUT.2_0``, etc.) and snake-case aliases (``action_``, ``layout_``, …).

    Each unique ``(file, matched_id)`` pair produces at most one edge.

    Args:
        path: Any text file (``.py``, ``.yaml``, ``.json``, ``.md``, …).
        root: Repo root for computing the POSIX-relative ``src`` field.
        budgets: Budget tracker (charges one file read).
        tracer: Trace sink.
        allowlist: When provided and non-empty, only emit edges for IDs that
            are present in the allowlist.  ``None`` or an empty frozenset uses
            full regex mode (backward-compatible default).

    Returns:
        Sorted, deduplicated list of :class:`IdRefEdge` namedtuples.
    """
    text = _read_file_text(path, budgets, tracer)
    if not text:
        return []
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = str(path)

    use_allowlist = bool(allowlist)
    seen: set[tuple[str, str]] = set()
    edges: list[IdRefEdge] = []

    for pat in _ID_PATTERNS:
        for m in pat.finditer(text):
            matched_id = m.group(0)
            # Allowlist filter: skip IDs not in the allowlist when enabled
            if use_allowlist and matched_id not in allowlist:  # type: ignore[operator]
                continue
            key = (rel, matched_id)
            if key in seen:
                continue
            seen.add(key)
            # Snippet: up to 20 chars before/after match, capped at 80 chars
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 20)
            snippet = text[start:end].replace("\n", " ").strip()[:80]
            edges.append(IdRefEdge(rel, matched_id, snippet))

    return sorted(set(edges))
