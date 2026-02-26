"""Tests for the multithreading harness: dsp_dispatch + render_engine thread safety.

Covers:
- ``src/mmo/core/dsp_dispatch.py`` — ``build_layout_context``, ``make_stem_seed``,
  ``StemJob``, ``StemResult``, ``dispatch_stems``.
- ``src/mmo/core/render_engine.py`` — ``render_scene_to_targets`` with stem
  dispatch (``stem_ids`` / ``stem_max_workers`` options).

Layout fixtures used
--------------------
- ``LAYOUT.7_1_4`` SMPTE: L R C LFE Ls Rs Lrs Rrs TFL TFR TBL TBR
  LFE at slot 3, height at [8, 9, 10, 11].
- ``LAYOUT.7_1_4`` FILM: L C R Ls Rs Lrs Rrs LFE TFL TFR TBL TBR
  LFE at slot 7, height at [8, 9, 10, 11].
"""

from __future__ import annotations

import concurrent.futures
import unittest

from mmo.core.dsp_dispatch import (
    StemJob,
    StemResult,
    build_layout_context,
    dispatch_stems,
    make_stem_seed,
)
from mmo.core.render_contract import build_render_contract
from mmo.core.render_engine import render_scene_to_targets

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SCENE_7_1_4: dict = {
    "schema_version": "0.1.0",
    "scene_id": "SCENE.TEST.MT_RENDER",
    "scene_path": "scenes/test/mt_scene.json",
    "source": {
        "stems_dir": "stems/test",
        "layout_id": "LAYOUT.7_1_4",
        "created_from": "analyze",
    },
    "metadata": {},
}

_STEM_IDS_SMALL: list[str] = [
    "STEM.DIALOGUE.EN",
    "STEM.MUSIC",
    "STEM.SFX",
]

_STEM_IDS_LARGE: list[str] = [
    "STEM.AMBIENCE",
    "STEM.DIALOGUE.EN",
    "STEM.DIALOGUE.FR",
    "STEM.HEIGHT.BIRDS",
    "STEM.HEIGHT.RAIN",
    "STEM.LFE.RUMBLE",
    "STEM.MUSIC",
    "STEM.SFX",
]


def _contract_714_smpte() -> dict:
    return build_render_contract(
        "TARGET.IMMERSIVE.7_1_4",
        "LAYOUT.7_1_4",
        source_layout_id="LAYOUT.7_1_4",
        layout_standard="SMPTE",
        output_formats=["wav"],
    )


def _contract_714_film() -> dict:
    return build_render_contract(
        "TARGET.IMMERSIVE.7_1_4.FILM",
        "LAYOUT.7_1_4",
        source_layout_id="LAYOUT.7_1_4",
        layout_standard="FILM",
        output_formats=["wav"],
    )


def _contract_51() -> dict:
    return build_render_contract(
        "TARGET.SURROUND.5_1",
        "LAYOUT.5_1",
        source_layout_id="LAYOUT.7_1_4",
        downmix_policy_id="POLICY.DOWNMIX.IMMERSIVE_FOLDOWN_V0",
        output_formats=["wav"],
    )


# ---------------------------------------------------------------------------
# TestBuildLayoutContext — layout context factory
# ---------------------------------------------------------------------------


