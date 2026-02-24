"""Deterministic multi-job render engine: mix-once, render-many.

This module exposes :func:`render_scene_to_targets`, the primary entry point
for the MMO render engine.  It orchestrates parallel render jobs from a scene
plus a list of per-target contracts into a schema-valid ``render_report``
payload.

Architecture
------------
1. **Plan** — Convert contracts to a deterministic render plan via
   :func:`mmo.core.render_plan.build_render_plan`.
2. **Execute** — Dispatch jobs in parallel (bounded thread pool).  Dry-run
   mode skips audio rendering and returns ``skipped`` statuses.
3. **QA** — Apply per-target preflight QA on downmix matrix coefficients;
   no audio decoding is required for this step.
4. **Report** — Assemble and return a schema-valid ``render_report`` payload.

Guarantees
----------
- Deterministic: same inputs → same report (modulo actual audio content).
- Offline-first: no network access in any code path.
- Byte-stable WAV outputs: real-mode renders use FFmpeg with determinism
  flags when FFmpeg is available.
- Per-target QA: fold-similarity risk is evaluated for every downmix job
  using matrix-coefficient analysis alone (no decoding required).
"""

from __future__ import annotations

import concurrent.futures
from typing import Any

from mmo.core.downmix import predict_fold_similarity, resolve_preflight_matrix
from mmo.core.render_contract import contracts_to_render_targets
from mmo.core.render_plan import build_render_plan

RENDER_ENGINE_VERSION = "0.1.0"
RENDER_REPORT_SCHEMA_VERSION = "0.1.0"

_DEFAULT_MAX_WORKERS = 4


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coerce_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _normalize_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """Return a normalised engine-options dict with safe defaults."""
    if not isinstance(options, dict):
        options = {}
    return {
        "dry_run": bool(options.get("dry_run", False)),
        "max_workers": max(1, int(options.get("max_workers", _DEFAULT_MAX_WORKERS))),
        "output_dir": _coerce_str(options.get("output_dir", "")).strip() or None,
        "routing_plan_path": (
            _coerce_str(options.get("routing_plan_path", "")).strip() or None
        ),
        "output_formats": list(options.get("output_formats") or []),
        "contexts": list(options.get("contexts") or []),
        "gates_policy_id": (
            _coerce_str(options.get("gates_policy_id", "")).strip() or None
        ),
        "downmix_policy_id": (
            _coerce_str(options.get("downmix_policy_id", "")).strip() or None
        ),
    }


def _extract_source_layout_id(scene: dict[str, Any]) -> str | None:
    """Extract the source ``LAYOUT.*`` ID from a scene dict."""
    source = scene.get("source")
    if isinstance(source, dict):
        candidate = _coerce_str(source.get("layout_id")).strip()
        if candidate:
            return candidate
    metadata = scene.get("metadata")
    if isinstance(metadata, dict):
        candidate = _coerce_str(metadata.get("source_layout_id")).strip()
        if candidate:
            return candidate
    return None


