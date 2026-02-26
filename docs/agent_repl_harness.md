# Agent REPL Harness

**Location:** `tools/agent/`
**Tests:** `tests/test_agent_harness.py`

---

## Mental model: the repo as a dependency graph

Before an AI agent edits anything, it must understand the repo's dependency
structure. The harness materialises that structure as a concrete JSON artifact:
a directed graph where every node is a file (or a canonical ID) and every edge
is a typed dependency (Python import, resolved import file, JSON schema `$ref`,
or MMO canonical ID reference).

**The contract:** no file edits may start until a valid graph artifact exists.
`patch` mode enforces this by refusing to proceed without the artifact.

```
Locate → Graph → Plan → Patch (optional, guarded)
  ↑         ↑       ↑       ↑
  read    build   inspect  edit
```

---

## Modules

| Module               | Role |
|----------------------|------|
| `budgets.py`         | Hard budget caps; raises `BudgetExceededError` on overflow. |
| `trace.py`           | Structured NDJSON trace log for every operation. |
| `repo_ops.py`        | Safe primitives: `list_files`, `read_slice`, `grep`, `parse_py_imports`, `parse_relative_py_imports`, `resolve_module_to_path`, `resolve_relative_import`, `scan_schema_refs`, `scan_id_refs`, `build_id_allowlist`. |
| `graph_build.py`     | Orchestrates a full graph build; writes deterministic JSON.  Also exposes `build_graph_from_files()` for the seed-first path. |
| `validate_graph.py`  | `validate_graph(graph) → list[str]` — validates a graph dict against `schemas/agent_graph.schema.json`. |
| `scoping.py`         | Scope presets, diff BFS expansion, graph filtering. |
| `diff_seed_first.py` | Seed-first BFS expansion: cheap AST + schema-ref crawl from changed files. |
| `explain.py`         | Edge-path explanations: shortest path + scope justifications. |
| `contract_stamp.py`  | Contract stamp: commit-bound provenance for graph artifacts (PR A). |
| `index_build.py`     | Hot-path index: fast-lookup artifact derived from graph (PR B). |
| `run.py`             | CLI entrypoint (modes: `graph-only`, `plan`, `patch`, `explain`, `explain-scope`). |

---

## REPL primitives

### `list_files(root, pattern, budgets, tracer)`

Glob files under `root` matching `pattern` (e.g. `"*.py"`).
Returns a sorted list of absolute paths.  Charges **one step**.

### `read_slice(path, start, end, budgets, tracer)`

Read lines `[start, end)` (0-indexed) from a file.
Charges **one step + one file read**.

### `grep(pattern, root, glob, budgets, tracer)`

Regex search across files matching `glob`.  Uses `rg` if available, pure-Python
otherwise.  Charges **one step + grep hits**.

### `parse_py_imports(path, root, budgets, tracer)`

AST-based Python import extraction.  Returns `ImportEdge` namedtuples with
`(src, dst, evidence="ast_import")`.  Charges **one file read**.

### `resolve_module_to_path(module, root)` *(Upgrade 1)*

Best-effort resolver: maps a dotted module name to a repo-relative file path.

- Searches under `root` itself and `root/src/` (src-layout).
- Resolution priority: direct `.py` file (priority 0) > package `__init__.py`
  (priority 1).  Within the same tier, shortest path then lex order wins.
- Only performs filesystem existence checks — **no file reads, no budget charges**.
- Returns `None` for stdlib or third-party modules not found under `root`.

### `resolve_relative_import(src_posix, level, module)` *(new)*

Resolves a Python relative import to an absolute dotted module name.

```python
# from .utils import Foo  in src/mmo/core/plan.py
resolve_relative_import("src/mmo/core/plan.py", 1, "utils")
# → "mmo.core.utils"

# from ..base import Bar  in src/mmo/core/plan.py
resolve_relative_import("src/mmo/core/plan.py", 2, "base")
# → "mmo.base"

# from . import something  in src/mmo/core/plan.py
resolve_relative_import("src/mmo/core/plan.py", 1, None)
# → "mmo.core"
```

- `level = 1` → base is the immediate package of the source file.
- `level = N` → base is `N − 1` levels above the package.
- Returns `None` when ascent would go past the package root.
- No file reads, no budget charges.

### `parse_relative_py_imports(path, root, budgets, tracer)` *(new)*