class TestBuildLayoutContext(unittest.TestCase):
    """Verify build_layout_context resolves correct slot positions."""

    def test_smpte_714_lfe_slot(self) -> None:
        ctx = build_layout_context("LAYOUT.7_1_4", "SMPTE")
        # SMPTE 7.1.4: L=0 R=1 C=2 LFE=3 Ls=4 Rs=5 Lrs=6 Rrs=7 TFL=8 TFR=9 TBL=10 TBR=11
        self.assertEqual(ctx.lfe_slots, [3])

    def test_film_714_lfe_slot(self) -> None:
        ctx = build_layout_context("LAYOUT.7_1_4", "FILM")
        # FILM 7.1.4: L=0 C=1 R=2 Ls=3 Rs=4 Lrs=5 Rrs=6 LFE=7 TFL=8 TFR=9 TBL=10 TBR=11
        self.assertEqual(ctx.lfe_slots, [7])

    def test_smpte_714_height_slots(self) -> None:
        ctx = build_layout_context("LAYOUT.7_1_4", "SMPTE")
        self.assertEqual(ctx.height_slots, [8, 9, 10, 11])

    def test_film_714_height_slots(self) -> None:
        ctx = build_layout_context("LAYOUT.7_1_4", "FILM")
        self.assertEqual(ctx.height_slots, [8, 9, 10, 11])

    def test_smpte_714_num_channels(self) -> None:
        ctx = build_layout_context("LAYOUT.7_1_4", "SMPTE")
        self.assertEqual(ctx.num_channels, 12)

    def test_film_714_num_channels(self) -> None:
        ctx = build_layout_context("LAYOUT.7_1_4", "FILM")
        self.assertEqual(ctx.num_channels, 12)

    def test_smpte_51_lfe_slot(self) -> None:
        ctx = build_layout_context("LAYOUT.5_1", "SMPTE")
        # SMPTE 5.1: L=0 R=1 C=2 LFE=3 Ls=4 Rs=5
        self.assertEqual(ctx.lfe_slots, [3])

    def test_film_51_lfe_slot(self) -> None:
        ctx = build_layout_context("LAYOUT.5_1", "FILM")
        # FILM 5.1: L=0 C=1 R=2 Ls=3 Rs=4 LFE=5
        self.assertEqual(ctx.lfe_slots, [5])

    def test_smpte_and_film_714_differ_only_in_lfe_slot(self) -> None:
        smpte = build_layout_context("LAYOUT.7_1_4", "SMPTE")
        film = build_layout_context("LAYOUT.7_1_4", "FILM")
        self.assertNotEqual(smpte.lfe_slots, film.lfe_slots)
        # Height slots and channel count are identical across standards for 7.1.4.
        self.assertEqual(smpte.height_slots, film.height_slots)
        self.assertEqual(smpte.num_channels, film.num_channels)

    def test_default_standard_is_smpte(self) -> None:
        ctx_default = build_layout_context("LAYOUT.7_1_4")
        ctx_smpte = build_layout_context("LAYOUT.7_1_4", "SMPTE")
        self.assertEqual(ctx_default.lfe_slots, ctx_smpte.lfe_slots)
        self.assertEqual(ctx_default.height_slots, ctx_smpte.height_slots)

    def test_unknown_layout_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            build_layout_context("LAYOUT.DOES_NOT_EXIST", "SMPTE")

    def test_unknown_standard_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            build_layout_context("LAYOUT.7_1_4", "NOT_A_STANDARD")

    def test_layout_context_is_immutable(self) -> None:
        ctx = build_layout_context("LAYOUT.7_1_4", "SMPTE")
        # LayoutContext is a frozen dataclass — reassignment raises AttributeError.
        with self.assertRaises(AttributeError):
            ctx.layout = None  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestMakeStemSeed — deterministic per-stem seeding
# ---------------------------------------------------------------------------


class TestMakeStemSeed(unittest.TestCase):
    """Verify make_stem_seed is deterministic and stem-unique."""

    def test_same_input_gives_same_seed(self) -> None:
        a = make_stem_seed("STEM.DIALOGUE.EN", 0)
        b = make_stem_seed("STEM.DIALOGUE.EN", 0)
        self.assertEqual(a, b)

    def test_different_stem_ids_give_different_seeds(self) -> None:
        a = make_stem_seed("STEM.DIALOGUE.EN", 0)
        b = make_stem_seed("STEM.MUSIC", 0)
        self.assertNotEqual(a, b)

    def test_different_render_seeds_give_different_seeds(self) -> None:
        a = make_stem_seed("STEM.DIALOGUE.EN", 0)
        b = make_stem_seed("STEM.DIALOGUE.EN", 1)
        self.assertNotEqual(a, b)

    def test_seed_is_non_negative_int(self) -> None:
        seed = make_stem_seed("STEM.TEST", 42)
        self.assertIsInstance(seed, int)
        self.assertGreaterEqual(seed, 0)

    def test_seed_within_31_bit_range(self) -> None:
        for stem_id in _STEM_IDS_LARGE:
            with self.subTest(stem_id=stem_id):
                seed = make_stem_seed(stem_id)
                self.assertLessEqual(seed, 0x7FFF_FFFF)

    def test_default_render_seed_is_zero(self) -> None:
        a = make_stem_seed("STEM.TEST")
        b = make_stem_seed("STEM.TEST", 0)
        self.assertEqual(a, b)

    def test_all_large_stem_ids_have_unique_seeds(self) -> None:
        seeds = [make_stem_seed(sid) for sid in _STEM_IDS_LARGE]
        self.assertEqual(len(seeds), len(set(seeds)), "Seed collision among stem IDs")


