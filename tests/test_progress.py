from __future__ import annotations

import threading
import time
import unittest

from mmo.core.progress import CancelToken, CancelledError, ProgressTracker


class TestCancelToken(unittest.TestCase):
    def test_cancel_token_sets_reason_and_raises(self) -> None:
        token = CancelToken()
        token.cancel("requested by test")
        self.assertTrue(token.is_cancelled)
        self.assertEqual(token.reason, "requested by test")
        with self.assertRaises(CancelledError):
            token.raise_if_cancelled()


class TestProgressTracker(unittest.TestCase):
    def test_eta_is_computed_after_first_step(self) -> None:
        tracker = ProgressTracker(total_steps=4)
        time.sleep(0.002)
        snapshot = tracker.advance(steps=1)
        self.assertGreater(snapshot.progress, 0.0)
        self.assertLess(snapshot.progress, 1.0)
        self.assertIsNotNone(snapshot.eta_seconds)

    def test_thread_safe_advance(self) -> None:
        tracker = ProgressTracker(total_steps=100)

        def _worker() -> None:
            for _ in range(25):
                tracker.advance(steps=1)

        threads = [threading.Thread(target=_worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snapshot = tracker.snapshot()
        self.assertEqual(snapshot.completed_steps, 100)
        self.assertAlmostEqual(snapshot.progress, 1.0, places=6)


if __name__ == "__main__":
    unittest.main()