Extracts `py_import_relative` edges from relative imports in a `.py` file.

- Handles `from . import X`, `from .X import Y`, `from .. import X`, etc.
- `dst` is the resolved absolute module name when resolvable, or the raw
  relative notation (e.g. `".utils"`) otherwise.
- `evidence` is always the raw relative notation (e.g. `".utils"`, `"..base"`).
- Charges **one file read** (independent of `parse_py_imports`).
- Returns sorted, deduplicated `RelativeImportEdge` namedtuples.

### `scan_schema_refs(path, root, budgets, tracer)`

Recursively walks a JSON file and extracts every `$ref` value.
Local refs (`#/$defs/…`) produce intra-file edges; cross-file refs produce
inter-file edges.  Charges **one file read**.

### `scan_id_refs(path, root, budgets, tracer, allowlist=None)` *(enhanced)*

Regex scan for MMO canonical IDs (e.g. `ACTION.UTILITY.GAIN`, `LAYOUT.2_0`,
`ROLE.DRUMS.KICK`) and snake-case aliases (`action_`, `layout_`, …).
Returns `IdRefEdge` namedtuples.  Charges **one file read**.

When `allowlist` is a non-empty `frozenset[str]`, only IDs present in the
allowlist are emitted (allowlist mode).  `None` or an empty frozenset uses full
regex mode (backward-compatible default).

### `build_id_allowlist(ontology_root, budgets, tracer)` *(Upgrade 2)*

Builds a `frozenset[str]` of canonical MMO IDs from YAML files under
`ontology_root`.

- Uses PyYAML (`yaml.safe_load`) for structural parsing when available.
- Falls back to a regex scan on parse failure or `ImportError`.
- Returns an empty frozenset if `ontology_root` does not exist (triggers
  fallback to regex mode in `build_graph`).
- Budget charges: one file read per YAML file scanned.

---

## Running the harness

Run from the **repo root**:

```bash
# 1. Graph-only — inspect the dependency graph, no edits
python -m tools.agent.run graph-only

# 2. Plan mode — graph + a JSON plan of top files to examine
python -m tools.agent.run plan --out sandbox_tmp/

# 3. Patch mode — reads existing graph, refuses without it
python -m tools.agent.run patch --graph sandbox_tmp/agent_graph.json

# 4. Scoped to a subdirectory
python -m tools.agent.run graph-only --root src/mmo/core/

# 5. Override budgets
python -m tools.agent.run graph-only --max-file-reads 200 --max-total-lines 50000
```

Exit codes:

- `0` — success
- `1` — budget cap hit or other error
- `2` — refused (patch mode without a valid graph artifact)
- `3` — refused (patch mode: contract stamp validation failed)

---

## Scoping, presets, and diff mode *(Upgrade 3)*

### Named presets (`--preset`)

```bash
# Only scan src/mmo/core/
python -m tools.agent.run graph-only --preset core

# Only scan schemas/
python -m tools.agent.run graph-only --preset schemas

# Only scan ontology/
python -m tools.agent.run graph-only --preset ontology

# Only scan CLI entrypoints
python -m tools.agent.run graph-only --preset cli
```

| Preset | Paths included |
|--------|---------------|
| `core` | `src/mmo/core` |
| `schemas` | `schemas` |
| `ontology` | `ontology` |
| `cli` | `src/mmo/cli.py`, `src/mmo/cli_commands` |

### Explicit scope paths (`--scope`, repeatable)

```bash
# Scope to one directory
python -m tools.agent.run graph-only --scope src/mmo/core

# Scope to multiple directories
python -m tools.agent.run graph-only --scope src/mmo/core --scope schemas
```

`--scope` and `--preset` can be combined (their path lists are merged).

### Diff-focused mode (`--diff`)

`--diff` restricts the output graph to files changed vs HEAD plus their
graph neighbours, expanded breadth-first up to `--diff-cap` nodes (default 50).

```bash
# Show graph for files changed since last commit + their neighbours
python -m tools.agent.run graph-only --diff

# Tighter cap (faster, smaller output)
python -m tools.agent.run graph-only --diff --diff-cap 20

# Combine with scope for maximum focus
python -m tools.agent.run graph-only --diff --preset core --diff-cap 30
```

**Behaviour:**

1. Runs `git diff --name-only HEAD` to get the seed file list.
2. Builds the full (possibly scoped) graph.
3. Expands seeds by one BFS step using graph edges.  The BFS queue is stable-
   sorted at every step so the result is fully deterministic.
