"""Validate the MMO User Manual sources and prove the PDF builder works.

Outputs deterministic JSON to stdout:

.. code-block:: json

    {
      "ok": true,
      "chapter_count": 15,
      "glossary_term_count": 17,
      "missing_chapters": [],
      "pdf_built": true,
      "pdf_bytes": 84321,
      "reportlab_available": true,
      "errors": [],
      "warnings": []
    }

Exit codes:
    0  — ``ok`` is true (all chapters found; PDF built if reportlab available).
    1  — One or more validation errors.
    2  — Setup error (PyYAML not installed).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

# --- insert src/ so the module works both as a repo script and installed ---
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def _resolve_path(value: str, *, repo_root: Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else repo_root / p


def validate_user_manual(
    *,
    repo_root: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Run all manual source checks and optionally build the PDF.

    Returns a dict with keys: ok, chapter_count, glossary_term_count,
    missing_chapters, pdf_built, pdf_bytes, reportlab_available,
    errors, warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []
    chapter_count = 0
    glossary_term_count = 0
    missing_chapters: list[str] = []
    pdf_built = False
    pdf_bytes = 0
    reportlab_available = False

    # ------------------------------------------------------------------
    # 0. PyYAML check
    # ------------------------------------------------------------------
    if yaml is None:
        return {
            "ok": False,
            "chapter_count": 0,
            "glossary_term_count": 0,
            "missing_chapters": [],
            "pdf_built": False,
            "pdf_bytes": 0,
            "reportlab_available": False,
            "errors": ["PyYAML is not installed; cannot validate manual.yaml."],
            "warnings": [],
        }

    # ------------------------------------------------------------------
    # 1. Manifest
    # ------------------------------------------------------------------
    if not manifest_path.is_file():
        errors.append(f"manual.yaml not found: {manifest_path}")
        return _result(
            ok=False,
            chapter_count=chapter_count,
            glossary_term_count=glossary_term_count,
            missing_chapters=missing_chapters,
            pdf_built=pdf_built,
            pdf_bytes=pdf_bytes,
            reportlab_available=reportlab_available,
            errors=errors,
            warnings=warnings,
        )

    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Failed to parse manual.yaml: {exc}")
        return _result(
            ok=False,
            chapter_count=chapter_count,
            glossary_term_count=glossary_term_count,
            missing_chapters=missing_chapters,
            pdf_built=pdf_built,
            pdf_bytes=pdf_bytes,
            reportlab_available=reportlab_available,
            errors=errors,
            warnings=warnings,
        )

    if not isinstance(manifest, dict):
        errors.append("manual.yaml root must be a mapping.")
        return _result(
            ok=False,
            chapter_count=chapter_count,
            glossary_term_count=glossary_term_count,
            missing_chapters=missing_chapters,
            pdf_built=pdf_built,
            pdf_bytes=pdf_bytes,
            reportlab_available=reportlab_available,
            errors=errors,
            warnings=warnings,
        )

    chapters_dir = manifest_path.parent
    chapters: list[dict[str, Any]] = manifest.get("chapters", [])
    if not isinstance(chapters, list):
        errors.append("manual.yaml 'chapters' must be a list.")
        chapters = []

    # ------------------------------------------------------------------
    # 2. Chapter files
    # ------------------------------------------------------------------
    for entry in chapters:
        if not isinstance(entry, dict):
            errors.append(f"Chapter entry is not a mapping: {entry!r}")
            continue
        chapter_file = entry.get("file", "")
        if not chapter_file:
            errors.append(f"Chapter entry missing 'file' key: {entry!r}")
            continue
        chapter_count += 1
        chapter_path = chapters_dir / chapter_file
        if not chapter_path.is_file():
            missing_chapters.append(chapter_file)
            errors.append(f"Missing chapter file: {chapter_file}")

    # ------------------------------------------------------------------
    # 3. Glossary
    # ------------------------------------------------------------------
    glossary_file = manifest.get("glossary_file", "glossary.yaml")
    glossary_path = chapters_dir / glossary_file
    if not glossary_path.is_file():
        warnings.append(f"Glossary file not found: {glossary_file}")
    else:
        try:
            gdata = yaml.safe_load(glossary_path.read_text(encoding="utf-8"))
            terms = gdata.get("terms", []) if isinstance(gdata, dict) else []
            glossary_term_count = len(terms)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Failed to parse {glossary_file}: {exc}")

    # ------------------------------------------------------------------
    # 4. PDF build smoke-test
    # ------------------------------------------------------------------
    try:
        import reportlab  # noqa: F401
        reportlab_available = True
    except ImportError:
        warnings.append(
            "reportlab not installed; skipping PDF build check. "
            "Install with: pip install .[pdf]"
        )

    if reportlab_available and not errors:
        tmp_dir = tempfile.mkdtemp(prefix="mmo_manual_validate_")
        try:
            tmp_pdf = Path(tmp_dir) / "MMO_User_Manual_validate.pdf"
            from mmo.exporters.pdf_manual import build_manual_pdf  # noqa: PLC0415

            build_manual_pdf(manifest_path, tmp_pdf, strict=False)
            if tmp_pdf.is_file():
                pdf_bytes = tmp_pdf.stat().st_size
                pdf_built = True
            else:
                errors.append("PDF builder ran but no output file was written.")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"PDF build failed: {exc}")
        finally:
            import shutil  # noqa: PLC0415
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return _result(
        ok=not errors,
        chapter_count=chapter_count,
        glossary_term_count=glossary_term_count,
        missing_chapters=missing_chapters,
        pdf_built=pdf_built,
        pdf_bytes=pdf_bytes,
        reportlab_available=reportlab_available,
        errors=sorted(errors),
        warnings=sorted(warnings),
    )


def _result(**kwargs: Any) -> dict[str, Any]:
    return dict(kwargs)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Validate MMO User Manual sources and prove PDF builder works.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(repo_root),
        help="Repository root (default: parent of this script).",
    )
    parser.add_argument(
        "--manifest",
        default="docs/manual/manual.yaml",
        help="Path to manual.yaml (absolute or relative to --repo-root).",
    )
    args = parser.parse_args()

    root = Path(args.repo_root)
    manifest_path = _resolve_path(args.manifest, repo_root=root)
    result = validate_user_manual(repo_root=root, manifest_path=manifest_path)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
