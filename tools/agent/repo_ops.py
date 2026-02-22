"""Safe repository operations for the agent REPL harness.

Every function that reads file contents goes through a budget-aware wrapper
(:func:`_read_file_text`) so that file-read and line-read budgets are enforced
uniformly across all primitives.

All returned collections are sorted for determinism.

Public API:
    list_files        Glob files under root, sorted by POSIX path.
    read_slice        Read a line range from a file (budget-tracked).
    grep              Regex search; uses ripgrep if available, Python fallback.
    parse_py_imports  AST-based import extraction from .py files.
    scan_schema_refs  Extract $ref edges from JSON schema files.
    scan_id_refs      Detect MMO canonical ID references in any text file.
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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
    """Extract Python import edges from *path* using the AST.

    Handles both ``import X`` and ``from X import Y`` forms.
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
            module = node.module or ""
            if module:
                edges.add(ImportEdge(rel, module, "ast_import"))

    return sorted(edges)


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

    seen: set[tuple[str, str]] = set()
    edges: list[IdRefEdge] = []

    for pat in _ID_PATTERNS:
        for m in pat.finditer(text):
            matched_id = m.group(0)
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
