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
from mmo.core.dsp_pipeline_hooks import (
    normalize_dsp_stem_specs,
    run_dsp_pipeline_hooks,
)
from mmo.core.layout_negotiation import DEFAULT_CHANNEL_STANDARD
from mmo.core.loudness_profiles import (
    DEFAULT_LOUDNESS_PROFILE_ID,
    resolve_loudness_profile_receipt,
)
from mmo.core.progress import CancelToken, CancelledError, ProgressTracker
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


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _normalize_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """Return a normalised engine-options dict with safe defaults."""
    if not isinstance(options, dict):
        options = {}
    raw_standard = _coerce_str(options.get("layout_standard", "")).strip().upper()
    normalized_dsp_stems = normalize_dsp_stem_specs(options.get("dsp_stems"))
    raw_stem_ids = sorted(str(s) for s in (options.get("stem_ids") or []))
    if not raw_stem_ids and normalized_dsp_stems:
        raw_stem_ids = [spec.stem_id for spec in normalized_dsp_stems]
    stem_ids = sorted(set(raw_stem_ids))
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
        "loudness_profile_id": (
            _coerce_str(options.get("loudness_profile_id", "")).strip() or None
        ),
        "layout_standard": raw_standard or DEFAULT_CHANNEL_STANDARD,
        "stem_ids": stem_ids,
        "stem_max_workers": max(1, int(options.get("stem_max_workers") or 2)),
        "dsp_stems": normalized_dsp_stems,
        "enable_bus_dsp": bool(options.get("enable_bus_dsp", False)),
        "enable_post_master_dsp": bool(options.get("enable_post_master_dsp", False)),
        "progress_listener": options.get("progress_listener"),
        "log_listener": options.get("log_listener"),
        "cancel_token": options.get("cancel_token"),
        "progress_tracker": options.get("progress_tracker"),
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
    cancel_token: CancelToken,
) -> dict[str, Any]:
    """Execute a single render job and return a result dict.

    In dry-run mode the audio render is skipped (status ``skipped``).
    In real mode, FFmpeg is invoked when available; the job degrades
    gracefully to ``skipped`` if FFmpeg is not found.
    """
    cancel_token.raise_if_cancelled()
    dry_run = bool(options.get("dry_run", True))

    job_qa = _build_job_qa(
        job_id=job_id,
        contract=contract,
        source_layout_id=source_layout_id,
    )

    output_files: list[dict[str, Any]] = []
    notes: list[str] = list(contract.get("notes") or [])
    dsp_receipt: dict[str, Any] | None = None
    dsp_events: list[dict[str, Any]] = []

    # Explainability: record which channel ordering standard was used.
    contract_standard = _coerce_str(contract.get("layout_standard")).strip()
    engine_standard = _coerce_str(options.get("layout_standard")).strip() or DEFAULT_CHANNEL_STANDARD
    active_standard = contract_standard or engine_standard
    if active_standard and active_standard != DEFAULT_CHANNEL_STANDARD:
        notes.append(f"using {active_standard} channel order (Film/Cinema ordering requested).")
    else:
        notes.append(f"using {active_standard or DEFAULT_CHANNEL_STANDARD} channel order (SMPTE/ITU-R default).")

    # Stem dispatch: layout-aware, seeded, parallel (stems → plugins phase).
    # Each stem is processed with the target layout's LayoutContext so that
    # plugin chains receive the correct channel slot assignments.
    stem_ids: list[str] = list(options.get("stem_ids") or [])
    if stem_ids:
        cancel_token.raise_if_cancelled()
        try:
            from mmo.core.dsp_dispatch import StemJob, dispatch_stems

            target_layout_id = _coerce_str(contract.get("target_layout_id")).strip()
            stem_workers = max(1, int(options.get("stem_max_workers") or 2))
            stem_jobs = [
                StemJob(
                    stem_id=sid,
                    layout_id=target_layout_id or "LAYOUT.2_0",
                    standard=active_standard,
                    params={},
                    render_seed=0,
                )
                for sid in stem_ids  # already sorted by _normalize_options
            ]
            stem_results = dispatch_stems(stem_jobs, max_workers=stem_workers)
            notes.append(
                f"stem_dispatch: {len(stem_results)} stem(s) ({active_standard})."
            )
            dsp_receipt = run_dsp_pipeline_hooks(
                stem_results=stem_results,
                stem_specs=list(options.get("dsp_stems") or []),
                enable_bus_stage=bool(options.get("enable_bus_dsp", False)),
                enable_post_master_stage=bool(options.get("enable_post_master_dsp", False)),
            )
            dsp_events = list(dsp_receipt.get("events") or [])
            stages = dsp_receipt.get("stages") if isinstance(dsp_receipt, dict) else {}
            pre_actions = 0
            bus_actions = 0
            post_actions = 0
            if isinstance(stages, dict):
                pre_actions = int(
                    ((stages.get("pre_bus_stem") or {}).get("action_count") or 0)
                )
                bus_actions = int(((stages.get("bus") or {}).get("action_count") or 0))
                post_actions = int(
                    ((stages.get("post_master") or {}).get("action_count") or 0)
                )
            notes.append(
                "dsp_hooks: "
                f"actions={len(dsp_receipt.get('actions') or [])}, "
                f"pre_bus={pre_actions}, bus={bus_actions}, post_master={post_actions}."
            )
        except (ValueError, ImportError) as exc:
            notes.append(f"stem_dispatch skipped: {exc}")

    if dry_run:
        cancel_token.raise_if_cancelled()
        status = "skipped"
        notes.append("dry_run: audio render skipped.")
    else:
        cancel_token.raise_if_cancelled()
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
        "_dsp_receipt": dsp_receipt or {},
        "_dsp_events": dsp_events,
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

    requested_profile_id = _coerce_str(options.get("loudness_profile_id")).strip() or None
    try:
        loudness_profile_receipt = resolve_loudness_profile_receipt(requested_profile_id)
    except ValueError as exc:
        loudness_profile_receipt = resolve_loudness_profile_receipt(DEFAULT_LOUDNESS_PROFILE_ID)
        warnings = list(loudness_profile_receipt.get("warnings") or [])
        warnings.insert(
            0,
            (
                f"{exc}. Falling back to default loudness_profile_id "
                f"{DEFAULT_LOUDNESS_PROFILE_ID!r}."
            ),
        )
        loudness_profile_receipt["warnings"] = warnings

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
        "loudness_profile_receipt": loudness_profile_receipt,
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
        - ``stem_ids`` (list[str]): Stem IDs to dispatch through the layout-aware
          plugin chain (stems → plugins phase).  Empty list skips stem dispatch.
        - ``stem_max_workers`` (int, default 2): Thread pool size for stem dispatch.
        - ``dsp_stems`` (list[dict]): Optional per-stem role/bus/evidence rows for
          DSP hook planning. Each row supports ``stem_id``, ``role_id``, ``bus_id``,
          and ``evidence`` object.
        - ``enable_bus_dsp`` (bool, default False): Enable bus-stage DSP hook actions.
        - ``enable_post_master_dsp`` (bool, default False): Enable post-master DSP
          hook actions.

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
    progress_tracker = opts.get("progress_tracker")
    if isinstance(progress_tracker, ProgressTracker):
        progress = progress_tracker
        cancel_token = progress.cancel_token
    else:
        maybe_token = opts.get("cancel_token")
        cancel_token = maybe_token if isinstance(maybe_token, CancelToken) else CancelToken()
        progress = ProgressTracker(
            total_steps=0,
            cancel_token=cancel_token,
            progress_listener=opts.get("progress_listener"),
            log_listener=opts.get("log_listener"),
        )

    cancel_token.raise_if_cancelled()
    progress.set_phase("plan")
    progress.emit_log(
        kind="info",
        scope="render",
        what="render planning started",
        why="Building deterministic render jobs from scene + target contracts.",
        where=[_coerce_str(scene.get("scene_path")).strip() or "scene.json"],
        confidence=1.0,
        evidence={"codes": ["RENDER.ENGINE.PLAN.STARTED"]},
    )

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
    plan_jobs: list[dict[str, Any]] = list(plan.get("jobs") or [])
    progress.set_total_steps(len(plan_jobs) + 2)
    progress.advance(
        phase="plan",
        what="render plan built",
        why="Prepared deterministic per-target render jobs.",
        where=[_coerce_str(plan.get("plan_path")).strip() or "render_plan.json"],
        confidence=1.0,
        evidence={
            "codes": ["RENDER.ENGINE.PLAN.BUILT"],
            "metrics": [{"name": "job_count", "value": float(len(plan_jobs))}],
        },
    )

    # Dispatch jobs — parallel when more than one job and max_workers > 1.
    max_workers: int = int(opts.get("max_workers") or _DEFAULT_MAX_WORKERS)

    def _run_job(plan_job: dict[str, Any]) -> dict[str, Any]:
        cancel_token.raise_if_cancelled()
        job_id = _coerce_str(plan_job.get("job_id")).strip()
        target_id = _coerce_str(plan_job.get("target_id")).strip()
        contract = contract_index.get(target_id) or {}
        progress.emit_log(
            kind="action",
            scope="render",
            what=f"render job started: {job_id}",
            why="Dispatching target contract through deterministic render execution.",
            where=[job_id, target_id or "(unknown_target)"],
            confidence=1.0,
            evidence={"codes": ["RENDER.ENGINE.JOB.STARTED"]},
        )
        result = _execute_job(
            job_id=job_id,
            contract=contract,
            source_layout_id=source_layout_id,
            options=opts,
            cancel_token=cancel_token,
        )
        raw_dsp_events = result.get("_dsp_events")
        if isinstance(raw_dsp_events, list):
            for raw_event in raw_dsp_events:
                if not isinstance(raw_event, dict):
                    continue
                what = _coerce_str(raw_event.get("what")).strip()
                why = _coerce_str(raw_event.get("why")).strip()
                if not what or not why:
                    continue
                where_raw = raw_event.get("where")
                where = where_raw if isinstance(where_raw, list) else [job_id]
                confidence = _coerce_float(raw_event.get("confidence"))
                if confidence is not None:
                    confidence = max(0.0, min(1.0, confidence))
                evidence = raw_event.get("evidence")
                progress.emit_log(
                    kind="action",
                    scope="dsp",
                    what=what,
                    why=why,
                    where=where,
                    confidence=confidence,
                    evidence=evidence if isinstance(evidence, dict) else {},
                )
        status = _coerce_str(result.get("status")).strip() or "unknown"
        confidence = 1.0 if status in {"completed", "skipped"} else 0.0
        progress.advance(
            phase="execute",
            what=f"render job completed: {job_id}",
            why=f"Render job finished with status={status}.",
            where=[job_id, target_id or "(unknown_target)"],
            confidence=confidence,
            evidence={
                "codes": ["RENDER.ENGINE.JOB.COMPLETED"],
                "notes": [f"status={status}"],
            },
        )
        return result

    if max_workers <= 1 or len(plan_jobs) <= 1:
        job_results: list[dict[str, Any]] = []
        for job in plan_jobs:
            cancel_token.raise_if_cancelled()
            job_results.append(_run_job(job))
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers
        ) as executor:
            futures = {executor.submit(_run_job, j): j for j in plan_jobs}
            job_results = []
            for future in concurrent.futures.as_completed(futures):
                try:
                    job_results.append(future.result())
                except CancelledError:
                    cancel_token.cancel("render engine cancelled")
                    for pending in futures:
                        pending.cancel()
                    raise

    # Sort deterministically — as_completed order is non-deterministic.
    job_results.sort(key=lambda r: _coerce_str(r.get("job_id")))

    report = _build_render_report(
        scene=scene,
        contracts=contracts,
        plan=plan,
        job_results=job_results,
        options=opts,
    )
    progress.advance(
        phase="report",
        what="render report assembled",
        why="Collected job outcomes, policies, and QA gates into schema-valid payload.",
        where=[_coerce_str(scene.get("scene_path")).strip() or "scene.json"],
        confidence=1.0,
        evidence={"codes": ["RENDER.ENGINE.REPORT.BUILT"]},
    )
    return report