# ---------------------------------------------------------------------------
# TestDispatchStemsBasic — basic dispatch behaviour
# ---------------------------------------------------------------------------


class TestDispatchStemsBasic(unittest.TestCase):
    """Verify basic dispatch_stems properties."""

    def test_empty_jobs_returns_empty(self) -> None:
        self.assertEqual(dispatch_stems([]), [])

    def test_single_job_serial(self) -> None:
        jobs = [StemJob("STEM.DIALOGUE", "LAYOUT.7_1_4", "SMPTE")]
        results = dispatch_stems(jobs, max_workers=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].stem_id, "STEM.DIALOGUE")

    def test_results_sorted_by_stem_id(self) -> None:
        # Supply jobs in reverse alphabetical order.
        jobs = [
            StemJob("STEM.SFX", "LAYOUT.7_1_4", "SMPTE"),
            StemJob("STEM.MUSIC", "LAYOUT.7_1_4", "SMPTE"),
            StemJob("STEM.DIALOGUE", "LAYOUT.7_1_4", "SMPTE"),
        ]
        results = dispatch_stems(jobs, max_workers=4)
        ids = [r.stem_id for r in results]
        self.assertEqual(ids, sorted(ids))

    def test_result_carries_correct_stem_id(self) -> None:
        jobs = [StemJob("STEM.TEST.XYZ", "LAYOUT.5_1", "SMPTE")]
        result = dispatch_stems(jobs)[0]
        self.assertEqual(result.stem_id, "STEM.TEST.XYZ")

    def test_result_carries_layout_info_smpte_714(self) -> None:
        jobs = [StemJob("STEM.BED", "LAYOUT.7_1_4", "SMPTE")]
        result = dispatch_stems(jobs)[0]
        self.assertEqual(result.layout_id, "LAYOUT.7_1_4")
        self.assertEqual(result.standard, "SMPTE")
        self.assertEqual(result.num_channels, 12)
        self.assertEqual(result.lfe_slots, [3])
        self.assertEqual(result.height_slots, [8, 9, 10, 11])

    def test_result_carries_layout_info_film_714(self) -> None:
        jobs = [StemJob("STEM.BED", "LAYOUT.7_1_4", "FILM")]
        result = dispatch_stems(jobs)[0]
        self.assertEqual(result.layout_id, "LAYOUT.7_1_4")
        self.assertEqual(result.standard, "FILM")
        self.assertEqual(result.num_channels, 12)
        self.assertEqual(result.lfe_slots, [7])
        self.assertEqual(result.height_slots, [8, 9, 10, 11])

    def test_result_carries_deterministic_seed(self) -> None:
        jobs = [StemJob("STEM.FIXED", "LAYOUT.2_0", "SMPTE", render_seed=7)]
        result = dispatch_stems(jobs)[0]
        expected_seed = make_stem_seed("STEM.FIXED", 7)
        self.assertEqual(result.seed, expected_seed)

    def test_result_has_non_empty_notes(self) -> None:
        jobs = [StemJob("STEM.X", "LAYOUT.5_1", "FILM")]
        result = dispatch_stems(jobs)[0]
        self.assertIsInstance(result.notes, list)
        self.assertGreater(len(result.notes), 0)

    def test_film_714_has_lfe_slot_7_not_3(self) -> None:
        smpte_res = dispatch_stems([StemJob("STEM.A", "LAYOUT.7_1_4", "SMPTE")])[0]
        film_res = dispatch_stems([StemJob("STEM.B", "LAYOUT.7_1_4", "FILM")])[0]
        self.assertEqual(smpte_res.lfe_slots, [3])
        self.assertEqual(film_res.lfe_slots, [7])

    def test_result_is_stem_result_instance(self) -> None:
        jobs = [StemJob("STEM.CHECK", "LAYOUT.2_0", "SMPTE")]
        result = dispatch_stems(jobs)[0]
        self.assertIsInstance(result, StemResult)


# ---------------------------------------------------------------------------
# TestDispatchStemsDeterminism — serial == parallel, repeated calls equal
# ---------------------------------------------------------------------------


