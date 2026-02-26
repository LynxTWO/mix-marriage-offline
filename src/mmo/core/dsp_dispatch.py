"""Thread-safe, seeded, layout-aware DSP dispatch for the MMO render engine.

The dispatch layer sits between raw audio buffers (stems) and render targets.
It is responsible for:

1. Assigning a deterministic per-stem seed derived from ``stem_id + render_seed``
   (never from time or environment state).
2. Building an immutable ``LayoutContext`` for each stem from its ``LAYOUT.*`` ID
   and channel ordering standard.
3. Dispatching plugin chains in parallel (bounded ``ThreadPoolExecutor``) with
   one thread per stem and strictly sequential plugins within each stem.
4. Returning results in stable ``stem_id`` order for deterministic output.

Thread safety
-------------
- Each stem gets its own ``PluginEvidenceCollector``; no shared mutable state.
- Seeds are derived deterministically; no global PRNG state is mutated.
- ``LayoutContext`` is an immutable frozen dataclass.
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

_DEFAULT_STEM_WORKERS = 4


# ---------------------------------------------------------------------------
# Layout context factory
# ---------------------------------------------------------------------------

# Lazy singleton: populated on first call to _get_layout_map().
# CPython dict update is GIL-protected; initialising twice from concurrent
# threads produces identical contents, so no lock is required.
_LAYOUT_MAP: dict[tuple[str, str], Any] | None = None


def _get_layout_map() -> dict[tuple[str, str], Any]:
    global _LAYOUT_MAP
    if _LAYOUT_MAP is not None:
        return _LAYOUT_MAP
    from mmo.core.speaker_layout import (
        FILM_2_0,
        FILM_2_1,
        FILM_5_1,
        FILM_5_1_2,
        FILM_5_1_4,
        FILM_7_1,
        FILM_7_1_2,
        FILM_7_1_4,
        SMPTE_2_0,
        SMPTE_2_1,
        SMPTE_5_1,
        SMPTE_5_1_2,
        SMPTE_5_1_4,
        SMPTE_7_1,
        SMPTE_7_1_2,
        SMPTE_7_1_4,
    )

    _LAYOUT_MAP = {
        ("LAYOUT.2_0", "SMPTE"): SMPTE_2_0,
        ("LAYOUT.2_0", "FILM"): FILM_2_0,
        ("LAYOUT.2_1", "SMPTE"): SMPTE_2_1,
        ("LAYOUT.2_1", "FILM"): FILM_2_1,
        ("LAYOUT.5_1", "SMPTE"): SMPTE_5_1,
        ("LAYOUT.5_1", "FILM"): FILM_5_1,
        ("LAYOUT.5_1_2", "SMPTE"): SMPTE_5_1_2,
        ("LAYOUT.5_1_2", "FILM"): FILM_5_1_2,
        ("LAYOUT.5_1_4", "SMPTE"): SMPTE_5_1_4,
        ("LAYOUT.5_1_4", "FILM"): FILM_5_1_4,
        ("LAYOUT.7_1", "SMPTE"): SMPTE_7_1,
        ("LAYOUT.7_1", "FILM"): FILM_7_1,
        ("LAYOUT.7_1_2", "SMPTE"): SMPTE_7_1_2,
        ("LAYOUT.7_1_2", "FILM"): FILM_7_1_2,
        ("LAYOUT.7_1_4", "SMPTE"): SMPTE_7_1_4,
        ("LAYOUT.7_1_4", "FILM"): FILM_7_1_4,
    }
    return _LAYOUT_MAP


def build_layout_context(layout_id: str, standard: str = "SMPTE") -> LayoutContext:
    """Return a ``LayoutContext`` for the given ``LAYOUT.*`` ID and ordering standard.

    Looks up the matching preset ``SpeakerLayout`` and wraps it in an immutable
    ``LayoutContext``.  Raises ``ValueError`` for unknown layout_id / standard pairs.

    Parameters
    ----------
    layout_id:
        Canonical ``LAYOUT.*`` ID, e.g. ``"LAYOUT.7_1_4"``.
    standard:
        Channel ordering standard: ``"SMPTE"`` (default) or ``"FILM"``.

    Returns
    -------
    LayoutContext:
        Frozen context; use ``.index_of(SpeakerPosition.LFE)`` etc. to
        look up speaker slots by semantic name.

    Raises
    ------
    ValueError:
        If the layout_id / standard combination has no preset.
    """
    key = (layout_id.strip(), standard.strip().upper())
    layout_map = _get_layout_map()
    speaker_layout = layout_map.get(key)
    if speaker_layout is None:
        available = sorted(layout_map.keys())
        raise ValueError(
            f"No preset SpeakerLayout for layout_id={layout_id!r}, "
            f"standard={standard!r}. "
            f"Available: {available}"
        )
    return LayoutContext(layout=speaker_layout)


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
    """

    stem_id: str
    layout_id: str
    standard: str = "SMPTE"
    params: dict[str, Any] = field(default_factory=dict)
    render_seed: int = 0


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
    lfe_slots:
        LFE channel slot indices in the resolved layout.
    height_slots:
        Height-channel slot indices in the resolved layout.
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
    lfe_slots: list[int]
    height_slots: list[int]
    num_channels: int
    evidence: PluginEvidenceCollector
    notes: list[str]


# ---------------------------------------------------------------------------
# Internal per-stem dispatch
# ---------------------------------------------------------------------------


def _dispatch_one_stem(job: StemJob) -> StemResult:
    """Resolve layout context and collect evidence for a single stem.

    This function runs in a worker thread.  Every object it creates is local
    to this call; no shared mutable state is accessed or written.
    """
    seed = make_stem_seed(job.stem_id, job.render_seed)
    layout_ctx = build_layout_context(job.layout_id, job.standard)
    evidence = PluginEvidenceCollector()
    evidence.set(
        stage_what="dsp_dispatch: layout context resolved",
        stage_why=(
            f"stem {job.stem_id!r} dispatched with layout "
            f"{job.layout_id} ({job.standard})"
        ),
        metrics=[
            {
                "key": "num_channels",
                "value": layout_ctx.num_channels,
                "unit": "channels",
            },
            {
                "key": "lfe_slot_count",
                "value": len(layout_ctx.lfe_slots),
                "unit": "slots",
            },
            {
                "key": "height_slot_count",
                "value": len(layout_ctx.height_slots),
                "unit": "slots",
            },
        ],
    )
    notes: list[str] = [
        f"seed={seed} stem_id={job.stem_id!r} render_seed={job.render_seed}",
        (
            f"layout={job.layout_id} standard={job.standard} "
            f"channels={layout_ctx.num_channels} "
            f"lfe={layout_ctx.lfe_slots} "
            f"height={layout_ctx.height_slots}"
        ),
    ]
    return StemResult(
        stem_id=job.stem_id,
        seed=seed,
        layout_id=job.layout_id,
        standard=job.standard,
        lfe_slots=layout_ctx.lfe_slots,
        height_slots=layout_ctx.height_slots,
        num_channels=layout_ctx.num_channels,
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