4. Filters the graph to the expanded node set.
5. Saves the filtered graph to `<out>/agent_graph.json`.

If git is unavailable, `--diff` exits with code `1` and a clear error message.

**Testability:** the BFS function `expand_diff_scope(seeds, graph, cap)` in
`scoping.py` is importable and unit-testable without running git.

### Seed-first diff build (`--diff-seed-first`) *(Part 1)*

The standard `--diff` path builds the **full** (or scoped) graph first and
then filters it down.  For large repositories this is wasteful when only a
handful of files changed.

`--diff-seed-first` inverts the order: it starts from the changed files and
crawls outward using **cheap discovery passes** — no full-repo walk needed.

```bash
# Enable seed-first strategy
python -m tools.agent.run graph-only --diff --diff-seed-first

# Control BFS depth and frontier size
python -m tools.agent.run graph-only --diff --diff-seed-first \
    --diff-max-frontier 100 \
    --diff-max-steps 4
```

**How it works:**

1. Get seeds via `git diff --name-only HEAD` (same as standard `--diff`).
2. `expand_seed_first_bfs()` (in `diff_seed_first.py`) crawls outward:
   - **Step 0:** seeds only.
   - **Each step:** for every file in the current frontier —
     - `.py` files: parse AST imports and resolve to repo files
       (`py_import_file` edges).
     - Schema JSON files (`schemas/**` or `*.schema.json`): follow cross-file
       `$ref` edges (`schema_ref` edges).
     - ID edges are **not** followed during expansion (too expensive).
   - Candidates are stable-sorted; frontier growth is capped by
     `--diff-max-frontier`.
   - BFS stops when the frontier is empty or `--diff-max-steps` is reached.
3. `build_graph_from_files()` runs the full 3-phase edge extraction (py
   imports, schema refs, id refs) but only over the resulting scoped file set.
4. The graph is saved with a `meta` section (see below).

**CLI flags:**

| Flag | Default | Meaning |
|------|---------|---------|
| `--diff-seed-first` | off | Enable seed-first strategy (requires `--diff`). |
| `--diff-max-frontier` | 250 | Cap on total files in expanded set (inclusive of seeds). |
| `--diff-max-steps` | 6 | Maximum BFS depth. |

**Fallback:** if seeds are empty (nothing changed vs HEAD), the harness
automatically falls back to the normal full-scan path.

**Back-compat:** `--diff-seed-first` is **OFF by default** — existing
`--diff` behaviour is unchanged unless you explicitly opt in.

### ID allowlist mode (`--no-id-allowlist`) *(Upgrade 2)*

By default the harness builds an allowlist of canonical IDs from `ontology/`
(using `build_id_allowlist`) and restricts `id_ref` edges to those IDs.  This
reduces noise from regex false positives (e.g. snake-case aliases like
`action_type = "drums"` that the regex would otherwise match).

```bash
# Default: allowlist ON (recommended)
python -m tools.agent.run graph-only

# Disable allowlist — full regex mode, more id_ref edges
python -m tools.agent.run graph-only --no-id-allowlist
```

Fallback rules:

- If `ontology/` does not exist under the repo root, the allowlist is empty
  and the harness automatically falls back to regex mode (no error).
- A warning is printed and traced when fallback occurs.

---

## Explain mode *(Part 2)*

The `explain` and `explain-scope` modes answer the question **"why is this
file here?"** by reading an already-built graph artifact — no repo re-scan.

### `explain` — shortest edge path to a target

```bash
# Print the shortest path from any seed to a target node
python -m tools.agent.run explain --target src/mmo/cli.py

# Specify the starting node explicitly
python -m tools.agent.run explain \
    --target schemas/render_request.schema.json \
    --from-seed src/mmo/cli.py

# Allow reverse traversal (undirected mode)
python -m tools.agent.run explain \
    --target src/mmo/core/render_plan.py \
    --undirected

# Point to a specific graph artifact
python -m tools.agent.run explain \
    --graph sandbox_tmp/agent_graph.json \
    --target src/mmo/core/render_plan.py

# Limit path length reported
python -m tools.agent.run explain --target src/mmo/cli.py --max-hops 5
```

**Output:**