class TestDispatchStemsDeterminism(unittest.TestCase):
    """Verify dispatch_stems is fully deterministic regardless of worker count."""

    def _make_jobs(
        self, stem_ids: list[str], layout_id: str, standard: str
    ) -> list[StemJob]:
        return [StemJob(sid, layout_id, standard) for sid in stem_ids]

    def _comparable(self, results: list[StemResult]) -> list[tuple]:
        return [
            (
                r.stem_id,
                r.seed,
                r.layout_id,
                r.standard,
                r.lfe_slots,
                r.height_slots,
                r.num_channels,
                r.notes,
            )
            for r in results
        ]

    def test_serial_equals_parallel_smpte_714(self) -> None:
        jobs = self._make_jobs(_STEM_IDS_SMALL, "LAYOUT.7_1_4", "SMPTE")
        serial = self._comparable(dispatch_stems(jobs, max_workers=1))
        parallel = self._comparable(dispatch_stems(jobs, max_workers=4))
        self.assertEqual(serial, parallel)

    def test_serial_equals_parallel_film_714(self) -> None:
        jobs = self._make_jobs(_STEM_IDS_SMALL, "LAYOUT.7_1_4", "FILM")
        serial = self._comparable(dispatch_stems(jobs, max_workers=1))
        parallel = self._comparable(dispatch_stems(jobs, max_workers=4))
        self.assertEqual(serial, parallel)

    def test_repeated_serial_calls_equal(self) -> None:
        jobs = self._make_jobs(_STEM_IDS_LARGE, "LAYOUT.7_1_4", "SMPTE")
        a = self._comparable(dispatch_stems(jobs, max_workers=1))
        b = self._comparable(dispatch_stems(jobs, max_workers=1))
        self.assertEqual(a, b)

    def test_repeated_parallel_calls_equal(self) -> None:
        jobs = self._make_jobs(_STEM_IDS_LARGE, "LAYOUT.7_1_4", "SMPTE")
        a = self._comparable(dispatch_stems(jobs, max_workers=4))
        b = self._comparable(dispatch_stems(jobs, max_workers=4))
        self.assertEqual(a, b)

    def test_worker_count_1_2_4_all_equal(self) -> None:
        jobs = self._make_jobs(_STEM_IDS_SMALL, "LAYOUT.7_1_4", "SMPTE")
        r1 = self._comparable(dispatch_stems(jobs, max_workers=1))
        r2 = self._comparable(dispatch_stems(jobs, max_workers=2))
        r4 = self._comparable(dispatch_stems(jobs, max_workers=4))
        self.assertEqual(r1, r2)
        self.assertEqual(r2, r4)

    def test_smpte_and_film_714_results_differ_in_lfe_slot(self) -> None:
        smpte_jobs = self._make_jobs(_STEM_IDS_SMALL, "LAYOUT.7_1_4", "SMPTE")
        film_jobs = self._make_jobs(_STEM_IDS_SMALL, "LAYOUT.7_1_4", "FILM")
        smpte = dispatch_stems(smpte_jobs, max_workers=4)
        film = dispatch_stems(film_jobs, max_workers=4)
        for sr, fr in zip(smpte, film):
            with self.subTest(stem_id=sr.stem_id):
                self.assertEqual(sr.lfe_slots, [3])
                self.assertEqual(fr.lfe_slots, [7])
                # Height slots are the same across standards.
                self.assertEqual(sr.height_slots, fr.height_slots)


# ---------------------------------------------------------------------------
# TestDispatchStemsConcurrent — concurrent dispatch_stems calls
# ---------------------------------------------------------------------------


