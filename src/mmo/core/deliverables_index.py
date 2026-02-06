from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DELIVERABLES_INDEX_SCHEMA_VERSION = "0.1.0"


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _optional_string(value: Any) -> str | None:
    normalized = _coerce_str(value).strip()
    if not normalized:
        return None
    return normalized


def _to_posix_path(value: Any) -> str | None:
    raw = _coerce_str(value).strip()
    if not raw:
        return None
    return raw.replace("\\", "/")


def _path_to_posix(path: Path) -> str:
    return path.resolve().as_posix()


def _resolve_path(path_value: Any, *, root_dir: Path) -> Path | None:
    raw = _to_posix_path(path_value)
    if raw is None:
        return None
    parsed = Path(raw)
    if parsed.is_absolute():
        return parsed
    return (root_dir / parsed).resolve()


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Failed to read {label} JSON from {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON must be an object: {path}")
    return payload


def _read_optional_json_object(path: Path | None, *, label: str) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return _read_json_object(path, label=label)


def _output_sort_key(output: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _coerce_str(output.get("format")).strip().lower(),
        _coerce_str(output.get("file_path")).strip(),
        _coerce_str(output.get("output_id")).strip(),
    )


def _manifest_outputs_by_output_id(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    outputs_by_id: dict[str, list[dict[str, Any]]] = {}
    for renderer_manifest in _coerce_dict_list(manifest.get("renderer_manifests")):
        for output in _coerce_dict_list(renderer_manifest.get("outputs")):
            output_id = _coerce_str(output.get("output_id")).strip()
            if not output_id:
                continue
            outputs_by_id.setdefault(output_id, []).append(output)
    for output_id in list(outputs_by_id):
        outputs_by_id[output_id] = sorted(outputs_by_id[output_id], key=_output_sort_key)
    return outputs_by_id


def _file_format(output: dict[str, Any], *, path_value: str) -> str:
    normalized = _coerce_str(output.get("format")).strip().lower()
    if normalized:
        return normalized
    suffix = Path(path_value).suffix.lstrip(".").strip().lower()
    if suffix:
        return suffix
    return "unknown"


def _deliverable_files(
    output_ids: list[str],
    outputs_by_id: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for output_id in sorted({item for item in output_ids if item}):
        for output in outputs_by_id.get(output_id, []):
            file_path = _to_posix_path(output.get("file_path"))
            if file_path is None:
                continue
            output_format = _file_format(output, path_value=file_path)
            sha256 = _optional_string(output.get("sha256"))
            dedupe_key = (output_format, file_path, sha256 or "")
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            file_entry: dict[str, Any] = {
                "format": output_format,
                "path": file_path,
            }
            if sha256:
                file_entry["sha256"] = sha256
            files.append(file_entry)

    files.sort(
        key=lambda item: (
            _coerce_str(item.get("format")),
            _coerce_str(item.get("path")),
            _coerce_str(item.get("sha256")),
        )
    )
    return files


def _manifest_deliverables(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    outputs_by_id = _manifest_outputs_by_output_id(manifest)
    deliverables: list[dict[str, Any]] = []

    for raw_deliverable in _coerce_dict_list(manifest.get("deliverables")):
        deliverable_id = _coerce_str(raw_deliverable.get("deliverable_id")).strip()
        if not deliverable_id:
            continue

        output_ids_raw = raw_deliverable.get("output_ids")
        if not isinstance(output_ids_raw, list):
            output_ids_raw = []
        output_ids = [
            _coerce_str(item).strip()
            for item in output_ids_raw
            if isinstance(item, str) and _coerce_str(item).strip()
        ]
        files = _deliverable_files(output_ids, outputs_by_id)

        formats_raw = raw_deliverable.get("formats")
        if not isinstance(formats_raw, list):
            formats_raw = []
        manifest_formats = {
            _coerce_str(item).strip().lower()
            for item in formats_raw
            if isinstance(item, str) and _coerce_str(item).strip()
        }
        file_formats = {
            _coerce_str(item.get("format")).strip().lower()
            for item in files
            if _coerce_str(item.get("format")).strip()
        }
        formats = sorted(manifest_formats | file_formats)

        deliverable: dict[str, Any] = {
            "deliverable_id": deliverable_id,
            "label": _coerce_str(raw_deliverable.get("label")).strip() or deliverable_id,
            "formats": formats,
            "files": files,
        }

        target_layout_id = _optional_string(raw_deliverable.get("target_layout_id"))
        if target_layout_id:
            deliverable["target_layout_id"] = target_layout_id

        channel_count = _coerce_int(raw_deliverable.get("channel_count"))
        if channel_count is not None and channel_count > 0:
            deliverable["channel_count"] = channel_count

        deliverables.append(deliverable)

    deliverables.sort(key=lambda item: _coerce_str(item.get("deliverable_id")))
    return deliverables


def _merge_deliverables(deliverables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for deliverable in deliverables:
        deliverable_id = _coerce_str(deliverable.get("deliverable_id")).strip()
        if not deliverable_id:
            continue
        existing = merged.get(deliverable_id)
        if existing is None:
            merged[deliverable_id] = {
                **deliverable,
                "formats": sorted(
                    {
                        _coerce_str(item).strip().lower()
                        for item in deliverable.get("formats", [])
                        if isinstance(item, str) and _coerce_str(item).strip()
                    }
                ),
                "files": sorted(
                    _coerce_dict_list(deliverable.get("files")),
                    key=lambda item: (
                        _coerce_str(item.get("format")),
                        _coerce_str(item.get("path")),
                        _coerce_str(item.get("sha256")),
                    ),
                ),
            }
            continue

        existing_formats = {
            _coerce_str(item).strip().lower()
            for item in existing.get("formats", [])
            if isinstance(item, str) and _coerce_str(item).strip()
        }
        incoming_formats = {
            _coerce_str(item).strip().lower()
            for item in deliverable.get("formats", [])
            if isinstance(item, str) and _coerce_str(item).strip()
        }
        existing["formats"] = sorted(existing_formats | incoming_formats)

        file_rows = _coerce_dict_list(existing.get("files")) + _coerce_dict_list(
            deliverable.get("files")
        )
        deduped_files: dict[tuple[str, str, str], dict[str, Any]] = {}
        for file_entry in file_rows:
            file_format = _coerce_str(file_entry.get("format")).strip()
            file_path = _coerce_str(file_entry.get("path")).strip()
            sha256 = _coerce_str(file_entry.get("sha256")).strip()
            if not file_format or not file_path:
                continue
            deduped_files[(file_format, file_path, sha256)] = {
                "format": file_format,
                "path": file_path,
                **({"sha256": sha256} if sha256 else {}),
            }
        existing["files"] = sorted(
            deduped_files.values(),
            key=lambda item: (
                _coerce_str(item.get("format")),
                _coerce_str(item.get("path")),
                _coerce_str(item.get("sha256")),
            ),
        )

        if "target_layout_id" not in existing and _optional_string(
            deliverable.get("target_layout_id")
        ):
            existing["target_layout_id"] = _coerce_str(deliverable.get("target_layout_id")).strip()
        if "channel_count" not in existing:
            channel_count = _coerce_int(deliverable.get("channel_count"))
            if channel_count is not None and channel_count > 0:
                existing["channel_count"] = channel_count

    return sorted(merged.values(), key=lambda item: _coerce_str(item.get("deliverable_id")))


def _combined_deliverables(
    *,
    render_manifest: dict[str, Any],
    apply_manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    combined = _manifest_deliverables(render_manifest) + _manifest_deliverables(apply_manifest)
    return _merge_deliverables(combined)


def _report_run_config(report: dict[str, Any]) -> dict[str, Any]:
    return _coerce_dict(report.get("run_config"))


def _artifact_path(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return _path_to_posix(path)


def _entry_sort_key(entry: dict[str, Any]) -> tuple[str, str]:
    variant_id = _coerce_str(entry.get("variant_id")).strip()
    entry_id = _coerce_str(entry.get("entry_id")).strip()
    if variant_id:
        return (variant_id, entry_id)
    return (entry_id, entry_id)


def build_deliverables_index_single(
    out_dir: Path,
    report_path: Path,
    apply_manifest_path: Path | None,
    render_manifest_path: Path | None,
    bundle_path: Path | None,
    pdf_path: Path | None,
    csv_path: Path | None,
) -> dict[str, Any]:
    resolved_out_dir = out_dir.resolve()
    report = _read_json_object(report_path, label="Report")
    run_config = _report_run_config(report)

    apply_manifest = _read_optional_json_object(apply_manifest_path, label="Apply manifest")
    render_manifest = _read_optional_json_object(render_manifest_path, label="Render manifest")
    deliverables = _combined_deliverables(
        render_manifest=render_manifest,
        apply_manifest=apply_manifest,
    )

    artifacts: dict[str, Any] = {}
    artifact_candidates = (
        ("report", report_path),
        ("bundle", bundle_path),
        ("pdf", pdf_path),
        ("csv", csv_path),
        ("render_manifest", render_manifest_path),
        ("apply_manifest", apply_manifest_path),
        ("listen_pack", resolved_out_dir / "listen_pack.json"),
    )
    for key, path in artifact_candidates:
        normalized = _artifact_path(path)
        if normalized is not None:
            artifacts[key] = normalized

    entry: dict[str, Any] = {
        "entry_id": "ENTRY.SINGLE",
        "label": "single",
        "deliverables": deliverables,
        "artifacts": artifacts,
    }
    preset_id = _optional_string(run_config.get("preset_id"))
    if preset_id:
        entry["preset_id"] = preset_id
    profile_id = _optional_string(run_config.get("profile_id"))
    if profile_id:
        entry["profile_id"] = profile_id

    entries = [entry]
    entries.sort(key=_entry_sort_key)
    return {
        "schema_version": DELIVERABLES_INDEX_SCHEMA_VERSION,
        "root_out_dir": _path_to_posix(resolved_out_dir),
        "mode": "single",
        "entries": entries,
    }


def _plan_variant_map(variant_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    plan = _coerce_dict(variant_result.get("plan"))
    for variant in _coerce_dict_list(plan.get("variants")):
        variant_id = _coerce_str(variant.get("variant_id")).strip()
        if not variant_id or variant_id in mapping:
            continue
        mapping[variant_id] = variant
    return mapping


def _variant_entry(
    *,
    root_out_dir: Path,
    result: dict[str, Any],
    plan_variant: dict[str, Any],
    listen_pack_path: Path | None,
) -> dict[str, Any] | None:
    variant_id = _coerce_str(result.get("variant_id")).strip()
    if not variant_id:
        return None

    report_path = _resolve_path(result.get("report_path"), root_dir=root_out_dir)
    if report_path is None or not report_path.exists():
        return None
    report = _read_json_object(report_path, label=f"Variant report ({variant_id})")
    run_config = _report_run_config(report)

    apply_manifest_path = _resolve_path(result.get("apply_manifest_path"), root_dir=root_out_dir)
    render_manifest_path = _resolve_path(result.get("render_manifest_path"), root_dir=root_out_dir)
    apply_manifest = _read_optional_json_object(
        apply_manifest_path,
        label=f"Apply manifest ({variant_id})",
    )
    render_manifest = _read_optional_json_object(
        render_manifest_path,
        label=f"Render manifest ({variant_id})",
    )
    deliverables = _combined_deliverables(
        render_manifest=render_manifest,
        apply_manifest=apply_manifest,
    )

    artifacts: dict[str, Any] = {}
    artifact_candidates = (
        ("report", report_path),
        ("bundle", _resolve_path(result.get("bundle_path"), root_dir=root_out_dir)),
        ("pdf", _resolve_path(result.get("pdf_path"), root_dir=root_out_dir)),
        ("csv", _resolve_path(result.get("csv_path"), root_dir=root_out_dir)),
        ("render_manifest", render_manifest_path),
        ("apply_manifest", apply_manifest_path),
        ("listen_pack", listen_pack_path),
    )
    for key, path in artifact_candidates:
        normalized = _artifact_path(path)
        if normalized is not None:
            artifacts[key] = normalized

    entry: dict[str, Any] = {
        "entry_id": f"ENTRY.{variant_id}",
        "variant_id": variant_id,
        "label": _coerce_str(plan_variant.get("label")).strip() or variant_id,
        "deliverables": deliverables,
        "artifacts": artifacts,
    }

    preset_id = _optional_string(plan_variant.get("preset_id")) or _optional_string(
        run_config.get("preset_id")
    )
    if preset_id:
        entry["preset_id"] = preset_id
    profile_id = _optional_string(run_config.get("profile_id"))
    if profile_id:
        entry["profile_id"] = profile_id
    return entry


def build_deliverables_index_variants(
    root_out_dir: Path,
    variant_result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(variant_result, dict):
        raise ValueError("variant_result must be an object.")

    resolved_root = root_out_dir.resolve()
    plan_variants = _plan_variant_map(variant_result)
    results = _coerce_dict_list(variant_result.get("results"))
    listen_pack_path = resolved_root / "listen_pack.json"
    if not listen_pack_path.exists():
        listen_pack_path = None

    entries: list[dict[str, Any]] = []
    for result in results:
        variant_id = _coerce_str(result.get("variant_id")).strip()
        plan_variant = _coerce_dict(plan_variants.get(variant_id))
        entry = _variant_entry(
            root_out_dir=resolved_root,
            result=result,
            plan_variant=plan_variant,
            listen_pack_path=listen_pack_path,
        )
        if entry is None:
            continue
        entries.append(entry)

    entries.sort(key=_entry_sort_key)
    return {
        "schema_version": DELIVERABLES_INDEX_SCHEMA_VERSION,
        "root_out_dir": _path_to_posix(resolved_root),
        "mode": "variants",
        "entries": entries,
    }