```
target     : src/mmo/cli.py
from       : src/mmo/core/render_plan.py
hops       : 2

  [0] py_import_file: src/mmo/core/render_plan.py -> src/mmo/cli.py | evidence: mmo.cli
  [1] py_import_file: src/mmo/cli.py -> src/mmo/cli.py | evidence: ...
```

**Tie-breaking:** when multiple shortest paths exist, the path whose edge
sequence is lexicographically smallest by `(kind, src, dst, evidence)` is
chosen — fully deterministic.

**CLI flags for `explain`:**

| Flag | Default | Meaning |
|------|---------|---------|
| `--target NODE` | (required) | Target node id (file path or canonical ID). |
| `--from-seed NODE` | auto | Explicit start node.  Defaults to seeds from `graph.meta.seeds`. |
| `--max-hops N` | 10 | Maximum path length to report. |
| `--undirected` | off | Allow reverse edge traversal. |
| `--graph PATH` | `<out>/agent_graph.json` | Graph artifact to load. |

### `explain-scope` — first-hop justification list

Prints every non-seed file that was pulled into the graph during seed-first
expansion, with the edge that first brought it in.

```bash
# After a seed-first build:
python -m tools.agent.run graph-only --diff --diff-seed-first
python -m tools.agent.run explain-scope

# Point to a specific graph
python -m tools.agent.run explain-scope --graph sandbox_tmp/agent_graph.json
```

**Output:**

```
seeds (2):
  src/mmo/cli.py
  src/mmo/core/render_plan.py

non-seed nodes (3 of 7 shown):
  src/mmo/core/__init__.py
    via py_import_file: src/mmo/cli.py | evidence: mmo.core
  src/mmo/core/roles.py
    via py_import_file: src/mmo/core/render_plan.py | evidence: mmo.core.roles
  schemas/render_request.schema.json
    via schema_ref: src/mmo/core/render_plan.py | evidence: ./render_request.schema.json
```

`explain-scope` requires a seed-first build (`--diff --diff-seed-first`) to
have been run; it reads `graph.meta.parent_map`.  If the graph has no seed
metadata an informational message is printed and the command exits `0`.

---

## Artifacts

After running, two files are written to `<out>/` (default: `sandbox_tmp/`):

### `agent_graph.json`

```json
{
  "edges": [
    {
      "dst": "schemas/render_request.schema.json#layout_id",
      "evidence": "#/$defs/layout_id",
      "kind": "schema_ref",
      "source_file": "schemas/render_request.schema.json",
      "src": "schemas/render_request.schema.json"
    },
    {
      "dst": "src/mmo/core/render_plan.py",
      "evidence": "mmo.core.render_plan",
      "kind": "py_import_file",
      "source_file": "src/mmo/cli.py",
      "src": "src/mmo/cli.py"
    }
  ],
  "nodes": [
    { "id": "schemas/render_request.schema.json", "kind": "file" },
    { "id": "src/mmo/cli.py", "kind": "file" }
  ],
  "warnings": []
}
```

**Edge kinds:**

| Kind | `src` | `dst` | `evidence` |
|------|-------|-------|------------|
| `py_import` | Python file (rel path) | Imported module (dotted, absolute) | `"ast_import"` |
| `py_import_file` | Python file (rel path) | Resolved file path (rel) | Dotted module name |
| `py_import_relative` | Python file (rel path) | Resolved abs module name (or raw `".X"`) | Raw relative notation |
| `schema_ref` | Schema file (rel path) | `$ref` target | Raw `$ref` string |
| `id_ref` | Any text file (rel path) | Matched MMO ID string | 80-char snippet |

**`py_import_file` edges** (Upgrade 1):

- Added alongside every `py_import` edge when the dotted module can be found
  as an actual file under the repo root.
- `dst` is the POSIX-relative file path (e.g. `src/mmo/core/render_plan.py`).
- `evidence` is the original dotted module name (e.g. `"mmo.core.render_plan"`).
- Only in-repo modules are resolved; stdlib and third-party packages remain as
  `py_import`-only edges.
- Resolution uses only filesystem existence checks (no file reads, no budget).

**`py_import_relative` edges** *(new)*:

- Emitted for relative imports: `from . import X`, `from .X import Y`, `from .. import X`, etc.
- `dst` is the resolved absolute dotted module name when resolution succeeds
  (e.g. `"mmo.core.utils"` for `from .utils import Foo` in `src/mmo/core/plan.py`).
  Falls back to the raw relative notation (e.g. `".utils"`) on failure.
