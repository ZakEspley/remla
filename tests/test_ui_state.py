import asyncio
import importlib
import json
import unittest
import uuid
from unittest import mock


experiment_module = importlib.import_module("remla.labcontrol.Experiment")


class WebSocket:
    def __init__(self, json_protocol=True):
        self.subprotocol = experiment_module.JSON_SUBPROTOCOL if json_protocol else None
        self.frames = []

    async def send(self, frame):
        self.frames.append(frame)

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class UIStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.experiment = experiment_module.Experiment("RemoteLabs")
        self.experiment._runtime_state = "ready"
        self.owner = WebSocket()
        self.observer = WebSocket()
        self.legacy = WebSocket(json_protocol=False)
        self.experiment.clients.extend([self.owner, self.observer, self.legacy])
        self.experiment.ownership.connect(self.owner)
        self.experiment.ownership.connect(self.observer)
        self.experiment.runDeviceMethod = mock.AsyncMock()

    def events(self, websocket, name):
        return [
            frame["payload"]["data"]
            for frame in map(json.loads, websocket.frames)
            if frame["type"] == "event" and frame["payload"]["name"] == name
        ]

    async def write(self, parameters, websocket=None, experiment=None):
        websocket = self.owner if websocket is None else websocket
        experiment = self.experiment if experiment is None else experiment
        message_id = str(uuid.uuid4())
        await experiment.process_json_frame(
            json.dumps({
                "meta": {"messageId": message_id, "version": "1.0.0"},
                "type": "command",
                "payload": {
                    "deviceName": "Experiment",
                    "commandName": "set_ui_state",
                    "parameters": parameters,
                },
            }),
            websocket,
        )
        results = [
            frame for frame in map(json.loads, websocket.frames)
            if frame["type"] == "result" and frame["meta"]["replyId"] == message_id
        ]
        self.assertEqual(len(results), 1, "Every UI write needs one correlated result")
        self.experiment.runDeviceMethod.assert_not_awaited()
        return results[0]["payload"]

    async def snapshot_on_join(self, experiment=None):
        experiment = self.experiment if experiment is None else experiment
        client = WebSocket()
        await experiment.handleConnection(client, "/")
        snapshots = self.events(client, "ui.state.snapshot")
        self.assertEqual(len(snapshots), 1, "Joining JSON clients need a UI snapshot")
        return snapshots[0]

    async def cancel_task(self, task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def start_blocked_ui_write(self):
        send_started = asyncio.Event()
        release_send = asyncio.Event()
        original_send = self.observer.send

        async def send(frame):
            message = json.loads(frame)
            if (message["type"] == "event"
                    and message["payload"]["name"] == "ui.state.changed"):
                send_started.set()
                await release_send.wait()
            await original_send(frame)

        self.observer.send = send
        write_task = asyncio.create_task(self.write({
            "namespace": "photoelectric", "values": {"potInterval": "36"},
        }))
        self.addAsyncCleanup(self.cancel_task, write_task)
        await asyncio.wait_for(send_started.wait(), timeout=1)
        self.assertFalse(write_task.done())
        return write_task, release_send

    async def test_fault_safety_work_is_not_blocked_by_ui_state_send(self):
        write_task, release_send = await self.start_blocked_ui_write()
        self.experiment.cancel_queued_operations = mock.AsyncMock()
        self.experiment.safeStopExperiment = mock.Mock()
        self.experiment.executor = mock.Mock()
        safe_stopped = asyncio.Event()

        async def run_in_executor(executor, function, *args):
            result = function(*args)
            safe_stopped.set()
            return result

        loop = asyncio.get_running_loop()
        with mock.patch.object(loop, "run_in_executor", side_effect=run_in_executor):
            fault_task = asyncio.create_task(self.experiment.enter_fault("test fault"))
            self.addAsyncCleanup(self.cancel_task, fault_task)
            try:
                await asyncio.wait_for(safe_stopped.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

            self.assertFalse(release_send.is_set())
            self.assertFalse(write_task.done())
            self.assertEqual(self.experiment._runtime_state, "faulted")
            with self.subTest(milestone="cancel queued operations"):
                self.experiment.cancel_queued_operations.assert_awaited_once()
            with self.subTest(milestone="safe stop hardware"):
                self.experiment.safeStopExperiment.assert_called_once_with()

    async def test_owner_disconnect_reaches_handoff_despite_blocked_ui_state_send(self):
        write_task, release_send = await self.start_blocked_ui_write()
        self.experiment.schedule_handoff_timeout = mock.Mock()
        self.experiment.clients.remove(self.owner)
        disconnect_task = asyncio.create_task(self.experiment.disconnect_client(self.owner))
        self.addAsyncCleanup(self.cancel_task, disconnect_task)

        await asyncio.wait({disconnect_task}, timeout=1)

        self.assertFalse(release_send.is_set())
        self.assertFalse(write_task.done())
        self.assertIsNone(self.experiment.ownership.active_owner)
        self.assertIs(self.experiment.ownership.handoff_user, self.observer)
        self.assertEqual(self.experiment._runtime_state, "ready")
        self.assertEqual(self.events(self.observer, "ownership.handoff"), [{
            "choices": ["continue", "reset"],
            "timeoutSeconds": self.experiment.handoff_timeout,
        }])
        self.experiment.schedule_handoff_timeout.assert_called_once_with()

    async def test_owner_disconnect_reaches_reset_despite_blocked_ui_state_send(self):
        self.experiment.ownership.disconnect(self.observer)
        write_task, release_send = await self.start_blocked_ui_write()
        self.experiment.resetExperiment = mock.Mock()
        self.experiment.clients.remove(self.owner)
        disconnect_task = asyncio.create_task(self.experiment.disconnect_client(self.owner))
        self.addAsyncCleanup(self.cancel_task, disconnect_task)

        await asyncio.wait({disconnect_task}, timeout=1)

        self.assertFalse(release_send.is_set())
        self.assertFalse(write_task.done())
        self.assertIsNone(self.experiment.ownership.active_owner)
        self.assertIsNone(self.experiment.ownership.handoff_user)
        self.experiment.resetExperiment.assert_called_once()
        self.assertEqual(self.experiment._runtime_state, "ready")

    async def test_owner_write_broadcasts_full_state_and_late_join_gets_snapshot(self):
        self.assertEqual(await self.snapshot_on_join(), {"revision": 0, "namespaces": {}})
        values = {"selectedTool": "potentiometer", "potInterval": "36"}
        result = await self.write({"namespace": "photoelectric", "values": values})
        self.assertEqual((result["status"], result["ok"]), (200, True))
        expected = {"revision": 1, "namespaces": {"photoelectric": values}}
        self.assertEqual(self.events(self.owner, "ui.state.changed"), [expected])
        self.assertEqual(self.events(self.observer, "ui.state.changed"), [expected])
        self.assertEqual(await self.snapshot_on_join(), expected)
        self.assertEqual(self.legacy.frames, [])

        result = await self.write({"namespace": "display", "values": {"enabled": True}})
        self.assertTrue(result["ok"])
        expected = {
            "revision": 2,
            "namespaces": {"photoelectric": values, "display": {"enabled": True}},
        }
        self.assertEqual(self.events(self.observer, "ui.state.changed")[-1], expected)
        self.assertEqual(await self.snapshot_on_join(), expected)

    async def test_queued_nonowner_and_unready_owner_cannot_write(self):
        for sender, lifecycle in [
            (self.observer, "ready"), (WebSocket(), "ready"),
            (self.owner, "draining"), (self.owner, "faulted"),
        ]:
            with self.subTest(lifecycle=lifecycle, sender=sender):
                self.experiment._runtime_state = lifecycle
                result = await self.write({"namespace": "photoelectric", "values": {}}, sender)
                self.assertEqual((result["status"], result["ok"]), (403, False))
                self.assertEqual(result["error"]["code"], "not_owner")
        self.experiment._runtime_state = "ready"
        self.assertEqual(await self.snapshot_on_join(), {"revision": 0, "namespaces": {}})
        self.assertEqual(self.events(self.observer, "ui.state.changed"), [])

    async def test_invalid_payloads_are_correlated_and_leave_state_unchanged(self):
        invalid = [
            {}, {"namespace": "photoelectric"}, {"values": {}},
            {"namespace": None, "values": {}},
            {"namespace": [], "values": {}},
            *[{"namespace": namespace, "values": {}} for namespace in
              ["", "n" * 33, "has space", "has.dot", "slash/name", "é"]],
            *[{"namespace": "photoelectric", "values": values} for values in
               [None, [], "bad", 1, {"nested": {}}, {"nested": []},
                {"value": "\ud800"},
               {"value": "x" * 81}, {"": 1}, {"k" * 49: 1},
               {"bad key": 1}, {"slash/key": 1}, {"é": 1},
               {f"key{i}": i for i in range(17)},
               {f"key{i}": "é" * 80 for i in range(16)}]],
        ]
        for parameters in invalid:
            with self.subTest(parameters=parameters):
                result = await self.write(parameters)
                self.assertEqual((result["status"], result["ok"]), (400, False))
                self.assertEqual(result["error"]["code"], "invalid_parameters")
        self.assertEqual(self.events(self.observer, "ui.state.changed"), [])
        self.assertEqual(await self.snapshot_on_join(), {"revision": 0, "namespaces": {}})

    async def test_scalar_values_and_identifier_boundaries_are_accepted(self):
        values = {
            "bool": False, "integer": 36, "float": 1.25, "null": None,
            "string": "x" * 80, "a.b-c_d": "", "k" * 48: True,
        }
        values.update({f"key{i}": i for i in range(16 - len(values))})
        namespace = "a-_" + "n" * 29
        result = await self.write({"namespace": namespace, "values": values})
        self.assertEqual((result["status"], result["ok"]), (200, True))
        self.assertEqual(await self.snapshot_on_join(), {
            "revision": 1, "namespaces": {namespace: values},
        })

    async def test_namespace_limit_is_atomic_and_existing_namespaces_remain_writable(self):
        namespaces = {f"n{i}": {"value": i} for i in range(8)}
        for namespace, values in namespaces.items():
            result = await self.write({"namespace": namespace, "values": values})
            self.assertEqual((result["status"], result["ok"]), (200, True))
        result = await self.write({"namespace": "ninth", "values": {"value": 9}})
        self.assertEqual((result["status"], result["ok"]), (400, False))
        self.assertEqual(result["error"]["code"], "invalid_parameters")
        self.assertEqual(await self.snapshot_on_join(), {"revision": 8, "namespaces": namespaces})
        result = await self.write({"namespace": "n0", "values": {"value": 99}})
        self.assertTrue(result["ok"])
        namespaces["n0"] = {"value": 99}
        self.assertEqual(await self.snapshot_on_join(), {"revision": 9, "namespaces": namespaces})

    async def test_owner_disconnect_clears_state_and_broadcasts_to_json_observers(self):
        result = await self.write({"namespace": "photoelectric", "values": {"potInterval": "36"}})
        self.assertTrue(result["ok"])
        self.experiment.schedule_handoff_timeout = mock.Mock()
        self.experiment.clients.remove(self.owner)
        await self.experiment.disconnect_client(self.owner)
        expected = {"revision": 2, "namespaces": {}}
        for _ in range(20):
            if expected in self.events(self.observer, "ui.state.changed"):
                break
            await asyncio.sleep(0.001)
        self.assertEqual(self.events(self.observer, "ui.state.changed")[-1], expected)
        self.assertEqual(await self.snapshot_on_join(), expected)
        self.assertEqual(self.legacy.frames, [])
        self.experiment.runDeviceMethod.assert_not_awaited()

    async def test_state_is_isolated_between_experiments(self):
        result = await self.write({"namespace": "photoelectric", "values": {"potInterval": "36"}})
        self.assertTrue(result["ok"])
        other = experiment_module.Experiment("OtherLab")
        other._runtime_state = "ready"
        other.ownership.connect(WebSocket())
        self.assertEqual(await self.snapshot_on_join(other), {"revision": 0, "namespaces": {}})
