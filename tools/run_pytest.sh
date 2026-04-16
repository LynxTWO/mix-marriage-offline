#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH+:${PYTHONPATH}}"

# Keep basetemp inside the repo so failing tests do not spray artifacts into a
# user-global temp root.
BASE_TEMP="${REPO_ROOT}/.tmp_pytest"
mkdir -p "${BASE_TEMP}"

PYTHON_BIN="${MMO_PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  # Prefer the repo venv when it exists. Falling through to the system
  # interpreter breaks local runs on shells that do not expose a `python` shim.
  if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    echo "Python interpreter not found on PATH. Install Python or set MMO_PYTHON_BIN." >&2
    exit 127
  fi
fi

# Optional parallelism: export MMO_PYTEST_N=auto (or a number)
PYTEST_N="${MMO_PYTEST_N:-}"

if [[ -n "${PYTEST_N}" ]]; then
  # Fail early when parallelism is requested without xdist. Silent fallback to
  # serial hides the validation mode the caller thought they were running.
  "${PYTHON_BIN}" -c "import xdist" >/dev/null 2>&1 || {
    echo "MMO_PYTEST_N is set but pytest-xdist is not installed. Install dev deps." >&2
    exit 2
  }
  exec "${PYTHON_BIN}" -m pytest -n "${PYTEST_N}" --dist loadscope --basetemp "${BASE_TEMP}" "$@"
else
  exec "${PYTHON_BIN}" -m pytest --basetemp "${BASE_TEMP}" "$@"
fi
