import asyncio
import importlib
import json
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor


experiment_module = importlib.import_module("remla.labcontrol.Experiment")


class QueuedJsonWebSocket:
    subprotocol = "remla-json-v1"

    def __init__(self):
        self.incoming = asyncio.Queue()
        self.frames = []
        self.changed = asyncio.Condition()
        self.hold_first_revision = False
        self.first_revision_sending = asyncio.Event()
        self.later_revision_sending = asyncio.Event()
        self.release_first_revision = asyncio.Event()
        self.hold_results = False
        self.block_reply_ids = set()
        self.result_sending = asyncio.Event()
        self.release_results = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        frame = await self.incoming.get()
        if frame is None:
            raise StopAsyncIteration
        return frame

    async def send(self, frame):
        message = json.loads(frame)
        if message["type"] == "result" and (self.hold_results or message["meta"].get("replyId") in self.block_reply_ids):
            self.result_sending.set()
            await self.release_results.wait()
        if message["payload"].get("name") == "state.changed":
            if message["payload"]["data"]["revision"] == 1:
                self.first_revision_sending.set()
                if self.hold_first_revision:
                    await self.release_first_revision.wait()
            else:
                self.later_revision_sending.set()
        await asyncio.sleep(0)
        async with self.changed:
            self.frames.append(message)
            self.changed.notify_all()

    def command(self, device_name, token):
        message_id = str(uuid.uuid4())
        self.incoming.put_nowait(json.dumps({
            "meta": {"messageId": message_id, "version": "1.0.0"},
            "type": "command",
            "payload": {
                "deviceName": device_name,
                "commandName": "move",
                "parameters": {"arguments": [token]},
            },
        }))
        return message_id

    async def result(self, message_id):
        async def receive():
            async with self.changed:
                await self.changed.wait_for(lambda: any(
                    frame["type"] == "result"
                    and frame["meta"].get("replyId") == message_id
                    for frame in self.frames
                ))
                return next(
                    frame for frame in self.frames
                    if frame["type"] == "result"
                    and frame["meta"].get("replyId") == message_id
                )

        return await asyncio.wait_for(receive(), timeout=1)


class GatedJsonDevice:
    def __init__(self, name, loop, tokens):
        self.name = name
        self.loop = loop
        self.started = {token: asyncio.Event() for token in tokens}
        self.finished = {token: asyncio.Event() for token in tokens}
        self.release = {token: threading.Event() for token in tokens}
        self.reset_called = asyncio.Event()
        self.safe_stopped = asyncio.Event()

    def cmdHandler(self, method, params, device_name):
        token = params[0]
        self.loop.call_soon_threadsafe(self.started[token].set)
        if not self.release[token].wait(timeout=5):
            raise RuntimeError("Test did not release the fake controller")
        self.loop.call_soon_threadsafe(self.finished[token].set)
        return "MESSAGE", f"{device_name}:{method}:{token}"

    def getState(self):
        return {"ready": True}

    def reset(self):
        self.loop.call_soon_threadsafe(self.reset_called.set)

    def safe_stop(self):
        self.loop.call_soon_threadsafe(self.safe_stopped.set)


class ExperimentJsonCommandDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.experiment = experiment_module.Experiment("RemoteLabs")
        self.experiment._runtime_state = "ready"
        self.websocket = QueuedJsonWebSocket()
        loop = asyncio.get_running_loop()
        self.first = GatedJsonDevice("first", loop, ["one", "two"])
        self.second = GatedJsonDevice("second", loop, ["other"])
        for device in [self.first, self.second]:
            self.experiment.addDevice(device)
        self.experiment.addLockGroup("motion", [self.first])
        self.experiment.addLockGroup("independent", [self.second])
        self.connection = asyncio.create_task(
            self.experiment.handleConnection(self.websocket, "/")
        )

    async def asyncTearDown(self):
        self.websocket.release_first_revision.set()
        self.websocket.release_results.set()
        for device in [self.first, self.second]:
            for release in device.release.values():
                release.set()
        self.websocket.incoming.put_nowait(None)
        await asyncio.wait_for(self.connection, timeout=2)
        if self.experiment.executor is not None:
            self.experiment.executor.shutdown(wait=True)

    async def wait_started(self, device, token):
        try:
            await asyncio.wait_for(device.started[token].wait(), timeout=1)
        except asyncio.TimeoutError:
            self.fail(
                f"{device.name}/{token} did not start while the earlier command "
                "was still gated on the same owner WebSocket"
            )

    async def assert_success(self, message_id):
        result = await self.websocket.result(message_id)
        self.assertEqual(result["meta"]["replyId"], message_id)
        self.assertEqual(result["payload"]["status"], 200)
        self.assertTrue(result["payload"]["ok"])
        matching = [frame for frame in self.websocket.frames
                    if frame["type"] == "result"
                    and frame["meta"].get("replyId") == message_id]
        self.assertEqual(len(matching), 1)

    async def test_distinct_groups_start_from_one_owner_and_results_are_correlated(self):
        first_id = self.websocket.command("first", "one")
        await self.wait_started(self.first, "one")
        second_id = self.websocket.command("second", "other")
        await self.wait_started(self.second, "other")

        self.assertFalse(self.first.finished["one"].is_set())
        self.assertFalse(self.second.finished["other"].is_set())
        self.second.release["other"].set()
        await self.assert_success(second_id)
        self.assertFalse(self.first.finished["one"].is_set())
        self.assertFalse(any(frame["type"] == "result"
                             and frame["meta"].get("replyId") == first_id
                             for frame in self.websocket.frames))
        self.first.release["one"].set()
        await self.assert_success(first_id)

    async def test_same_group_stays_serialized_while_another_group_runs(self):
        first_id = self.websocket.command("first", "one")
        await self.wait_started(self.first, "one")
        queued_id = self.websocket.command("first", "two")
        independent_id = self.websocket.command("second", "other")
        await self.wait_started(self.second, "other")

        self.assertFalse(self.first.started["two"].is_set())
        self.second.release["other"].set()
        await self.assert_success(independent_id)
        self.assertFalse(self.first.started["two"].is_set())
        self.first.release["one"].set()
        await self.wait_started(self.first, "two")
        self.assertTrue(self.first.finished["one"].is_set())
        self.first.release["two"].set()
        await self.assert_success(first_id)
        await self.assert_success(queued_id)

    async def test_owner_disconnect_drains_running_and_cancels_queued_before_reset(self):
        self.websocket.command("first", "one")
        await self.wait_started(self.first, "one")
        self.websocket.command("first", "two")
        self.websocket.command("second", "other")
        await self.wait_started(self.second, "other")
        self.websocket.incoming.put_nowait(None)

        async def wait_for_owner_removal():
            while self.experiment.ownership.active_owner is self.websocket:
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_for_owner_removal(), timeout=1)
        self.assertFalse(self.connection.done())
        self.assertFalse(self.first.reset_called.is_set())
        self.assertFalse(self.second.reset_called.is_set())
        self.assertFalse(self.first.started["two"].is_set())
        self.first.release["one"].set()
        self.second.release["other"].set()
        await asyncio.wait_for(asyncio.shield(self.connection), timeout=1)
        self.assertFalse(self.first.started["two"].is_set())
        self.assertTrue(self.first.finished["one"].is_set())
        self.assertTrue(self.second.finished["other"].is_set())
        self.assertTrue(self.first.reset_called.is_set())
        self.assertTrue(self.second.reset_called.is_set())

    async def test_outstanding_limit_rejects_correlated_command_without_starting_it(self):
        self.experiment.operation_registry.max_outstanding_per_owner = 1
        first_id = self.websocket.command("first", "one")
        await self.wait_started(self.first, "one")
        rejected_id = self.websocket.command("second", "other")
        result = await self.websocket.result(rejected_id)

        self.assertFalse(result["payload"]["ok"])
        self.assertEqual(result["payload"]["status"], 429)
        self.assertEqual(result["payload"]["error"]["code"], "outstanding_operation_limit")
        self.assertFalse(self.second.started["other"].is_set())
        self.assertFalse(self.first.finished["one"].is_set())
        self.first.release["one"].set()
        await self.assert_success(first_id)

    async def test_concurrent_state_changed_revisions_stay_ordered_when_send_yields(self):
        self.websocket.hold_first_revision = True
        first_id = self.websocket.command("first", "one")
        await self.wait_started(self.first, "one")
        second_id = self.websocket.command("second", "other")
        await self.wait_started(self.second, "other")
        self.first.release["one"].set()
        await asyncio.wait_for(self.websocket.first_revision_sending.wait(), timeout=1)
        self.second.release["other"].set()
        await asyncio.wait_for(self.second.finished["other"].wait(), timeout=1)
        try:
            await asyncio.wait_for(self.websocket.later_revision_sending.wait(), timeout=0.05)
        except asyncio.TimeoutError:
            pass
        self.websocket.release_first_revision.set()
        await self.assert_success(first_id)
        await self.assert_success(second_id)

        revisions = [frame["payload"]["data"]["revision"]
                     for frame in self.websocket.frames
                     if frame["payload"].get("name") == "state.changed"]
        self.assertEqual(revisions, [1, 2])

    async def test_fault_cancels_queued_json_command_with_correlated_result(self):
        self.experiment.default_command_timeout = 0.05
        first_id = self.websocket.command("first", "one")
        await self.wait_started(self.first, "one")
        queued_id = self.websocket.command("first", "two")
        first_result = await self.websocket.result(first_id)
        queued_result = await self.websocket.result(queued_id)
        self.assertEqual(first_result["payload"]["error"]["code"], "device_faulted")
        self.assertEqual(queued_result["payload"]["error"]["code"], "operation_cancelled")
        self.assertEqual(queued_result["payload"]["status"], 409)
        self.assertFalse(self.first.started["two"].is_set())
        self.first.release["one"].set()

    async def test_slow_replies_bound_tracked_json_tasks_to_operation_limit(self):
        self.experiment.max_outstanding_operations = 1
        self.websocket.hold_results = True
        self.websocket.command("missing", "one")
        await asyncio.wait_for(self.websocket.result_sending.wait(), timeout=1)
        rejected_id = self.websocket.command("second", "other")
        for index in range(100):
            self.websocket.command("missing", str(index))
        await asyncio.sleep(0.05)
        self.assertLessEqual(len(self.experiment._client_command_tasks.get(self.websocket, ())), 1)
        self.assertFalse(self.second.started["other"].is_set())
        self.websocket.release_results.set()
        rejected = await self.websocket.result(rejected_id)
        self.assertEqual(rejected["payload"]["status"], 429)
        self.assertEqual(rejected["payload"]["error"]["code"], "outstanding_operation_limit")
        self.assertFalse(self.second.started["other"].is_set())

    async def test_waiting_client_disconnect_cleans_up_blocked_replies(self):
        await asyncio.sleep(0)
        waiting = QueuedJsonWebSocket()
        waiting.hold_results = True
        connection = asyncio.create_task(self.experiment.handleConnection(waiting, "/"))
        try:
            waiting.command("first", "one")
            await asyncio.wait_for(waiting.result_sending.wait(), timeout=1)
            waiting.incoming.put_nowait(None)
            await asyncio.wait_for(asyncio.shield(connection), timeout=1)
            self.assertFalse(self.experiment._client_command_tasks.get(waiting))
        finally:
            waiting.release_results.set()
            if not connection.done():
                waiting.incoming.put_nowait(None)
                await asyncio.wait_for(connection, timeout=2)

    async def test_fault_safe_stops_even_while_cancellation_reply_is_backpressured(self):
        self.experiment.executor = ThreadPoolExecutor(max_workers=3)
        self.experiment.default_command_timeout = 0.05
        self.websocket.command("first", "one")
        await self.wait_started(self.first, "one")
        queued_id = self.websocket.command("first", "two")
        self.websocket.block_reply_ids.add(queued_id)
        await asyncio.wait_for(self.websocket.result_sending.wait(), timeout=1)
        await asyncio.wait_for(self.first.safe_stopped.wait(), timeout=0.5)
        self.websocket.release_results.set()
        queued_result = await self.websocket.result(queued_id)
        self.assertEqual(queued_result["payload"]["error"]["code"], "operation_cancelled")
        self.first.release["one"].set()

    async def test_handoff_waiter_disconnect_cleans_up_blocked_rejection(self):
        await asyncio.sleep(0)
        pending = QueuedJsonWebSocket()
        pending.hold_results = True
        connection = asyncio.create_task(self.experiment.handleConnection(pending, "/"))
        try:
            await asyncio.sleep(0)
            self.websocket.incoming.put_nowait(None)
            async def handoff_ready():
                while self.experiment.ownership.handoff_user is not pending:
                    await asyncio.sleep(0)
            await asyncio.wait_for(handoff_ready(), timeout=1)
            pending.command("first", "one")
            await asyncio.wait_for(pending.result_sending.wait(), timeout=1)
            pending.incoming.put_nowait(None)
            await asyncio.wait_for(asyncio.shield(connection), timeout=1)
            self.assertFalse(self.experiment._client_command_tasks.get(pending))
        finally:
            pending.release_results.set()
            if not connection.done():
                pending.incoming.put_nowait(None)
                await asyncio.wait_for(connection, timeout=2)
