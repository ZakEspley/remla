import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from remla.snapshot_budget import SnapshotBudget, SnapshotBudgetError
from remla.snapshot_config import SnapshotConfig
from remla.snapshot_service import SnapshotBusy, SnapshotNotOwner, SnapshotService, SnapshotUnavailable


class SnapshotServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clock = mock.Mock(return_value=10_000)
        budget = SnapshotBudget(Path(self.directory.name) / "budget.json", clock=self.clock)
        self.worker = mock.Mock(return_value=b"\x89PNG\r\n\x1a\nimage")
        self.service = SnapshotService(budget=budget, capture=self.worker)
        self.config = SnapshotConfig("cam", 2592, 1944)

    async def test_rechecks_owner_before_and_after_capture(self):
        allowed = mock.Mock(return_value=True)
        image = await self.service.capture_png(self.config, allowed)
        self.assertTrue(image.startswith(b"\x89PNG"))
        self.worker.assert_called_once_with(self.config)
        self.assertGreaterEqual(allowed.call_count, 2)

    async def test_non_owner_never_invokes_worker_or_charges_budget(self):
        with self.assertRaises(SnapshotNotOwner):
            await self.service.capture_png(self.config, lambda: False)
        self.worker.assert_not_called()
        self.assertFalse(self.service.budget.path.exists())

    async def test_owner_loss_during_worker_discards_image(self):
        gate = asyncio.Event()
        allowed = mock.Mock(side_effect=[True, False])

        def worker(config):
            return self.worker.return_value

        self.service.capture = worker
        with self.assertRaises(SnapshotNotOwner):
            await self.service.capture_png(self.config, allowed)

    async def test_cooldown_survives_service_recreation(self):
        await self.service.capture_png(self.config, lambda: True)
        another = SnapshotService(budget=SnapshotBudget(self.service.budget.path, clock=self.clock), capture=self.worker)
        with self.assertRaises(SnapshotBudgetError):
            await another.capture_png(self.config, lambda: True)
        self.worker.assert_called_once()
        self.clock.return_value += 10
        await another.capture_png(self.config, lambda: True)
        self.assertEqual(self.worker.call_count, 2)

    async def test_one_capture_in_flight_even_if_owner_disconnects(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_capture(config):
            started.set()
            await release.wait()
            return self.worker.return_value

        self.service.capture_async = slow_capture
        task = asyncio.create_task(self.service.capture_png(self.config, lambda: True))
        await asyncio.wait_for(started.wait(), 1)
        with self.assertRaises(SnapshotBusy):
            await self.service.capture_png(self.config, lambda: True)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done(), "cancellation must wait for the camera worker to release")
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_helper_failure_is_not_a_successful_image(self):
        self.service.capture = mock.Mock(side_effect=SnapshotUnavailable("helper unavailable"))
        with self.assertRaises(SnapshotUnavailable):
            await self.service.capture_png(self.config, lambda: True)


if __name__ == "__main__":
    unittest.main()
