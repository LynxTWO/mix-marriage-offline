"""Thread-safe, seeded, layout-aware DSP dispatch for the MMO render engine.

The dispatch layer sits between raw audio buffers (stems) and render targets.
It is responsible for:

1. Assigning a deterministic per-stem seed derived from ``stem_id + render_seed``
   (never from time or environment state).
2. Building an immutable ``ProcessContext`` for each stem from its ``LAYOUT.*`` ID
   and channel ordering standard.
3. Dispatching plugin chains in parallel (bounded ``ThreadPoolExecutor``) with
   one thread per stem and strictly sequential plugins within each stem.
4. Returning results in stable ``stem_id`` order for deterministic output.

Thread safety
-------------
- Each stem gets its own ``PluginEvidenceCollector``; no shared mutable state.
- Seeds are derived deterministically; no global PRNG state is mutated.
- ``ProcessContext`` is an immutable frozen dataclass.
- Result list is sorted by ``stem_id`` before return.

Typical flow
------------
::

    from mmo.core.dsp_dispatch import StemJob, dispatch_stems

    jobs = [
        StemJob("STEM.DIALOGUE.EN", "LAYOUT.7_1_4", "SMPTE"),
        StemJob("STEM.MUSIC",       "LAYOUT.7_1_4", "SMPTE"),
        StemJob("STEM.SFX",         "LAYOUT.7_1_4", "SMPTE"),
    ]
    results = dispatch_stems(jobs, max_workers=4)
    for r in results:
        print(r.stem_id, "lfe_slots=", r.lfe_slots, "seed=", r.seed)
"""

from __future__ import annotations

import concurrent.futures
import hashlib
from dataclasses import dataclass, field
from typing import Any

from mmo.dsp.plugins.base import LayoutContext, PluginEvidenceCollector
from mmo.dsp.process_context import ProcessContext, build_process_context as _build_process_context

_DEFAULT_STEM_WORKERS = 4
_DEFAULT_SAMPLE_RATE_HZ = 48_000


# ---------------------------------------------------------------------------
# Process context factory
# ---------------------------------------------------------------------------


def build_process_context(
    layout_id: str,
    standard: str = "SMPTE",
    *,
    sample_rate_hz: int = _DEFAULT_SAMPLE_RATE_HZ,
    seed: int = 0,
) -> ProcessContext:
    """Return a ProcessContext for the given ``LAYOUT.*`` ID and standard."""

    return _build_process_context(
        layout_id,
        layout_standard=standard,
        sample_rate_hz=sample_rate_hz,
        seed=seed,
    )


def build_layout_context(
    layout_id: str,
    standard: str = "SMPTE",
    *,
    sample_rate_hz: int = _DEFAULT_SAMPLE_RATE_HZ,
    seed: int = 0,
) -> LayoutContext:
    """Compatibility wrapper that adapts ProcessContext into LayoutContext."""

    process_ctx = build_process_context(
        layout_id,
        standard,
        sample_rate_hz=sample_rate_hz,
        seed=seed,
    )
    return LayoutContext.from_process_context(process_ctx)


# ---------------------------------------------------------------------------
# Deterministic per-stem seed
# ---------------------------------------------------------------------------


def make_stem_seed(stem_id: str, render_seed: int = 0) -> int:
    """Derive a deterministic per-stem integer seed.

    SHA-256 of ``"{stem_id}:{render_seed}"`` truncated to 31 bits.  The
    result is always in ``[0, 2**31 - 1]`` and is safe for any PRNG that
    expects a non-negative Python int.

    Never reads time, process ID, or any other environment-dependent state.

    Parameters
    ----------
    stem_id:
        Stable identifier for this stem (e.g. ``"STEM.DIALOGUE.EN"``).
    render_seed:
        Top-level render seed; combined with ``stem_id`` to partition the
        seed space per render pass.  Use ``0`` for production renders.

    Returns
    -------
    int:
        Deterministic seed in ``[0, 2**31 - 1]``.
    """
    raw = hashlib.sha256(f"{stem_id}:{render_seed}".encode("utf-8")).digest()
    return int.from_bytes(raw[:4], "little") & 0x7FFF_FFFF


# ---------------------------------------------------------------------------
# StemJob and StemResult
# ---------------------------------------------------------------------------


@dataclass
class StemJob:
    """Input specification for a single stem dispatch operation.

    Treat as immutable after construction — do not mutate ``params`` after
    passing a job to :func:`dispatch_stems`.

    Parameters
    ----------
    stem_id:
        Unique identifier for this stem (e.g. ``"STEM.DIALOGUE.EN"``).
    layout_id:
        Canonical ``LAYOUT.*`` ID for the stem's channel layout.
    standard:
        Channel ordering standard (``"SMPTE"`` or ``"FILM"``).
    params:
        Plugin-specific parameters (snapshot; treat as immutable).
    render_seed:
        Top-level render seed; combined with ``stem_id`` for per-stem seeding.
        Default ``0`` for deterministic production renders.
    sample_rate_hz:
        Buffer sample rate in Hz; carried into ``ProcessContext``.
    """

    stem_id: str
    layout_id: str
    standard: str = "SMPTE"
    params: dict[str, Any] = field(default_factory=dict)
    render_seed: int = 0
    sample_rate_hz: int = _DEFAULT_SAMPLE_RATE_HZ