class TestDispatchStemsConcurrent(unittest.TestCase):
    """Verify dispatch_stems is thread-safe when called from concurrent threads."""

    def _key(self, results: list[StemResult]) -> list[tuple]:
        return [
            (r.stem_id, r.seed, r.lfe_slots, r.height_slots, r.num_channels)
            for r in results
        ]

    def test_concurrent_smpte_dispatch_equal(self) -> None:
        jobs = [StemJob(sid, "LAYOUT.7_1_4", "SMPTE") for sid in _STEM_IDS_LARGE]
        n = 8

        def _run() -> list[StemResult]:
            return dispatch_stems(jobs, max_workers=4)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as executor:
            futures = [executor.submit(_run) for _ in range(n)]
            collected = [f.result() for f in concurrent.futures.as_completed(futures)]

        reference = self._key(collected[0])
        for results in collected[1:]:
            self.assertEqual(self._key(results), reference)

    def test_concurrent_film_dispatch_equal(self) -> None:
        jobs = [StemJob(sid, "LAYOUT.7_1_4", "FILM") for sid in _STEM_IDS_LARGE]
        n = 8

        def _run() -> list[StemResult]:
            return dispatch_stems(jobs, max_workers=4)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n) as executor:
            futures = [executor.submit(_run) for _ in range(n)]
            collected = [f.result() for f in concurrent.futures.as_completed(futures)]

        reference = self._key(collected[0])
        for results in collected[1:]:
            self.assertEqual(self._key(results), reference)

    def test_concurrent_mixed_standard_dispatch(self) -> None:
        """Mixed SMPTE/FILM jobs dispatched concurrently produce correct lfe_slots."""
        smpte_jobs = [StemJob(sid, "LAYOUT.7_1_4", "SMPTE") for sid in _STEM_IDS_SMALL]
        film_jobs = [StemJob(sid, "LAYOUT.7_1_4", "FILM") for sid in _STEM_IDS_SMALL]

        results: list[list[StemResult]] = []

        def _run_smpte() -> list[StemResult]:
            return dispatch_stems(smpte_jobs, max_workers=2)

        def _run_film() -> list[StemResult]:
            return dispatch_stems(film_jobs, max_workers=2)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            smpte_fut = [executor.submit(_run_smpte) for _ in range(2)]
            film_fut = [executor.submit(_run_film) for _ in range(2)]
            smpte_results = [f.result() for f in smpte_fut]
            film_results = [f.result() for f in film_fut]

        for smpte_res in smpte_results:
            for r in smpte_res:
                self.assertEqual(r.lfe_slots, [3], f"SMPTE {r.stem_id}")
        for film_res in film_results:
            for r in film_res:
                self.assertEqual(r.lfe_slots, [7], f"FILM {r.stem_id}")


# ---------------------------------------------------------------------------
# TestRenderEngineWithStemDispatch — stem_ids option integration
# ---------------------------------------------------------------------------


class TestRenderEngineWithStemDispatch(unittest.TestCase):
    """Verify render_scene_to_targets integrates stem dispatch correctly."""

    def test_stem_dispatch_adds_note_to_job(self) -> None:
        report = render_scene_to_targets(
            _SCENE_7_1_4,
            [_contract_714_smpte()],
            {"dry_run": True, "stem_ids": _STEM_IDS_SMALL, "stem_max_workers": 2},
        )
        all_notes = [n for job in report["jobs"] for n in job["notes"]]
        stem_notes = [n for n in all_notes if "stem_dispatch" in n]
        self.assertGreater(len(stem_notes), 0)

    def test_stem_dispatch_note_mentions_stem_count(self) -> None:
        report = render_scene_to_targets(
            _SCENE_7_1_4,
            [_contract_714_smpte()],
            {"dry_run": True, "stem_ids": _STEM_IDS_SMALL, "stem_max_workers": 1},
        )
        all_notes = [n for job in report["jobs"] for n in job["notes"]]
        stem_notes = [n for n in all_notes if "stem_dispatch" in n]
        self.assertTrue(
            any(str(len(_STEM_IDS_SMALL)) in n for n in stem_notes),
            f"Expected stem count {len(_STEM_IDS_SMALL)} in notes: {stem_notes}",
        )

    def test_stem_dispatch_is_deterministic(self) -> None:
        opts = {
            "dry_run": True,
            "stem_ids": _STEM_IDS_SMALL,
            "stem_max_workers": 2,
        }
        a = render_scene_to_targets(_SCENE_7_1_4, [_contract_714_smpte()], opts)
        b = render_scene_to_targets(_SCENE_7_1_4, [_contract_714_smpte()], opts)
        self.assertEqual(a, b)

    def test_stem_worker_count_does_not_affect_output(self) -> None:
        contract = _contract_714_smpte()
        r1 = render_scene_to_targets(
            _SCENE_7_1_4, [contract],
            {"dry_run": True, "stem_ids": _STEM_IDS_SMALL, "stem_max_workers": 1},
        )
        r4 = render_scene_to_targets(
            _SCENE_7_1_4, [contract],
            {"dry_run": True, "stem_ids": _STEM_IDS_SMALL, "stem_max_workers": 4},
        )
        self.assertEqual(r1, r4)

    def test_no_stem_ids_produces_no_stem_dispatch_note(self) -> None:
        report = render_scene_to_targets(
            _SCENE_7_1_4,
            [_contract_714_smpte()],
            {"dry_run": True},
        )
        all_notes = [n for job in report["jobs"] for n in job["notes"]]
        stem_notes = [n for n in all_notes if "stem_dispatch" in n]
        self.assertEqual(len(stem_notes), 0)

    def test_multi_target_each_job_gets_stem_dispatch_note(self) -> None:
        contracts = [_contract_714_smpte(), _contract_51()]
        report = render_scene_to_targets(
            _SCENE_7_1_4,
            contracts,
            {
                "dry_run": True,
                "stem_ids": _STEM_IDS_SMALL,
                "stem_max_workers": 2,
                "max_workers": 2,
            },
        )
        self.assertEqual(len(report["jobs"]), 2)
        all_notes = [n for job in report["jobs"] for n in job["notes"]]
        stem_notes = [n for n in all_notes if "stem_dispatch" in n]
        # One note per target job.
        self.assertGreaterEqual(len(stem_notes), 2)

    def test_smpte_and_film_contracts_produce_different_notes(self) -> None:
        """SMPTE and FILM contracts dispatch stems with different active standards."""
        opts = {"dry_run": True, "stem_ids": ["STEM.BED"], "stem_max_workers": 1}
        r_smpte = render_scene_to_targets(
            _SCENE_7_1_4, [_contract_714_smpte()], opts
        )
        r_film = render_scene_to_targets(
            _SCENE_7_1_4, [_contract_714_film()], opts
        )
        smpte_notes = " ".join(n for job in r_smpte["jobs"] for n in job["notes"])
        film_notes = " ".join(n for job in r_film["jobs"] for n in job["notes"])
        # The standard name appears in the stem dispatch note.
        self.assertIn("SMPTE", smpte_notes)
        self.assertIn("FILM", film_notes)
        self.assertNotEqual(smpte_notes, film_notes)


