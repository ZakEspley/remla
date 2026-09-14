import unittest

from remla.runtime_operations import (
    OperationRegistry,
    OperationTransitionError,
    OutstandingOperationLimit,
    OwnershipManager,
)


class OwnershipManagerTests(unittest.TestCase):
    def test_waiting_users_are_promoted_in_fifo_order(self):
        ownership = OwnershipManager()

        ownership.connect("first")
        ownership.connect("second")
        ownership.connect("third")

        self.assertEqual(ownership.active_owner, "first")
        self.assertEqual(ownership.waiting_users, ["second", "third"])

        ownership.disconnect("first")

        self.assertEqual(ownership.handoff_user, "second")
        self.assertFalse(ownership.can_submit("second"))

        ownership.choose_handoff("second", "continue")

        self.assertEqual(ownership.active_owner, "second")
        self.assertEqual(ownership.waiting_users, ["third"])
        self.assertTrue(ownership.can_submit("second"))

    def test_reset_handoff_requires_explicit_completion(self):
        ownership = OwnershipManager()
        ownership.connect("first")
        ownership.connect("second")

        ownership.disconnect("first")
        ownership.choose_handoff("second", "reset")

        self.assertEqual(ownership.handoff_state, "resetting")
        self.assertFalse(ownership.can_submit("second"))

        ownership.complete_reset(success=True)

        self.assertEqual(ownership.active_owner, "second")
        self.assertTrue(ownership.can_submit("second"))

    def test_disconnect_during_reset_waits_for_reset_completion(self):
        ownership = OwnershipManager()
        ownership.connect("first")
        ownership.connect("second")
        ownership.connect("third")

        ownership.disconnect("first")
        ownership.choose_handoff("second", "reset")
        ownership.disconnect("second")

        self.assertEqual(ownership.handoff_state, "resetting")
        self.assertEqual(ownership.handoff_user, "second")

        ownership.complete_reset(success=True)

        self.assertEqual(ownership.handoff_user, "third")
        self.assertEqual(ownership.handoff_state, "pending")

    def test_failed_reset_blocks_handoff_promotion(self):
        ownership = OwnershipManager()
        ownership.connect("first")
        ownership.connect("second")
        ownership.connect("third")

        ownership.disconnect("first")
        ownership.choose_handoff("second", "reset")
        ownership.complete_reset(success=False)
        ownership.disconnect("second")

        self.assertEqual(ownership.handoff_state, "faulted")
        self.assertIsNone(ownership.active_owner)
        self.assertEqual(ownership.waiting_users, ["third"])


class OperationRegistryTests(unittest.TestCase):
    def test_operations_track_lifecycle_and_outstanding_limit(self):
        registry = OperationRegistry(max_outstanding_per_owner=2, clock=lambda: 100.0)

        first = registry.submit("owner", "camera", "switch", "camera", 30)
        second = registry.submit("owner", "motor", "move", None, 60)

        with self.assertRaises(OutstandingOperationLimit):
            registry.submit("owner", "motor", "move", None, 60)

        registry.start(first.operation_id, timestamp=101.0)
        registry.complete(first.operation_id, result={"channel": 2}, timestamp=102.0)

        self.assertEqual(first.status, "completed")
        self.assertEqual(first.started_at, 101.0)
        self.assertEqual(first.finished_at, 102.0)
        self.assertEqual(first.result, {"channel": 2})

        third = registry.submit("owner", "motor", "move", None, 60)
        self.assertEqual(third.status, "queued")
        self.assertEqual(second.lock_group, None)

    def test_only_one_terminal_transition_is_allowed(self):
        registry = OperationRegistry(max_outstanding_per_owner=1, clock=lambda: 100.0)
        operation = registry.submit("owner", "camera", "switch", "camera", 30)

        registry.fail(operation.operation_id, error={"code": "device_error"}, timestamp=101.0)

        with self.assertRaises(OperationTransitionError):
            registry.complete(operation.operation_id, result={}, timestamp=102.0)

    def test_owner_disconnect_cancels_only_unstarted_operations(self):
        registry = OperationRegistry(max_outstanding_per_owner=3, clock=lambda: 100.0)
        waiting = registry.submit("owner", "camera", "switch", "camera", 30)
        running = registry.submit("owner", "motor", "move", "motion", 60)
        registry.start(running.operation_id, timestamp=101.0)

        cancelled = registry.cancel_waiting_for_owner("owner", timestamp=102.0)

        self.assertEqual(cancelled, [waiting.operation_id])
        self.assertEqual(waiting.status, "cancelled")
        self.assertEqual(running.status, "running")

    def test_timeout_is_terminal_and_appears_in_unfinished_snapshot(self):
        registry = OperationRegistry(max_outstanding_per_owner=1, clock=lambda: 100.0)
        operation = registry.submit("owner", "motor", "move", "motion", 30)

        registry.timeout(operation.operation_id, timestamp=130.0)

        self.assertEqual(operation.status, "timed_out")
        self.assertEqual(
            registry.unfinished_snapshot(),
            [operation.to_dict()],
        )

    def test_invalid_operation_limits_and_timeouts_are_rejected(self):
        with self.assertRaises(ValueError):
            OperationRegistry(max_outstanding_per_owner=0, clock=lambda: 100.0)

        registry = OperationRegistry(max_outstanding_per_owner=1, clock=lambda: 100.0)
        with self.assertRaises(ValueError):
            registry.submit("owner", "camera", "switch", "camera", 0)

    def test_starting_after_deadline_marks_the_operation_timed_out(self):
        registry = OperationRegistry(max_outstanding_per_owner=1, clock=lambda: 100.0)
        operation = registry.submit("owner", "camera", "switch", "camera", 30)

        with self.assertRaises(OperationTransitionError):
            registry.start(operation.operation_id, timestamp=131.0)

        self.assertEqual(operation.status, "timed_out")


if __name__ == "__main__":
    unittest.main()