- `evidence` is always the raw relative notation (e.g. `".utils"`, `"..base"`).
- A companion `py_import_file` edge is also emitted for the resolved file (same
  as for absolute `py_import` edges) when the module resolves to an in-repo file.
- **Bug fix**: before this change, relative imports were incorrectly emitted as
  absolute `py_import` edges (e.g. `from .utils import X` → edge to `"utils"`).
  Those edges are now suppressed from `py_import` and emitted correctly under
  `py_import_relative`.

All lists are deterministically sorted:

- Nodes by `(kind, id)`.
- Edges by `(kind, src, dst, evidence)`.

No timestamps are written; the artifact is byte-identical for identical repo state.

**Optional `meta` section** (present when `--diff` or `--diff --diff-seed-first` is active):

```json
{
  "meta": {
    "diff_max_frontier": 250,
    "diff_max_steps": 6,
    "file_count": 12,
    "parent_map": {
      "src/mmo/core/render_plan.py": {
        "edge_kind": "py_import_file",
        "evidence": "mmo.core.render_plan",
        "parent": "src/mmo/cli.py"
      }
    },
    "seed_first": true,
    "seeds": ["src/mmo/cli.py"]
  }
}
```

| `meta` field | Present when | Meaning |
|---|---|---|
| `seed_first` | `--diff` (any) | `true` if seed-first build, `false` if standard diff filter. |
| `seeds` | `--diff` (any) | Sorted list of git-changed file paths. |
| `diff_max_frontier` | `--diff-seed-first` | Cap used during BFS. |
| `diff_max_steps` | `--diff-seed-first` | Depth limit used during BFS. |
| `file_count` | `--diff-seed-first` | Number of files in the scoped set. |
| `parent_map` | `--diff-seed-first` | `{child: {parent, edge_kind, evidence}}` first-hop justifications. |

### `agent_trace.ndjson`

One JSON object per line, sequence-numbered (no timestamps):

```
{"event": "run_start", "mode": "graph-only", "root": ".", "seq": 1}
{"event": "scope_resolved", "preset": null, "scope_paths": [], "seq": 2}
{"event": "id_allowlist_built", "count": 312, "parse_ok": true, "seq": 3}
{"event": "list_files", "count": 46, "pattern": "*.json", "seq": 4}
{"event": "file_read", "lines": 62, "path": "schemas/render_request.schema.json", "seq": 5}
```

### `agent_plan.json` (plan mode only)

```json
{
  "mode": "plan",
  "note": "Plan mode does not perform edits. ...",
  "suggested_tests": ["tests/test_agent_harness.py"],
  "top_files": ["src/mmo/cli.py", "src/mmo/core/render_plan.py"]
}
```

---

## Reading the console summary

```
=== Agent Graph Summary ===
Nodes                : 87
Edges total          : 640
  py_import          : 210
  py_import_file     : 165
  py_import_relative : 28
  schema_ref         : 134
  id_ref             : 103

Top 10 most connected nodes (by degree):
   1. [file  ] deg= 42  src/mmo/cli.py
   2. [file  ] deg= 31  schemas/render_plan.schema.json
   ...

Budget usage : {'steps': 18, 'file_reads': 46, 'total_lines': 6821, ...}
```

---

## Budget knobs

Budget caps protect against runaway operations during automated analysis.
They apply **per harness run** and use these defaults:

| Flag | Default | Meaning |
|------|---------|---------|
| `--max-steps` | 40 | Logical ops (`list_files`, `grep`, etc.) |
| `--max-file-reads` | 60 | Individual file content reads |
| `--max-total-lines` | 4000 | Cumulative lines read across all files |
| `--max-grep-hits` | 300 | Cumulative grep result lines |
| `--max-graph-nodes-summary` | 200 | Display cap for node summary (not a hard stop) |

When any hard cap is hit:

1. `BudgetExceededError` is raised internally.
2. The current phase records a warning and aborts its loop.
3. Subsequent phases are skipped if the budget remains exceeded.
4. The partial graph is saved and a summary is printed.
5. The CLI returns exit code `1`.

To scan the full repo, raise the limits:

```bash
python -m tools.agent.run graph-only \
    --max-file-reads 500 \
    --max-total-lines 200000
```

---

## Graph schema + validate_graph()

