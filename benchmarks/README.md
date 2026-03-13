# Benchmarks Suite

This folder contains the MMO v1.1 benchmark runner:

- `suite.py`: deterministic benchmark cases for core CLI list commands and the
  agent harness self-dogfood graph build.

The suite uses only Python standard library modules.

## Run

From repo root:

```bash
PYTHONPATH=src python3 benchmarks/suite.py
```

Write results to a JSON artifact:

```bash
PYTHONPATH=src python3 benchmarks/suite.py --out sandbox_tmp/benchmarks/v1.1.0.json
```

Run one specific case:

```bash
PYTHONPATH=src python3 benchmarks/suite.py --case cli.roles.list_json
```

Override runs for every case:

```bash
PYTHONPATH=src python3 benchmarks/suite.py --runs 20 --warmup-runs 2
```

## Cases

- `cli.roles.list_json`
- `cli.targets.list_json`
- `cli.downmix.list_json`
- `harness.graph_only.tools_agent`

## Notes

- Results are environment-dependent timing numbers; compare runs on the same
  machine class for trend tracking.
- Temporary files are written under `sandbox_tmp/benchmarks` by default.
