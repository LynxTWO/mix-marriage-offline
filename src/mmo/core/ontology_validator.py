"""Ontology integrity validator for ``mmo ontology validate``.

Loads every file referenced in ontology/ontology.yaml (the manifest) and
checks that each entry satisfies the required-field contract defined in
``validation_defaults.required_entry_fields``.  Prefix compliance is also
verified: every entry key must start with the ``id_prefix`` declared for
its category.

Returns a structured payload that CLI and tests can both consume:

.. code-block:: python

    {
        "ok": bool,
        "ontology_version": str,
        "categories_checked": int,
        "entries_checked": int,
        "error_count": int,
        "warn_count": int,
        "issues": [
            {
                "severity": "error" | "warn",
                "category": str,
                "file": str,
                "entry_id": str | None,
                "message": str,
            },
            ...
        ],
    }
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> tuple[Any, str | None]:
    """Return ``(data, error_message)``.  *data* is ``None`` on failure."""
    try:
        import yaml  # type: ignore[import]
    except ImportError:
        return None, "PyYAML is not installed; cannot validate ontology YAML files."
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh), None
    except Exception as exc:  # noqa: BLE001
        return None, f"YAML parse error: {exc}"


def _add_issue(
    issues: list[dict[str, Any]],
    *,
    severity: str,
    category: str,
    file: str,
    entry_id: str | None,
    message: str,
) -> None:
    issues.append(
        {
            "severity": severity,
            "category": category,
            "file": file,
            "entry_id": entry_id,
            "message": message,
        }
    )


def _validate_category(
    *,
    ontology_dir: Path,
    category: str,
    filename: str,
    root_key: str,
    id_prefix: str,
    required_fields: list[str],
    issues: list[dict[str, Any]],
) -> int:
    """Validate one ontology category file.  Returns the number of entries checked."""
    path = ontology_dir / filename
    if not path.exists():
        _add_issue(
            issues,
            severity="warn",
            category=category,
            file=filename,
            entry_id=None,
            message=f"File not found (skipped): {path.as_posix()}",
        )
        return 0

    data, err = _load_yaml(path)
    if err is not None or data is None:
        _add_issue(
            issues,
            severity="error",
            category=category,
            file=filename,
            entry_id=None,
            message=err or "File parsed to None (empty YAML).",
        )
        return 0

    if not isinstance(data, dict):
        _add_issue(
            issues,
            severity="error",
            category=category,
            file=filename,
            entry_id=None,
            message=f"Root of file is not a YAML mapping (got {type(data).__name__}).",
        )
        return 0

    entries_raw = data.get(root_key)
    if entries_raw is None:
        _add_issue(
            issues,
            severity="error",
            category=category,
            file=filename,
            entry_id=None,
            message=f"Missing root key '{root_key}' in file.",
        )
        return 0

    if not isinstance(entries_raw, dict):
        _add_issue(
            issues,
            severity="error",
            category=category,
            file=filename,
            entry_id=None,
            message=(
                f"Root key '{root_key}' is not a mapping "
                f"(got {type(entries_raw).__name__})."
            ),
        )
        return 0

    entries_checked = 0
    for entry_id, entry in entries_raw.items():
        if isinstance(entry_id, str) and entry_id == "_meta":
            continue  # skip metadata block

        entries_checked += 1
        entry_id_str = str(entry_id) if not isinstance(entry_id, str) else entry_id

        # Prefix check.
        if not entry_id_str.startswith(id_prefix):
            _add_issue(
                issues,
                severity="error",
                category=category,
                file=filename,
                entry_id=entry_id_str,
                message=(
                    f"ID '{entry_id_str}' does not start with required prefix "
                    f"'{id_prefix}'."
                ),
            )

        if not isinstance(entry, dict):
            _add_issue(
                issues,
                severity="error",
                category=category,
                file=filename,
                entry_id=entry_id_str,
                message=(
                    f"Entry value is not a mapping "
                    f"(got {type(entry).__name__}); cannot check required fields."
                ),
            )
            continue

        # Required field check.
        for field in required_fields:
            if field not in entry:
                _add_issue(
                    issues,
                    severity="error",
                    category=category,
                    file=filename,
                    entry_id=entry_id_str,
                    message=f"Missing required field '{field}'.",
                )

    return entries_checked


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_ontology(ontology_dir: Path) -> dict[str, Any]:
    """Load and validate all ontology files from *ontology_dir*.

    Returns a structured result dict (see module docstring).
    """
    issues: list[dict[str, Any]] = []
    manifest_filename = "ontology.yaml"
    manifest_path = ontology_dir / manifest_filename

    if not manifest_path.exists():
        return {
            "ok": False,
            "ontology_version": "",
            "categories_checked": 0,
            "entries_checked": 0,
            "error_count": 1,
            "warn_count": 0,
            "issues": [
                {
                    "severity": "error",
                    "category": "manifest",
                    "file": manifest_filename,
                    "entry_id": None,
                    "message": (
                        f"Manifest not found: {manifest_path.as_posix()}"
                    ),
                }
            ],
        }

    manifest_data, err = _load_yaml(manifest_path)
    if err is not None or manifest_data is None:
        return {
            "ok": False,
            "ontology_version": "",
            "categories_checked": 0,
            "entries_checked": 0,
            "error_count": 1,
            "warn_count": 0,
            "issues": [
                {
                    "severity": "error",
                    "category": "manifest",
                    "file": manifest_filename,
                    "entry_id": None,
                    "message": err or "Manifest parsed to None (empty YAML).",
                }
            ],
        }

    ontology_section = manifest_data.get("ontology") or {}
    ontology_version = str(ontology_section.get("ontology_version", ""))

    # Collect category specs from manifest.
    category_specs: list[dict[str, Any]] = []
    raw_specs = manifest_data.get("category_specs")
    if isinstance(raw_specs, list):
        for spec in raw_specs:
            if isinstance(spec, dict):
                category_specs.append(spec)

    # Collect required-field rules per category.
    validation_defaults = manifest_data.get("validation_defaults") or {}
    required_fields_by_cat: dict[str, list[str]] = {}
    raw_req = validation_defaults.get("required_entry_fields")
    if isinstance(raw_req, dict):
        for cat, fields in raw_req.items():
            if isinstance(fields, list):
                required_fields_by_cat[cat] = [f for f in fields if isinstance(f, str)]

    # Build filename map from includes.
    includes = manifest_data.get("includes") or {}
    file_key_to_filename: dict[str, str] = {}

    def _flatten_includes(node: Any, prefix: str) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, str):
                file_key_to_filename[full_key] = value
            elif isinstance(value, dict):
                _flatten_includes(value, full_key)

    _flatten_includes(includes, "includes")

    # Validate each declared category.
    total_entries = 0
    categories_checked = 0

    for spec in category_specs:
        category = spec.get("category", "")
        root_key = spec.get("root_key", "")
        id_prefix = spec.get("id_prefix", "")
        file_key = spec.get("file_key", "")

        if not (category and root_key and id_prefix):
            _add_issue(
                issues,
                severity="warn",
                category="manifest",
                file=manifest_filename,
                entry_id=None,
                message=(
                    f"Incomplete category_spec (missing category/root_key/id_prefix): "
                    f"{spec!r}"
                ),
            )
            continue

        filename = file_key_to_filename.get(file_key, "")
        if not filename:
            _add_issue(
                issues,
                severity="warn",
                category=category,
                file=manifest_filename,
                entry_id=None,
                message=(
                    f"Category '{category}' has file_key '{file_key}' "
                    f"not found in includes map (skipped)."
                ),
            )
            continue

        required_fields = required_fields_by_cat.get(category, [])
        n = _validate_category(
            ontology_dir=ontology_dir,
            category=category,
            filename=filename,
            root_key=root_key,
            id_prefix=id_prefix,
            required_fields=required_fields,
            issues=issues,
        )
        total_entries += n
        categories_checked += 1

    error_count = sum(1 for iss in issues if iss.get("severity") == "error")
    warn_count = sum(1 for iss in issues if iss.get("severity") == "warn")

    return {
        "ok": error_count == 0,
        "ontology_version": ontology_version,
        "categories_checked": categories_checked,
        "entries_checked": total_entries,
        "error_count": error_count,
        "warn_count": warn_count,
        "issues": sorted(
            issues,
            key=lambda iss: (
                iss.get("category", ""),
                iss.get("file", ""),
                iss.get("entry_id") or "",
                iss.get("severity", ""),
                iss.get("message", ""),
            ),
        ),
    }