The artifact structure is formally defined in `schemas/agent_graph.schema.json`
(also mirrored to `src/mmo/data/schemas/agent_graph.schema.json` for packaged
installs).  The schema is strict (`additionalProperties: false`) and enumerates
all valid edge kinds.

### `validate_graph(graph, schema_path=None)` → `list[str]`

Validates a graph dict and returns a list of error strings (empty = valid).

```python
import json
from tools.agent.validate_graph import validate_graph

graph = json.loads(pathlib.Path("sandbox_tmp/agent_graph.json").read_text(encoding="utf-8"))
errors = validate_graph(graph)
if errors:
    for err in errors:
        print(f"  [ERROR] {err}")
else:
    print("Graph is valid.")
```

**Two-phase validation:**

1. **Structural check** (always, no external dependencies): verifies required
   keys, field types, and known edge kinds.
2. **JSON Schema check** (when `jsonschema` is installed): full validation
   against `schemas/agent_graph.schema.json`.

`patch` mode calls `validate_graph()` automatically after loading the artifact
and prints any errors as `[WARN]` messages (non-fatal, preserving exit codes).

**Gotcha:** `validate_graph` requires the repo-local schema file
(`schemas/agent_graph.schema.json`) to exist for phase 2.  If the schema is
missing (e.g. installed wheel without schemas), only the structural check runs —
still catches most issues.

---

## Graph-first enforcement contract

```
patch mode
  ├── graph artifact missing?  → exit 2  (REFUSED)
  ├── graph artifact malformed? → exit 2  (REFUSED)
  └── graph valid              → stub OK (exit 0)
                                   ↑
                            future: --patch-file or explicit instructions
```

`patch` mode is intentionally a stub in this version.  It validates the graph
artifact and documents the enforcement boundary, but does not edit files.
Future extensions may add `--patch-file <unified-diff>` to apply pre-approved,
minimal diffs — always with a valid graph as a prerequisite.

---

## Contract stamp (PR A)

The **contract stamp** is a small JSON artifact that binds a graph build to its
git commit and scope.  It prevents an agent from accidentally using a stale
graph (built at a different commit or with different settings) when entering
`patch` mode.

### Default location

```
<repo-root>/.mmo_agent/graph_contract.json
```

This directory is excluded from git (`.gitignore`) and from the graph scanner
(`_SKIP_DIRS`).

### What it contains

```json
{
  "budgets": { "max_file_reads": 60, "max_steps": 40, ... },
  "git_available": true,
  "git_sha": "abc123…",
  "graph_edge_count": 612,
  "graph_node_count": 87,
  "graph_path": "sandbox_tmp/agent_graph.json",
  "graph_sha256": "e3b0c4…",
  "repo_root": "/abs/path/to/repo",
  "run_mode": "graph-only",
  "scope": {
    "diff": false,
    "diff_cap": 50,
    "id_allowlist": true,
    "preset": null,
    "scope_paths": []
  },
  "trace_path": "sandbox_tmp/agent_trace.ndjson",
  "version": 1
}
```

No timestamps are included — the stamp is deterministic for identical inputs.

### How it prevents drift

When `patch` mode is entered:

1. The harness reads `.mmo_agent/graph_contract.json` (or the path specified
   by `--contract-stamp-path`).
2. It verifies:
   - `repo_root` matches the current resolved path.
   - `git_sha` matches `git rev-parse HEAD` (when git was available at stamp
     write time).
   - The saved graph file exists and its SHA-256 matches `graph_sha256`.
3. If **any** check fails, `patch` is refused with **exit code 3** and a clear
   error message.
4. If the stamp file does not exist, the check is skipped (backwards compatible
   with pre-stamp runs).

### CLI options

```bash
# Default behaviour: stamp is written after graph-only/plan and validated in patch
python -m tools.agent.run graph-only

# Override stamp path
python -m tools.agent.run graph-only --contract-stamp-path /tmp/my_stamp.json

# Disable stamp writing/validation entirely
python -m tools.agent.run graph-only --no-contract-stamp
python -m tools.agent.run patch --no-contract-stamp
```

### Exit codes (updated)

| Code | Meaning |
|------|---------|
| `0`  | Success |
| `1`  | Budget cap hit or other error |
| `2`  | Refused: no valid graph artifact |
| `3`  | Refused: contract stamp validation failed |

---

## Hot-path index (PR B)