# ---------------------------------------------------------------------------
# TestConcurrentRenderDeterminism — concurrent render_scene_to_targets
# ---------------------------------------------------------------------------


class TestConcurrentRenderDeterminism(unittest.TestCase):
    """Verify render_scene_to_targets is thread-safe when called concurrently."""

    def test_concurrent_render_calls_produce_equal_results(self) -> None:
        contracts = [_contract_714_smpte(), _contract_51()]
        opts = {
            "dry_run": True,
            "max_workers": 2,
            "stem_ids": _STEM_IDS_LARGE,
            "stem_max_workers": 4,
        }
        n_concurrent = 6

        def _run() -> dict:
            return render_scene_to_targets(_SCENE_7_1_4, contracts, opts)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_concurrent) as executor:
            futures = [executor.submit(_run) for _ in range(n_concurrent)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        reference = results[0]
        for r in results[1:]:
            self.assertEqual(r, reference)

    def test_concurrent_smpte_vs_film_render(self) -> None:
        """Concurrent SMPTE and FILM renders produce mutually consistent results."""
        opts = {"dry_run": True, "stem_ids": _STEM_IDS_SMALL, "stem_max_workers": 2}

        def _run_smpte() -> dict:
            return render_scene_to_targets(_SCENE_7_1_4, [_contract_714_smpte()], opts)

        def _run_film() -> dict:
            return render_scene_to_targets(_SCENE_7_1_4, [_contract_714_film()], opts)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            smpte_futs = [executor.submit(_run_smpte) for _ in range(3)]
            film_futs = [executor.submit(_run_film) for _ in range(3)]
            smpte_results = [f.result() for f in smpte_futs]
            film_results = [f.result() for f in film_futs]

        # All SMPTE results equal each other.
        for r in smpte_results[1:]:
            self.assertEqual(r, smpte_results[0])
        # All FILM results equal each other.
        for r in film_results[1:]:
            self.assertEqual(r, film_results[0])
        # SMPTE and FILM results differ (different standards in notes).
        self.assertNotEqual(smpte_results[0], film_results[0])

    def test_job_level_and_stem_level_workers_independent(self) -> None:
        """max_workers (job level) and stem_max_workers (stem level) are orthogonal."""
        contracts = [_contract_714_smpte(), _contract_51()]
        r_j1_s1 = render_scene_to_targets(
            _SCENE_7_1_4, contracts,
            {"dry_run": True, "max_workers": 1, "stem_ids": _STEM_IDS_SMALL,
             "stem_max_workers": 1},
        )
        r_j4_s4 = render_scene_to_targets(
            _SCENE_7_1_4, contracts,
            {"dry_run": True, "max_workers": 4, "stem_ids": _STEM_IDS_SMALL,
             "stem_max_workers": 4},
        )
        self.assertEqual(r_j1_s1, r_j4_s4)


if __name__ == "__main__":
    unittest.main()
