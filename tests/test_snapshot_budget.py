import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from remla.snapshot_budget import SnapshotBudget, SnapshotBudgetError


class SnapshotBudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "budget.json"
        self.clock = mock.Mock(return_value=10_000)
        self.budget = SnapshotBudget(self.path, clock=self.clock, max_per_hour=2)

    def test_cooldown_and_window_survive_new_instance(self):
        self.budget.reserve()
        newer = SnapshotBudget(self.path, clock=self.clock, max_per_hour=2)
        with self.assertRaises(SnapshotBudgetError):
            newer.reserve()
        self.clock.return_value += 9
        with self.assertRaisesRegex(SnapshotBudgetError, "cooldown"):
            newer.reserve()
        self.clock.return_value += 1
        newer.reserve()
        self.clock.return_value += 10
        with self.assertRaises(SnapshotBudgetError):
            newer.reserve()
        self.clock.return_value += 3600
        newer.reserve()

    def test_corrupt_state_fails_closed_and_is_not_overwritten(self):
        self.path.write_text("not json")
        with self.assertRaises(SnapshotBudgetError):
            self.budget.reserve()
        self.assertEqual(self.path.read_text(), "not json")

    def test_clock_rollback_fails_closed(self):
        self.budget.reserve()
        self.clock.return_value -= 5
        with self.assertRaises(SnapshotBudgetError):
            self.budget.reserve()

    def test_default_hourly_limit_blocks_101st_attempt_after_short_cooldowns(self):
        budget = SnapshotBudget(self.path, clock=self.clock)
        for attempt in range(100):
            budget.reserve()
            self.clock.return_value += 10
        with self.assertRaisesRegex(SnapshotBudgetError, "exhausted"):
            budget.reserve()
        self.assertEqual(len(json.loads(self.path.read_text())["attempts"]), 100)
        self.clock.return_value += 3600
        budget.reserve()
        self.assertEqual(len(json.loads(self.path.read_text())["attempts"]), 1)

    def test_existing_three_attempt_ledger_can_be_extended_without_reset(self):
        self.path.write_text(json.dumps({"attempts": [10_000, 10_010, 10_020]}))
        self.clock.return_value = 10_030
        SnapshotBudget(self.path, clock=self.clock).reserve()
        self.assertEqual(len(json.loads(self.path.read_text())["attempts"]), 4)

    def test_realistic_epoch_ledger_stays_below_size_limit_across_restart(self):
        self.clock.return_value = 1_795_000_000.123456
        for _ in range(100):
            SnapshotBudget(self.path, clock=self.clock).reserve()
            self.clock.return_value += 10.125
        self.assertLess(self.path.stat().st_size, 4096)
        with self.assertRaisesRegex(SnapshotBudgetError, "exhausted"):
            SnapshotBudget(self.path, clock=self.clock).reserve()
        self.clock.return_value += 3600
        SnapshotBudget(self.path, clock=self.clock).reserve()


if __name__ == "__main__":
    unittest.main()