The **hot-path index** (`agent_index.json`) is a second deterministic artifact
derived from the graph.  It pre-computes fast-lookup tables that let an agent
jump directly to evidence — the file, line number, and surrounding snippet —
without issuing additional grep passes.

### Default location

```
<repo-root>/.mmo_agent/agent_index.json
```

Same ignored directory as the contract stamp.

### What it contains

```json
{
  "file_summary": {
    "src/mmo/cli.py": {
      "id_refs_count": 3,
      "py_imports_count": 12,
      "schema_refs_count": 0
    }
  },
  "git_available": true,
  "git_sha": "abc123…",
  "graph_sha256": "e3b0c4…",
  "id_to_occurrences": {
    "ACTION.EQ.BELL_CUT": [
      {
        "col_start": 5,
        "evidence": "  action_id: ACTION.EQ.BELL_CUT",
        "line": 42,
        "path": "ontology/actions.yaml"
      }
    ]
  },
  "module_to_file": {
    "mmo.core.render_plan": "src/mmo/core/render_plan.py"
  },
  "repo_root": "/abs/path/to/repo",
  "schema_to_refs": {
    "schemas/render_request.schema.json": [
      { "evidence": "#/$defs/layout_id", "ref": "schemas/render_request.schema.json#layout_id" }
    ]
  },
  "version": 1,
  "warnings": []
}
```

### How to use it

- **Jump to a canonical ID**: look up `id_to_occurrences["ACTION.EQ.BELL_CUT"]`
  to get the exact file + line.
- **Find where a module is defined**: look up `module_to_file["mmo.core.render_plan"]`
  for the resolved file path.
- **Explore schema references**: `schema_to_refs["schemas/render_request.schema.json"]`
  lists every `$ref` in that schema.
- **Hotspot analysis**: `file_summary` shows which files have the most imports
  or ID references — useful for prioritising review.

### Relationship between graph, index, and contract stamp

```
graph-only / plan run
  ├── saves  agent_graph.json       (primary: nodes, edges, warnings)
  ├── writes .mmo_agent/graph_contract.json  (contract stamp)
  └── writes .mmo_agent/agent_index.json     (fast-lookup index)
                                    ↑
              index.graph_sha256 == stamp.graph_sha256
              (both reference the same saved graph)

patch run
  └── validates contract stamp against current HEAD + graph sha256
```

All three artifacts are deterministic (no timestamps) and are regenerated on
every `graph-only` or `plan` run.  The stamp and index are excluded from git.

### Performance

Most index sections (module_to_file, schema_to_refs, file_summary) are
derived directly from the already-built graph edges — **no extra file reads**.
Only `id_to_occurrences` requires reading files to find per-line positions.
Those reads are budget-charged; if the budget is exhausted, a partial index is
returned with a warning in `index.warnings`.

### CLI options

```bash
# Default: index is written after every graph-only or plan run
python -m tools.agent.run graph-only

# Override index path
python -m tools.agent.run graph-only --index-path /tmp/my_index.json

# Disable index writing
python -m tools.agent.run graph-only --no-index
```

---

### `run.py` modes (updated)

| Mode | Graph built | Artifacts written | Read-only? |
|------|-------------|-------------------|------------|
| `graph-only` | Yes | `agent_graph.json`, `agent_trace.ndjson`, stamp, index | Yes |
| `plan` | Yes | `agent_graph.json`, `agent_plan.json`, `agent_trace.ndjson`, stamp, index | Yes |
| `patch` | No (reads existing) | `agent_trace.ndjson` | Stub only |
| `explain` | No (reads existing) | `agent_trace.ndjson` | Yes |
| `explain-scope` | No (reads existing) | `agent_trace.ndjson` | Yes |

---

## Budget profiles and index tuning

### `--profile code` — code-navigation defaults

For daily code-focused work, the `--profile code` flag raises budget limits
and focuses the expensive `id_to_occurrences` scan where it matters most:

```bash
# Generous budgets, docs/ skipped in id_to_occurrences
python -m tools.agent.run graph-only --profile code

# Profile + diff-seed-first is the recommended daily recipe (see below)
python -m tools.agent.run graph-only --diff --diff-seed-first --profile code
```

**What `--profile code` changes:**

| Setting | Default | Under `--profile code` |
|---------|---------|----------------------|
| `max_file_reads` | 60 | **80** |
| `max_total_lines` | 4000 | **20 000** |
| `--index-skip-path` | (none) | **docs** |