@dataclass
class StemResult:
    """Output of dispatching a single stem job.

    Parameters
    ----------
    stem_id:
        Mirrors ``StemJob.stem_id``.
    seed:
        Deterministic per-stem seed used by this dispatch.
    layout_id:
        Layout ID (mirrored from input for traceability).
    standard:
        Channel ordering standard (mirrored from input).
    process_ctx:
        Canonical DSP execution context for this stem.
    channel_order:
        Semantic channel IDs in the current buffer order.
    lfe_indices:
        LFE channel indices in the resolved layout.
    height_indices:
        Height-channel indices in the resolved layout.
    num_channels:
        Total channel count.
    evidence:
        Evidence payload populated by the dispatch layer.
    notes:
        Human-readable dispatch notes (seed, layout, slot info).
    """

    stem_id: str
    seed: int
    layout_id: str
    standard: str
    process_ctx: ProcessContext
    channel_order: tuple[str, ...]
    lfe_indices: list[int]
    height_indices: list[int]
    num_channels: int
    evidence: PluginEvidenceCollector
    notes: list[str]

    @property
    def lfe_slots(self) -> list[int]:
        return self.lfe_indices

    @property
    def height_slots(self) -> list[int]:
        return self.height_indices


# ---------------------------------------------------------------------------
# Internal per-stem dispatch
# ---------------------------------------------------------------------------


def _dispatch_one_stem(job: StemJob) -> StemResult:
    """Resolve process context and collect evidence for a single stem.

    This function runs in a worker thread.  Every object it creates is local
    to this call; no shared mutable state is accessed or written.
    """
    seed = make_stem_seed(job.stem_id, job.render_seed)
    process_ctx = build_process_context(
        job.layout_id,
        job.standard,
        sample_rate_hz=job.sample_rate_hz,
        seed=seed,
    )
    evidence = PluginEvidenceCollector()
    evidence.set(
        stage_what="dsp_dispatch: process context resolved",
        stage_why=(
            f"stem {job.stem_id!r} dispatched with layout "
            f"{job.layout_id} ({job.standard})"
        ),
        metrics=[
            {
                "key": "num_channels",
                "value": process_ctx.num_channels,
                "unit": "channels",
            },
            {
                "key": "lfe_index_count",
                "value": len(process_ctx.lfe_indices),
                "unit": "indices",
            },
            {
                "key": "height_index_count",
                "value": len(process_ctx.height_indices),
                "unit": "indices",
            },
        ],
    )
    notes: list[str] = [
        f"seed={seed} stem_id={job.stem_id!r} render_seed={job.render_seed}",
        (
            f"layout={job.layout_id} standard={job.standard} "
            f"channels={process_ctx.num_channels} "
            f"lfe={process_ctx.lfe_indices} "
            f"height={process_ctx.height_indices}"
        ),
        f"channel_order={list(process_ctx.channel_order)}",
    ]
    return StemResult(
        stem_id=job.stem_id,
        seed=seed,
        layout_id=job.layout_id,
        standard=job.standard,
        process_ctx=process_ctx,
        channel_order=process_ctx.channel_order,
        lfe_indices=process_ctx.lfe_indices,
        height_indices=process_ctx.height_indices,
        num_channels=process_ctx.num_channels,
        evidence=evidence,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Public dispatch API
# ---------------------------------------------------------------------------


def dispatch_stems(
    jobs: list[StemJob],
    max_workers: int = _DEFAULT_STEM_WORKERS,
) -> list[StemResult]:
    """Dispatch stem jobs in parallel; return results sorted by ``stem_id``.

    Uses a bounded ``ThreadPoolExecutor``.  Falls back to serial execution
    when ``max_workers <= 1`` or there is only one job.

    Thread safety
    -------------
    - Each stem gets an independent ``PluginEvidenceCollector``.
    - ``StemJob`` contains no shared mutable state after construction.
    - Results are sorted by ``stem_id`` before return, so output order is
      deterministic regardless of thread scheduling.

    Parameters
    ----------
    jobs:
        List of stem dispatch jobs (may be empty).
    max_workers:
        Maximum number of worker threads (clamped to at least 1).

    Returns
    -------
    list[StemResult]:
        Results sorted by ``stem_id`` for deterministic output.
    """
    if not jobs:
        return []

    max_workers = max(1, int(max_workers))

    if max_workers <= 1 or len(jobs) == 1:
        results = [_dispatch_one_stem(job) for job in jobs]
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers
        ) as executor:
            futures = {executor.submit(_dispatch_one_stem, job): job for job in jobs}
            results = [
                future.result()
                for future in concurrent.futures.as_completed(futures)
            ]

    # Stable sort — as_completed order is non-deterministic.
    results.sort(key=lambda r: r.stem_id)
    return results
