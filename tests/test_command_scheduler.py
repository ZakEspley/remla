import asyncio
import unittest

from remla.command_scheduler import CommandScheduler
from remla.runtime_operations import OperationRegistry


class CommandSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = OperationRegistry(max_outstanding_per_owner=4, clock=lambda: 0.0)
        self.scheduler = CommandScheduler(self.registry, clock=lambda: 1.0)

    async def test_same_lock_group_runs_commands_sequentially(self):
        first = self.registry.submit("owner", "camera", "switch", "camera", 30)
        second = self.registry.submit("owner", "camera", "switch", "camera", 30)
        started = []
        first_started = asyncio.Event()
        allow_first = asyncio.Event()

        async def first_command():
            started.append("first")
            first_started.set()
            await allow_first.wait()
            return {"channel": 1}

        async def second_command():
            started.append("second")
            return {"channel": 2}

        first_task = asyncio.create_task(self.scheduler.execute(first, first_command))
        await first_started.wait()
        second_task = asyncio.create_task(self.scheduler.execute(second, second_command))
        await asyncio.sleep(0)

        self.assertEqual(started, ["first"])

        allow_first.set()
        await first_task
        await second_task

        self.assertEqual(started, ["first", "second"])
        self.assertEqual(first.status, "completed")
        self.assertEqual(second.status, "completed")

    async def test_ungrouped_commands_run_concurrently(self):
        first = self.registry.submit("owner", "camera", "switch", None, 30)
        second = self.registry.submit("owner", "motor", "move", None, 30)
        started = []
        started_both = asyncio.Event()
        allow_completion = asyncio.Event()

        async def command(name):
            started.append(name)
            if len(started) == 2:
                started_both.set()
            await allow_completion.wait()
            return {"name": name}

        first_task = asyncio.create_task(self.scheduler.execute(first, lambda: command("first")))
        second_task = asyncio.create_task(self.scheduler.execute(second, lambda: command("second")))
        await started_both.wait()

        self.assertCountEqual(started, ["first", "second"])

        allow_completion.set()
        await first_task
        await second_task

    async def test_timeout_marks_operation_terminal(self):
        operation = self.registry.submit("owner", "camera", "switch", "camera", 0.001)
        scheduler = CommandScheduler(self.registry, clock=lambda: 0.0)

        async def slow_command():
            await asyncio.sleep(1)

        with self.assertRaises(asyncio.TimeoutError):
            await scheduler.execute(operation, slow_command)

        self.assertEqual(operation.status, "timed_out")