Explicit budget flags always override profile values:

```bash
# Profile sets 80 but --max-file-reads 120 takes effect:
python -m tools.agent.run graph-only --profile code --max-file-reads 120
```

### `--index-skip-path` — focus id_to_occurrences on code

The `id_to_occurrences` section of the index requires reading every file that
contains a canonical ID reference.  Documentation files tend to have many ID
mentions but are rarely the target of code navigation.

`--index-skip-path PATH` (repeatable) excludes files under `PATH` from
`id_to_occurrences` **only** — all graph edges (including those from docs)
remain in the graph.

```bash
# Skip docs/ in id occurrence scanning (also set by --profile code)
python -m tools.agent.run graph-only --index-skip-path docs

# Skip multiple directories
python -m tools.agent.run graph-only \
    --index-skip-path docs \
    --index-skip-path tools/agent

# Override profile's default skip (empty = scan everything)
python -m tools.agent.run graph-only --profile code --index-skip-path ""
```

> **When to override:** pass `--index-skip-path ""` (empty string, equivalent
> to no skip) if you need full `id_to_occurrences` coverage — for example,
> when investigating where a canonical ID is used in documentation.

---

## Daily recipes

### Self-dogfood: run the harness on itself

The harness is self-validating.  Running it on `tools/agent/` should always
produce a valid graph with no schema errors:

```bash
# Run on the harness directory itself (no diff, no contract stamp for speed)
python -m tools.agent.run graph-only \
    --root tools/agent \
    --no-contract-stamp \
    --no-index \
    --max-file-reads 200 \
    --max-total-lines 50000

# Validate the resulting artifact
python -c "
import json, pathlib
from tools.agent.validate_graph import validate_graph
g = json.loads(pathlib.Path('sandbox_tmp/agent_graph.json').read_text('utf-8'))
errs = validate_graph(g)
print('VALID' if not errs else 'ERRORS: ' + str(errs))
"
```

The automated equivalent runs in `tests/test_agent_harness.py::TestSelfDogfood`.

### Which mode for which task?

| Task | Recommended command |
|------|---------------------|
| Review today's changes | `--diff --diff-seed-first --profile code` |
| Inspect a subsystem | `--preset core` (or `schemas`, `ontology`, `cli`) |
| Full repo navigation | `--profile code` (no diff, no preset) |
| Explain why a file is in scope | `explain-scope` after a seed-first build |
| Justify a specific path | `explain --target <file>` |

### Diff runs: use seed-first (not preset)

`--preset` and `--scope` constrain which files are *scanned* from the start.
In a seed-first diff run, seeds come from `git diff` — the preset does not
affect which seeds are chosen, only which non-seed files are eligible for
expansion.  For diff-focused work, **omit `--preset`** and let seed-first BFS
discover the relevant scope automatically:

```bash
# Good: seed-first discovers scope from git diff
python -m tools.agent.run graph-only --diff --diff-seed-first --profile code

# Use preset for non-diff, subsystem-focused runs
python -m tools.agent.run graph-only --preset core
```

### After a seed-first build, use explain to justify expansions

```bash
# Step 1: build
python -m tools.agent.run graph-only --diff --diff-seed-first --profile code

# Step 2: see what was pulled in and why
python -m tools.agent.run explain-scope

# Step 3: trace the path to a specific file
python -m tools.agent.run explain --target src/mmo/core/render_plan.py
```

### Raising budgets when the full repo is needed

```bash
# Scan everything, high budget
python -m tools.agent.run graph-only \
    --max-file-reads 500 \
    --max-total-lines 200000
```

---

## Extending the harness

**Add a new edge kind:** implement a scan function in `repo_ops.py` (accept
`path, root, budgets, tracer`, return sorted namedtuples), call it from the
appropriate phase in `graph_build.build_graph`, add the new kind to the
`"enum"` in `schemas/agent_graph.schema.json` **and** its packaged mirror
(`src/mmo/data/schemas/agent_graph.schema.json`), then add a test.

**Add symbol-level nodes:** parse `ast.FunctionDef` / `ast.ClassDef` nodes in
`parse_py_imports` and emit `{"kind": "symbol", "id": "module:ClassName"}` nodes.

**Async delegation:** the harness is sync by design (standard-library only).
Parallelism can be added by running multiple `build_graph` calls (scoped to
subdirectories) in a `ThreadPoolExecutor` and merging results.
