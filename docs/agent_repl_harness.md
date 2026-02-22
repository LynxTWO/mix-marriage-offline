# Agent REPL Harness

**Location:** `tools/agent/`
**Tests:** `tests/test_agent_harness.py`

---

## Mental model: the repo as a dependency graph

Before an AI agent edits anything, it must understand the repo's dependency
structure. The harness materialises that structure as a concrete JSON artifact:
a directed graph where every node is a file (or a canonical ID) and every edge
is a typed dependency (Python import, JSON schema `$ref`, or MMO canonical ID
reference).

**The contract:** no file edits may start until a valid graph artifact exists.
`patch` mode enforces this by refusing to proceed without the artifact.

```
Locate → Graph → Plan → Patch (optional, guarded)
  ↑         ↑       ↑       ↑
  read    build   inspect  edit
```

---

## Modules

| Module           | Role |
|------------------|------|
| `budgets.py`     | Hard budget caps; raises `BudgetExceededError` on overflow. |
| `trace.py`       | Structured NDJSON trace log for every operation. |
| `repo_ops.py`    | Safe primitives: `list_files`, `read_slice`, `grep`, `parse_py_imports`, `scan_schema_refs`, `scan_id_refs`. |
| `graph_build.py` | Orchestrates a full graph build; writes deterministic JSON. |
| `run.py`         | CLI entrypoint (modes: `graph-only`, `plan`, `patch`). |

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

### `scan_schema_refs(path, root, budgets, tracer)`
Recursively walks a JSON file and extracts every `$ref` value.
Local refs (`#/$defs/…`) produce intra-file edges; cross-file refs produce
inter-file edges.  Charges **one file read**.

### `scan_id_refs(path, root, budgets, tracer)`
Regex scan for MMO canonical IDs (e.g. `ACTION.UTILITY.GAIN`, `LAYOUT.2_0`,
`ROLE.DRUMS.KICK`) and snake-case aliases (`action_`, `layout_`, …).
Returns `IdRefEdge` namedtuples.  Charges **one file read**.

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
    }
  ],
  "nodes": [
    { "id": "schemas/render_request.schema.json", "kind": "file" }
  ],
  "warnings": []
}
```

**Edge kinds:**

| Kind | `src` | `dst` | `evidence` |
|------|-------|-------|------------|
| `py_import` | Python file (rel path) | Imported module (dotted) | `"ast_import"` |
| `schema_ref` | Schema file (rel path) | `$ref` target | Raw `$ref` string |
| `id_ref` | Any text file (rel path) | Matched MMO ID string | 80-char snippet |

All lists are deterministically sorted:
- Nodes by `(kind, id)`.
- Edges by `(kind, src, dst, evidence)`.

No timestamps are written; the artifact is byte-identical for identical repo state.

### `agent_trace.ndjson`

One JSON object per line, sequence-numbered (no timestamps):

```
{"event": "run_start", "mode": "graph-only", "root": ".", "seq": 1}
{"event": "list_files", "count": 46, "pattern": "*.json", "seq": 2}
{"event": "file_read", "lines": 62, "path": "schemas/render_request.schema.json", "seq": 3}
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
Nodes        : 87
Edges total  : 412
  py_import  : 210
  schema_ref : 134
  id_ref     : 68

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

## Extending the harness

**Add a new edge kind:** implement a scan function in `repo_ops.py` (accept
`path, root, budgets, tracer`, return sorted namedtuples), call it from the
appropriate phase in `graph_build.build_graph`, and add a test.

**Add symbol-level nodes:** parse `ast.FunctionDef` / `ast.ClassDef` nodes in
`parse_py_imports` and emit `{"kind": "symbol", "id": "module:ClassName"}` nodes.

**Async delegation:** the harness is sync by design (standard-library only).
Parallelism can be added by running multiple `build_graph` calls (scoped to
subdirectories) in a `ThreadPoolExecutor` and merging results.