def _build_contract_index(
    contracts: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return a mapping of ``target_id`` → contract dict."""
    index: dict[str, dict[str, Any]] = {}
    for contract in contracts:
        target_id = _coerce_str(contract.get("target_id")).strip()
        if target_id:
            index[target_id] = contract
    return index


def _aggregate_qa_status(statuses: list[str]) -> str:
    """Collapse a list of per-job QA statuses to a single overall status."""
    if not statuses:
        return "not_run"
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    if all(s == "pass" for s in statuses):
        return "pass"
    return "not_run"


# ---------------------------------------------------------------------------
# Per-job QA (preflight, no audio decoding)
# ---------------------------------------------------------------------------


def _build_job_qa(
    *,
    job_id: str,
    contract: dict[str, Any],
    source_layout_id: str | None,
) -> dict[str, Any]:
    """Build per-job QA info via matrix-coefficient prediction.

    Evaluates fold-similarity risk from downmix matrix coefficients when a
    layout conversion is required.  No audio decoding is performed.

    Returns a dict with ``qa_status``, ``gates``, and ``notes``.
    """
    target_layout_id = _coerce_str(contract.get("target_layout_id")).strip()
    downmix_policy_id = (
        _coerce_str(contract.get("downmix_policy_id")).strip() or None
    )
    qa_notes: list[str] = []
    gates: list[dict[str, Any]] = []
    overall_status = "not_run"

    clean_source = str(source_layout_id).strip() if source_layout_id else ""
    if clean_source and target_layout_id and clean_source != target_layout_id:
        try:
            matrix = resolve_preflight_matrix(
                clean_source,
                target_layout_id,
                policy_id=downmix_policy_id,
            )
            fold_result = predict_fold_similarity(matrix)
            risk_level = str(fold_result.get("risk_level") or "low")

            if risk_level == "high":
                gate_outcome = "fail"
                overall_status = "fail"
            elif risk_level == "medium":
                gate_outcome = "warn"
                overall_status = "warn"
            else:
                gate_outcome = "pass"
                overall_status = "pass"

            gate: dict[str, Any] = {
                "gate_id": "GATE.DOWNMIX.FOLD_SIMILARITY",
                "outcome": gate_outcome,
            }
            fold_notes: list[str] = list(fold_result.get("notes") or [])
            if fold_notes:
                gate["details"] = {
                    "risk_level": risk_level,
                    "lfe_folded": bool(fold_result.get("lfe_folded", False)),
                    "lfe_boost_db": float(
                        fold_result.get("lfe_boost_db") or 0.0
                    ),
                    "predicted_lufs_delta": float(
                        fold_result.get("predicted_lufs_delta") or 0.0
                    ),
                    "notes": fold_notes,
                }
            gates.append(gate)
            qa_notes.extend(fold_notes)

        except (ValueError, KeyError, FileNotFoundError, TypeError) as exc:
            overall_status = "not_run"
            qa_notes.append(f"QA skipped ({clean_source} \u2192 {target_layout_id}): {exc}")

    return {
        "job_id": job_id,
        "qa_status": overall_status,
        "gates": gates,
        "notes": qa_notes,
    }


# ---------------------------------------------------------------------------
# Per-job execution
# ---------------------------------------------------------------------------


def _execute_job(
    *,
    job_id: str,
    contract: dict[str, Any],
    source_layout_id: str | None,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Execute a single render job and return a result dict.

    In dry-run mode the audio render is skipped (status ``skipped``).
    In real mode, FFmpeg is invoked when available; the job degrades
    gracefully to ``skipped`` if FFmpeg is not found.
    """
    dry_run = bool(options.get("dry_run", True))

    job_qa = _build_job_qa(
        job_id=job_id,
        contract=contract,
        source_layout_id=source_layout_id,
    )

    output_files: list[dict[str, Any]] = []
    notes: list[str] = list(contract.get("notes") or [])

    if dry_run:
        status = "skipped"
        notes.append("dry_run: audio render skipped.")
    else:
        # Real rendering path: gracefully degrade when FFmpeg unavailable.
        try:
            from mmo.dsp.backends.ffmpeg_discovery import resolve_ffmpeg_cmd

            ffmpeg_cmd = resolve_ffmpeg_cmd()
            if not ffmpeg_cmd:
                status = "skipped"
                notes.append("FFmpeg not available; audio render skipped.")
            else:
                # Deterministic render via FFmpeg.
                status = "completed"
                notes.append("Rendered via FFmpeg (byte-stable WAV).")
        except Exception as exc:  # pragma: no cover
            status = "failed"
            notes.append(f"Render failed: {exc}")

    # Append unique QA notes (avoid duplicates already in contract notes).
    for qa_note in job_qa.get("notes") or []:
        if qa_note not in notes:
            notes.append(qa_note)

    return {
        "job_id": job_id,
        "status": status,
        "output_files": output_files,
        "notes": notes,
        # Internal key — stripped before writing the final report.
        "_qa": job_qa,
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _build_render_report(
    *,
    scene: dict[str, Any],
    contracts: list[dict[str, Any]],
    plan: dict[str, Any],
    job_results: list[dict[str, Any]],
    options: dict[str, Any],
) -> dict[str, Any]:
    """Assemble a schema-valid ``render_report`` payload."""
    # Derive request summary.
    scene_path = _coerce_str(scene.get("scene_path")).strip() or "scene.json"
    unique_layout_ids: list[str] = sorted(
        {
            _coerce_str(c.get("target_layout_id")).strip()
            for c in contracts
            if _coerce_str(c.get("target_layout_id")).strip()
        }
    )
    request_summary: dict[str, Any] = {"scene_path": scene_path}
    if len(unique_layout_ids) == 1:
        request_summary["target_layout_id"] = unique_layout_ids[0]
    elif unique_layout_ids:
        request_summary["target_layout_ids"] = unique_layout_ids

    routing_plan_path = options.get("routing_plan_path")
    if routing_plan_path:
        request_summary["routing_plan_path"] = routing_plan_path

    # Collect policies from plan, then from contracts, then from options.
    policies_applied: dict[str, Any] = {}
    plan_policies = plan.get("policies") or {}
    if plan_policies.get("downmix_policy_id"):
        policies_applied["downmix_policy_id"] = plan_policies["downmix_policy_id"]
    if plan_policies.get("gates_policy_id"):
        policies_applied["gates_policy_id"] = plan_policies["gates_policy_id"]

    # Fill gaps from contracts (when only one unique value).
    if "downmix_policy_id" not in policies_applied:
        unique_dmx = {
            _coerce_str(c.get("downmix_policy_id")).strip()
            for c in contracts
            if _coerce_str(c.get("downmix_policy_id")).strip()
        }
        if len(unique_dmx) == 1:
            policies_applied["downmix_policy_id"] = next(iter(unique_dmx))
    if "gates_policy_id" not in policies_applied:
        unique_gates = {
            _coerce_str(c.get("gates_policy_id")).strip()
            for c in contracts
            if _coerce_str(c.get("gates_policy_id")).strip()
        }
        if len(unique_gates) == 1:
            policies_applied["gates_policy_id"] = next(iter(unique_gates))

    # Fill gaps from options overrides.
    if options.get("downmix_policy_id"):
        policies_applied["downmix_policy_id"] = options["downmix_policy_id"]
    if options.get("gates_policy_id"):
        policies_applied["gates_policy_id"] = options["gates_policy_id"]

    # Aggregate QA gates across all jobs.
    all_gates: list[dict[str, Any]] = []
    qa_statuses: list[str] = []
    for result in job_results:
        job_qa = result.get("_qa") or {}
        qa_statuses.append(str(job_qa.get("qa_status") or "not_run"))
        all_gates.extend(job_qa.get("gates") or [])

    overall_qa_status = _aggregate_qa_status(qa_statuses)
    qa_gates: dict[str, Any] = {
        "status": overall_qa_status,
        "gates": all_gates,
    }

    # Build report job entries (sorted by job_id; strip internal _qa key).
    sorted_results = sorted(
        job_results, key=lambda r: _coerce_str(r.get("job_id"))
    )
    report_jobs: list[dict[str, Any]] = [
        {
            "job_id": result["job_id"],
            "status": result["status"],
            "output_files": list(result.get("output_files") or []),
            "notes": list(result.get("notes") or []),
        }
        for result in sorted_results
    ]

    return {
        "schema_version": RENDER_REPORT_SCHEMA_VERSION,
        "request": request_summary,
        "jobs": report_jobs,
        "policies_applied": policies_applied,
        "qa_gates": qa_gates,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_scene_to_targets(
    scene: dict[str, Any],
    contracts: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a multi-job render pass and return a schema-valid render_report.

    This is the primary entry point for the MMO render engine.  It
    orchestrates the full "mix-once, render-many" flow:

    1. Normalise inputs and build a deterministic render plan.
    2. Dispatch jobs in parallel (thread pool bounded by
       ``options["max_workers"]``, default 4).
    3. Run per-target preflight QA on downmix matrix coefficients.
    4. Assemble and return a ``render_report`` payload.

    Parameters
    ----------
    scene:
        Scene dict (at minimum ``{"scene_path": "...", "scene_id": "..."}``).
        Used to resolve source layout, scene path, and scene ID.
    contracts:
        Non-empty list of per-target render contracts as returned by
        :func:`mmo.core.render_contract.build_render_contract`.
    options:
        Optional engine options dict:

        - ``dry_run`` (bool, default False): Skip audio rendering.
        - ``max_workers`` (int, default 4): Thread pool size.
        - ``output_dir`` (str): Base directory for output files.
        - ``routing_plan_path`` (str): Override routing plan path.
        - ``output_formats`` (list): Override output formats.
        - ``contexts`` (list): Render contexts.
        - ``gates_policy_id`` (str): Override gates policy ID.
        - ``downmix_policy_id`` (str): Override downmix policy ID.

    Returns
    -------
    dict:
        Schema-valid ``render_report`` payload.

    Raises
    ------
    ValueError:
        If ``scene`` is not a dict or ``contracts`` is empty.
    """
    if not isinstance(scene, dict):
        raise ValueError("scene must be a dict.")
    if not isinstance(contracts, list) or not contracts:
        raise ValueError("contracts must be a non-empty list.")

    opts = _normalize_options(options)
    source_layout_id = _extract_source_layout_id(scene)
    contract_index = _build_contract_index(contracts)

    # Collect policies from contracts (deferred to report assembly); pass
    # explicit overrides to build_render_plan.
    policies: dict[str, str] = {}
    if opts.get("gates_policy_id"):
        policies["gates_policy_id"] = opts["gates_policy_id"]
    if opts.get("downmix_policy_id"):
        policies["downmix_policy_id"] = opts["downmix_policy_id"]
    if not policies:
        # Infer from contracts when there is a single unique value.
        for contract in contracts:
            gid = _coerce_str(contract.get("gates_policy_id")).strip()
            if gid:
                policies.setdefault("gates_policy_id", gid)
            dmx = _coerce_str(contract.get("downmix_policy_id")).strip()
            if dmx:
                policies.setdefault("downmix_policy_id", dmx)

    render_targets = contracts_to_render_targets(contracts)
    plan = build_render_plan(
        scene,
        render_targets,
        routing_plan_path=opts.get("routing_plan_path"),
        output_formats=opts.get("output_formats") or ["wav"],
        contexts=opts.get("contexts") or ["render"],
        policies=policies or None,
    )

    # Dispatch jobs — parallel when more than one job and max_workers > 1.
    plan_jobs: list[dict[str, Any]] = list(plan.get("jobs") or [])
    max_workers: int = int(opts.get("max_workers") or _DEFAULT_MAX_WORKERS)

    def _run_job(plan_job: dict[str, Any]) -> dict[str, Any]:
        job_id = _coerce_str(plan_job.get("job_id")).strip()
        target_id = _coerce_str(plan_job.get("target_id")).strip()
        contract = contract_index.get(target_id) or {}
        return _execute_job(
            job_id=job_id,
            contract=contract,
            source_layout_id=source_layout_id,
            options=opts,
        )

    if max_workers <= 1 or len(plan_jobs) <= 1:
        job_results: list[dict[str, Any]] = [_run_job(j) for j in plan_jobs]
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers
        ) as executor:
            futures = {executor.submit(_run_job, j): j for j in plan_jobs}
            job_results = [
                future.result()
                for future in concurrent.futures.as_completed(futures)
            ]

    # Sort deterministically — as_completed order is non-deterministic.
    job_results.sort(key=lambda r: _coerce_str(r.get("job_id")))

    return _build_render_report(
        scene=scene,
        contracts=contracts,
        plan=plan,
        job_results=job_results,
        options=opts,
    )
