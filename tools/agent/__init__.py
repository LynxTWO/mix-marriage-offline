"""tools/agent — Graph-first REPL harness for AI-assisted development.

Provides safe, budget-enforced repo operations and a dependency graph builder.
Import as ``tools.agent.*`` from the repo root.

Submodules:
    budgets    Hard budget caps (file reads, lines, steps, grep hits).
    trace      Structured NDJSON trace logging.
    repo_ops   Safe repo primitives (list_files, read_slice, grep, parse_py_imports,
               scan_schema_refs, scan_id_refs).
    graph_build  Builds the file-level dependency graph (py_import, schema_ref, id_ref).
    run        CLI entrypoint (graph-only | plan | patch).
"""
