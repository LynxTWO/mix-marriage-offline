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
| `repo_ops.py`        | Safe primitives: `list_files`, `read_slice`, `grep`, `parse_py_imports`, `resolve_module_to_path`, `scan_schema_refs`, `scan_id_refs`, `build_id_allowlist`. |
| `graph_build.py`     | Orchestrates a full graph build; writes deterministic JSON. |
| `scoping.py`         | Scope presets, diff BFS expansion, graph filtering. |
| `contract_stamp.py`  | Contract stamp: commit-bound provenance for graph artifacts (PR A). |
| `index_build.py`     | Hot-path index: fast-lookup artifact derived from graph (PR B). |
| `run.py`             | CLI entrypoint (modes: `graph-only`, `plan`, `patch`). |

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
| `py_import` | Python file (rel path) | Imported module (dotted) | `"ast_import"` |
| `py_import_file` | Python file (rel path) | Resolved file path (rel) | Dotted module name |
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

All lists are deterministically sorted:
- Nodes by `(kind, id)`.
- Edges by `(kind, src, dst, evidence)`.

No timestamps are written; the artifact is byte-identical for identical repo state.

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
Nodes            : 87
Edges total      : 612
  py_import      : 210
  py_import_file : 145
  schema_ref     : 134
  id_ref         : 123

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

## Extending the harness

**Add a new edge kind:** implement a scan function in `repo_ops.py` (accept
`path, root, budgets, tracer`, return sorted namedtuples), call it from the
appropriate phase in `graph_build.build_graph`, and add a test.

**Add symbol-level nodes:** parse `ast.FunctionDef` / `ast.ClassDef` nodes in
`parse_py_imports` and emit `{"kind": "symbol", "id": "module:ClassName"}` nodes.

**Async delegation:** the harness is sync by design (standard-library only).
Parallelism can be added by running multiple `build_graph` calls (scoped to
subdirectories) in a `ThreadPoolExecutor` and merging results.
