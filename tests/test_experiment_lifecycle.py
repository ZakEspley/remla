import asyncio
import importlib
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from remla.runtime_state import LabConfigIdentity, RuntimeStateStore, StateWriteError


experiment_module = importlib.import_module("remla.labcontrol.Experiment")


class ExperimentLifecycleTests(unittest.TestCase):
    def test_constructor_uses_the_configured_operation_policy(self):
        experiment = experiment_module.Experiment("RemoteLabs")

        self.assertEqual(experiment.max_outstanding_operations, 16)
        self.assertEqual(experiment.default_command_timeout, 180)
        self.assertEqual(experiment.handoff_timeout, 60)


    def test_constructor_does_not_start_runtime_resources(self):
        with (
            mock.patch.object(experiment_module, "ThreadPoolExecutor") as executor,
            mock.patch.object(experiment_module.asyncio, "new_event_loop") as new_loop,
            mock.patch.object(experiment_module.asyncio, "set_event_loop") as set_loop,
            mock.patch.object(experiment_module.logging, "basicConfig") as configure_logging,
            mock.patch.object(experiment_module.socket, "socket") as create_socket,
            mock.patch.object(experiment_module.threading, "Thread") as create_thread,
            mock.patch.object(experiment_module.os.path, "exists", return_value=False),
        ):
            experiment = experiment_module.Experiment("RemoteLabs")

        self.assertIsNone(experiment.executor)
        self.assertIsNone(experiment.loop)
        self.assertIsNone(experiment.ipc_socket)
        self.assertIsNone(experiment.ipc_thread)
        executor.assert_not_called()
        new_loop.assert_not_called()
        set_loop.assert_not_called()
        configure_logging.assert_not_called()
        create_socket.assert_not_called()
        create_thread.assert_not_called()

    def test_runtime_initialization_is_explicit_and_idempotent(self):
        loop = mock.Mock(spec=asyncio.AbstractEventLoop)
        executor = mock.Mock()

        with (
            mock.patch.object(
                experiment_module.Experiment,
                "startIpcListener",
                return_value=(mock.Mock(), mock.Mock()),
            ),
            mock.patch.object(
                experiment_module, "ThreadPoolExecutor", return_value=executor
            ) as create_executor,
            mock.patch.object(
                experiment_module.asyncio, "new_event_loop", return_value=loop
            ) as create_loop,
            mock.patch.object(experiment_module.asyncio, "set_event_loop") as set_loop,
            mock.patch.object(experiment_module.logging, "basicConfig") as configure_logging,
            mock.patch.object(experiment_module.logging, "info"),
        ):
            experiment = experiment_module.Experiment("RemoteLabs")
            start_ipc = experiment.startIpcListener
            experiment.initialize_runtime()
            experiment.initialize_runtime()

        self.assertIs(experiment.executor, executor)
        self.assertIs(experiment.loop, loop)
        create_executor.assert_called_once_with(max_workers=4)
        create_loop.assert_called_once_with()
        set_loop.assert_not_called()
        configure_logging.assert_called_once()
        start_ipc.assert_called_once_with(loop=loop)

    def test_server_requires_explicit_runtime_initialization(self):
        experiment = experiment_module.Experiment("RemoteLabs")

        with self.assertRaisesRegex(RuntimeError, "runtime is not initialized"):
            experiment.startServer()

    def test_runtime_initialization_can_retry_after_ipc_failure(self):
        first_loop = mock.Mock(spec=asyncio.AbstractEventLoop)
        second_loop = mock.Mock(spec=asyncio.AbstractEventLoop)
        first_executor = mock.Mock()
        second_executor = mock.Mock()
        experiment = experiment_module.Experiment("RemoteLabs")

        with (
            mock.patch.object(
                experiment_module,
                "ThreadPoolExecutor",
                side_effect=[first_executor, second_executor],
            ) as create_executor,
            mock.patch.object(
                experiment_module.asyncio,
                "new_event_loop",
                side_effect=[first_loop, second_loop],
            ) as create_loop,
            mock.patch.object(experiment_module.asyncio, "set_event_loop"),
            mock.patch.object(experiment_module.logging, "basicConfig"),
            mock.patch.object(experiment_module.logging, "info"),
            mock.patch.object(
                experiment,
                "startIpcListener",
                side_effect=[OSError("IPC"), (mock.Mock(), mock.Mock())],
            ) as start_ipc,
        ):
            with self.assertRaisesRegex(OSError, "IPC"):
                experiment.initialize_runtime()

            self.assertIsNone(experiment.executor)
            self.assertIsNone(experiment.loop)

            experiment.initialize_runtime()

        self.assertIs(experiment.executor, second_executor)
        self.assertIs(experiment.loop, second_loop)
        create_executor.assert_has_calls([mock.call(max_workers=4)] * 2)
        create_loop.assert_has_calls([mock.call()] * 2)
        start_ipc.assert_has_calls(
            [mock.call(loop=first_loop), mock.call(loop=second_loop)]
        )
        first_executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        first_loop.close.assert_called_once_with()

    def test_runtime_initialization_recovers_from_executor_creation_failure(self):
        executor = mock.Mock()
        loop = mock.Mock(spec=asyncio.AbstractEventLoop)
        experiment = experiment_module.Experiment("RemoteLabs")

        with (
            mock.patch.object(
                experiment_module,
                "ThreadPoolExecutor",
                side_effect=[OSError("executor"), executor],
            ),
            mock.patch.object(
                experiment_module.asyncio, "new_event_loop", return_value=loop
            ),
            mock.patch.object(experiment_module.logging, "basicConfig"),
            mock.patch.object(experiment_module.logging, "info"),
            mock.patch.object(
                experiment,
                "startIpcListener",
                return_value=(mock.Mock(), mock.Mock()),
            ),
        ):
            with self.assertRaisesRegex(OSError, "executor"):
                experiment.initialize_runtime()

            self.assertEqual(experiment._runtime_state, "new")
            experiment.initialize_runtime()

        self.assertIs(experiment.executor, executor)
        self.assertIs(experiment.loop, loop)

    def test_failed_initialization_preserves_the_current_event_loop(self):
        previous_loop = asyncio.new_event_loop()
        runtime_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(previous_loop)
        experiment = experiment_module.Experiment("RemoteLabs")

        try:
            with (
                mock.patch.object(experiment_module, "ThreadPoolExecutor"),
                mock.patch.object(
                    experiment_module.asyncio,
                    "new_event_loop",
                    return_value=runtime_loop,
                ),
                mock.patch.object(experiment_module.logging, "basicConfig"),
                mock.patch.object(experiment_module.logging, "info"),
                mock.patch.object(
                    experiment, "startIpcListener", side_effect=OSError("IPC")
                ),
            ):
                with self.assertRaisesRegex(OSError, "IPC"):
                    experiment.initialize_runtime()

            self.assertIs(asyncio.get_event_loop(), previous_loop)
        finally:
            asyncio.set_event_loop(None)
            previous_loop.close()
            runtime_loop.close()

    def test_runtime_initialization_is_thread_safe(self):
        loop = mock.Mock(spec=asyncio.AbstractEventLoop)
        executor = mock.Mock()
        experiment = experiment_module.Experiment("RemoteLabs")
        entered_ipc_start = threading.Event()
        allow_ipc_start = threading.Event()
        second_finished = threading.Event()
        errors = []

        def start_ipc(*, loop):
            entered_ipc_start.set()
            allow_ipc_start.wait(timeout=1)
            return mock.Mock(), mock.Mock()

        def initialize():
            try:
                experiment.initialize_runtime()
            except Exception as error:
                errors.append(error)

        def initialize_second():
            initialize()
            second_finished.set()

        with (
            mock.patch.object(
                experiment_module, "ThreadPoolExecutor", return_value=executor
            ) as create_executor,
            mock.patch.object(
                experiment_module.asyncio, "new_event_loop", return_value=loop
            ) as create_loop,
            mock.patch.object(experiment_module.asyncio, "set_event_loop"),
            mock.patch.object(experiment_module.logging, "basicConfig"),
            mock.patch.object(experiment_module.logging, "info"),
            mock.patch.object(experiment, "startIpcListener", side_effect=start_ipc),
        ):
            first = threading.Thread(target=initialize)
            second = threading.Thread(target=initialize_second)
            first.start()
            self.assertTrue(entered_ipc_start.wait(timeout=1))
            second.start()
            self.assertFalse(second_finished.wait(timeout=0.1))
            allow_ipc_start.set()
            first.join(timeout=1)
            second.join(timeout=1)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        create_executor.assert_called_once_with(max_workers=4)
        create_loop.assert_called_once_with()

    def test_failed_ipc_start_removes_the_socket_file(self):
        experiment = experiment_module.Experiment("RemoteLabs")
        thread = mock.Mock()
        thread.start.side_effect = OSError("thread start")

        with tempfile.TemporaryDirectory() as directory:
            socket_path = os.path.join(directory, "remla.sock")
            with mock.patch.object(
                experiment_module.threading, "Thread", return_value=thread
            ):
                with self.assertRaisesRegex(OSError, "thread start"):
                    experiment.startIpcListener(
                        ipc_path=socket_path,
                        loop=mock.Mock(spec=asyncio.AbstractEventLoop),
                    )

            self.assertFalse(os.path.exists(socket_path))

    def test_ipc_start_does_not_replace_an_active_listener(self):
        experiment = experiment_module.Experiment("RemoteLabs")

        with tempfile.TemporaryDirectory() as directory:
            socket_path = os.path.join(directory, "remla.sock")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(socket_path)
            listener.listen(1)
            try:
                with mock.patch.object(experiment_module.threading, "Thread"):
                    with self.assertRaisesRegex(RuntimeError, "already running"):
                        experiment.startIpcListener(
                            ipc_path=socket_path,
                            loop=mock.Mock(spec=asyncio.AbstractEventLoop),
                        )

                self.assertTrue(os.path.exists(socket_path))
            finally:
                listener.close()
                os.unlink(socket_path)

    def test_mismatched_persisted_state_is_preserved_with_a_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            state_store = RuntimeStateStore(Path(directory) / "runtime-state.json")
            stored_identity = LabConfigIdentity.from_content("lab.yml", b"original")
            active_identity = LabConfigIdentity.from_content("lab.yml", b"changed")
            state_store.save(state_store.new_snapshot(stored_identity, "ready", {}))
            experiment = experiment_module.Experiment(
                "RemoteLabs",
                lab_config_identity=active_identity,
                state_store=state_store,
            )

            result = experiment.load_persisted_state()
            stored_snapshot = state_store.load(stored_identity).snapshot

        self.assertEqual(result.diagnostic, "lab_mismatch")
        self.assertFalse(experiment.state_writable)
        self.assertIn("To resolve", result.message)
        self.assertIsNotNone(stored_snapshot)

    def test_controller_states_are_persisted_for_the_active_lab(self):
        class Device:
            name = "camera"

            def getState(self):
                return {"enabled": True}

        with tempfile.TemporaryDirectory() as directory:
            state_store = RuntimeStateStore(Path(directory) / "runtime-state.json")
            identity = LabConfigIdentity.from_content("lab.yml", b"active")
            experiment = experiment_module.Experiment(
                "RemoteLabs",
                lab_config_identity=identity,
                state_store=state_store,
            )
            experiment.load_persisted_state()
            experiment.addDevice(Device())

            experiment.getControllerStates()

            snapshot = state_store.load(identity).snapshot

        self.assertEqual(snapshot["devices"]["camera"]["observed"], {"enabled": True})

    def test_state_write_failure_does_not_abort_controller_state_capture(self):
        class Device:
            name = "camera"

            def getState(self):
                return {"enabled": True}

        with tempfile.TemporaryDirectory() as directory:
            state_store = RuntimeStateStore(Path(directory) / "runtime-state.json")
            identity = LabConfigIdentity.from_content("lab.yml", b"active")
            experiment = experiment_module.Experiment(
                "RemoteLabs",
                lab_config_identity=identity,
                state_store=state_store,
            )
            experiment.load_persisted_state()
            experiment.addDevice(Device())

            with mock.patch.object(
                state_store, "save", side_effect=StateWriteError("disk")
            ):
                experiment.getControllerStates()

        self.assertEqual(experiment.state_diagnostic, "write_failed")
        self.assertFalse(experiment.state_writable)


class ExperimentCommandOperationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ungrouped_command_is_tracked_and_completed(self):
        class Device:
            name = "camera"

            def cmdHandler(self, method, params, device_name):
                return "MESSAGE", f"{device_name}:{method}:{params[0]}"

        experiment = experiment_module.Experiment("RemoteLabs")
        experiment._runtime_state = "ready"
        experiment.ownership.connect("owner")
        experiment.addDevice(Device())
        experiment.sendMessage = mock.AsyncMock()
        loop = mock.Mock()

        async def run_in_executor(executor, func, *args):
            return func(*args)

        loop.run_in_executor = mock.AsyncMock(side_effect=run_in_executor)
        with mock.patch.object(experiment_module.asyncio, "get_event_loop", return_value=loop):
            await experiment.runDeviceMethod("camera", "capture", ["now"], "owner")

        operations = list(experiment.operation_registry.operations.values())
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].owner_id, "owner")
        self.assertIsNone(operations[0].lock_group)
        self.assertEqual(operations[0].status, "completed")
        experiment.sendMessage.assert_awaited_once_with("owner", "camera:capture:now")

    async def test_command_timeout_returns_a_client_alert(self):
        experiment = experiment_module.Experiment("RemoteLabs")
        experiment._runtime_state = "ready"
        experiment.devices["camera"] = mock.Mock()
        experiment.runDeviceMethod = mock.AsyncMock(side_effect=asyncio.TimeoutError())
        experiment.sendAlert = mock.AsyncMock()

        await experiment.processCommand("camera/capture/now", "owner")

        experiment.sendAlert.assert_awaited_once_with(
            "owner", "Experiment/operationTimedOut/camera/capture"
        )
        self.assertEqual(experiment._runtime_state, "faulted")

    async def test_outstanding_operation_limit_returns_a_client_alert(self):
        experiment = experiment_module.Experiment("RemoteLabs")
        experiment.devices["camera"] = mock.Mock()
        experiment.runDeviceMethod = mock.AsyncMock(
            side_effect=experiment_module.OutstandingOperationLimit()
        )
        experiment.sendAlert = mock.AsyncMock()

        await experiment.processCommand("camera/capture/now", "owner")

        experiment.sendAlert.assert_awaited_once_with(
            "owner", "Experiment/operationRejected/outstandingOperationLimit"
        )

    async def test_faulted_experiment_rechecks_command_admission(self):
        experiment = experiment_module.Experiment("RemoteLabs")
        experiment._runtime_state = "faulted"
        experiment.ownership.connect("owner")
        experiment.devices["camera"] = mock.Mock()
        experiment.sendAlert = mock.AsyncMock()

        await experiment.processCommand("camera/capture/now", "owner")

        experiment.sendAlert.assert_awaited_once_with(
            "owner", "Experiment/operationRejected/notAcceptingCommands"
        )


class ExperimentHandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.experiment = experiment_module.Experiment("RemoteLabs")
        self.experiment._runtime_state = "ready"
        self.experiment.sendAlert = mock.AsyncMock()
        self.first_client = "first"
        self.next_client = "next"
        self.experiment.ownership.connect(self.first_client)
        self.experiment.ownership.connect(self.next_client)
        self.experiment.ownership.disconnect(self.first_client)

    async def test_continue_handoff_grants_control(self):
        await self.experiment.processControlCommand(
            "CONTROL/handoff/continue", self.next_client
        )

        self.assertEqual(self.experiment.activeClient, self.next_client)
        self.assertTrue(self.experiment.ownership.can_submit(self.next_client))

    async def test_reset_handoff_grants_control_after_successful_reset(self):
        loop = mock.Mock()
        loop.run_in_executor = mock.AsyncMock(return_value=None)
        with mock.patch.object(experiment_module.asyncio, "get_running_loop", return_value=loop):
            await self.experiment.processControlCommand(
                "CONTROL/handoff/reset", self.next_client
            )

        loop.run_in_executor.assert_awaited_once_with(
            self.experiment.executor, self.experiment.resetExperiment
        )
        self.assertEqual(self.experiment.activeClient, self.next_client)
        self.assertTrue(self.experiment.ownership.can_submit(self.next_client))

    async def test_non_handoff_user_cannot_select_a_handoff_action(self):
        waiting_client = "waiting"
        self.experiment.ownership.connect(waiting_client)

        await self.experiment.processControlCommand(
            "CONTROL/handoff/continue", waiting_client
        )

        self.assertIsNone(self.experiment.activeClient)
        self.assertEqual(self.experiment.ownership.handoff_user, self.next_client)
        self.experiment.sendAlert.assert_awaited_once_with(
            waiting_client,
            "Experiment/controlStatus/0,You do not have a pending control handoff.",
        )

    async def test_malformed_handoff_frame_is_rejected(self):
        await self.experiment.processControlCommand("CONTROL/handoff", self.next_client)

        self.assertEqual(self.experiment.ownership.handoff_user, self.next_client)
        self.experiment.sendAlert.assert_awaited_once_with(
            self.next_client,
            "Experiment/controlStatus/0,You do not have a pending control handoff.",
        )

    async def test_handoff_action_is_rejected_while_stopping(self):
        self.experiment._runtime_state = "stopping"

        await self.experiment.processControlCommand(
            "CONTROL/handoff/reset", self.next_client
        )

        self.assertEqual(self.experiment.ownership.handoff_state, "pending")
        self.experiment.sendAlert.assert_awaited_once_with(
            self.next_client,
            "Experiment/controlStatus/0,The experiment is not accepting control actions.",
        )

    async def test_reset_failure_faults_the_pending_handoff(self):
        loop = mock.Mock()
        loop.run_in_executor = mock.AsyncMock(side_effect=RuntimeError("reset failed"))
        with mock.patch.object(experiment_module.asyncio, "get_running_loop", return_value=loop):
            await self.experiment.processControlCommand(
                "CONTROL/handoff/reset", self.next_client
            )

        self.assertEqual(self.experiment.ownership.handoff_state, "faulted")
        self.assertIsNone(self.experiment.activeClient)
        self.experiment.sendAlert.assert_awaited_once_with(
            self.next_client, "Experiment/resetFailed/reset failed"
        )

    async def test_handoff_timeout_resets_before_granting_control(self):
        loop = mock.Mock()
        loop.run_in_executor = mock.AsyncMock(return_value=None)
        with (
            mock.patch.object(experiment_module.asyncio, "sleep", new=mock.AsyncMock()),
            mock.patch.object(experiment_module.asyncio, "get_running_loop", return_value=loop),
        ):
            self.experiment.schedule_handoff_timeout()
            await self.experiment._handoff_timeout_task

        loop.run_in_executor.assert_awaited_once_with(
            self.experiment.executor, self.experiment.resetExperiment
        )
        self.assertEqual(self.experiment.activeClient, self.next_client)
        self.assertTrue(self.experiment.ownership.can_submit(self.next_client))
        self.experiment.sendAlert.assert_awaited_once_with(
            self.next_client,
            "Experiment/controlStatus/1,Handoff timed out. Reset complete. You have control of the lab equipment.",
        )

    async def test_pending_handoff_user_cannot_run_normal_commands(self):
        class WebSocket:
            def __init__(self):
                self.commands = ["camera/capture/now"]

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.commands:
                    raise StopAsyncIteration
                return self.commands.pop(0)

        websocket = WebSocket()
        experiment = experiment_module.Experiment("RemoteLabs")
        experiment.sendAlert = mock.AsyncMock()
        experiment.processCommand = mock.AsyncMock()
        experiment.ownership.connect("active")
        experiment.ownership.connect(websocket)
        experiment.ownership.disconnect("active")

        await experiment.handleConnection(websocket, "/")
        await asyncio.sleep(0)

        experiment.processCommand.assert_not_awaited()
        self.assertIn(
            mock.call(
                websocket,
                "Experiment/controlStatus/0,You do not have control to send commands.",
            ),
            experiment.sendAlert.await_args_list,
        )


class ExperimentOwnerDrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_disconnect_waits_for_running_operation_before_handoff(self):
        experiment = experiment_module.Experiment("RemoteLabs")
        experiment.notify_handoff_user = mock.AsyncMock()
        experiment.ownership.connect("owner")
        experiment.ownership.connect("next")
        operation = experiment.operation_registry.submit(
            "owner", "camera", "switch", "camera", 30
        )
        operation_started = asyncio.Event()
        allow_completion = asyncio.Event()

        async def command():
            operation_started.set()
            await allow_completion.wait()
            return {"channel": 1}

        command_task = asyncio.create_task(
            experiment.command_scheduler.execute(operation, command)
        )
        await operation_started.wait()

        disconnect_task = asyncio.create_task(experiment.disconnect_client("owner"))
        await asyncio.sleep(0)

        self.assertEqual(experiment.ownership.active_owner, "owner")
        self.assertIsNone(experiment.ownership.handoff_user)

        allow_completion.set()
        await command_task
        await disconnect_task

        self.assertIsNone(experiment.ownership.active_owner)
        self.assertEqual(experiment.ownership.handoff_user, "next")
        experiment.notify_handoff_user.assert_awaited_once_with()

    async def test_owner_disconnect_cancels_queued_operations_before_handoff(self):
        experiment = experiment_module.Experiment("RemoteLabs")
        experiment.notify_handoff_user = mock.AsyncMock()
        experiment.ownership.connect("owner")
        experiment.ownership.connect("next")
        first = experiment.operation_registry.submit(
            "owner", "camera", "switch", "camera", 30
        )
        second = experiment.operation_registry.submit(
            "owner", "camera", "switch", "camera", 30
        )
        first_started = asyncio.Event()
        allow_first_completion = asyncio.Event()
        second_started = asyncio.Event()

        async def first_command():
            first_started.set()
            await allow_first_completion.wait()
            return {"channel": 1}

        async def second_command():
            second_started.set()
            return {"channel": 2}

        first_task = asyncio.create_task(
            experiment.command_scheduler.execute(first, first_command)
        )
        await first_started.wait()
        second_task = asyncio.create_task(
            experiment.command_scheduler.execute(second, second_command)
        )
        experiment._operation_tasks[second.operation_id] = second_task
        experiment._client_command_tasks["owner"] = {second_task}

        disconnect_task = asyncio.create_task(experiment.disconnect_client("owner"))
        await asyncio.sleep(0)

        self.assertEqual(second.status, "cancelled")
        self.assertFalse(second_started.is_set())

        allow_first_completion.set()
        await first_task
        await disconnect_task
        with self.assertRaises(asyncio.CancelledError):
            await second_task

        self.assertEqual(experiment.ownership.handoff_user, "next")

    async def test_handoff_reset_waits_for_running_operations(self):
        experiment = experiment_module.Experiment("RemoteLabs")
        experiment._runtime_state = "ready"
        experiment.sendAlert = mock.AsyncMock()
        experiment.ownership.connect("owner")
        experiment.ownership.connect("next")
        experiment.ownership.disconnect("owner")
        operation = experiment.operation_registry.submit(
            "owner", "camera", "switch", "camera", 30
        )
        queued_operation = experiment.operation_registry.submit(
            "owner", "camera", "switch", "camera", 30
        )
        operation_started = asyncio.Event()
        allow_completion = asyncio.Event()
        queued_operation_started = asyncio.Event()

        async def command():
            operation_started.set()
            await allow_completion.wait()
            return {"channel": 1}

        async def queued_command():
            queued_operation_started.set()
            return {"channel": 2}

        command_task = asyncio.create_task(
            experiment.command_scheduler.execute(operation, command)
        )
        await operation_started.wait()
        queued_task = asyncio.create_task(
            experiment.command_scheduler.execute(queued_operation, queued_command)
        )
        experiment._operation_tasks[queued_operation.operation_id] = queued_task
        loop = mock.Mock()
        loop.run_in_executor = mock.AsyncMock(return_value=None)

        with mock.patch.object(experiment_module.asyncio, "get_running_loop", return_value=loop):
            reset_task = asyncio.create_task(
                experiment.processControlCommand("CONTROL/handoff/reset", "next")
            )
            await asyncio.sleep(0)
            loop.run_in_executor.assert_not_awaited()
            self.assertEqual(queued_operation.status, "cancelled")
            self.assertFalse(queued_operation_started.is_set())

            allow_completion.set()
            await command_task
            await reset_task

        with self.assertRaises(asyncio.CancelledError):
            await queued_task

        loop.run_in_executor.assert_awaited_once_with(
            experiment.executor, experiment.resetExperiment
        )
        self.assertTrue(experiment.ownership.can_submit("next"))


class ExperimentShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_resets_devices_and_releases_runtime_resources(self):
        class Device:
            name = "camera"

            def __init__(self):
                self.reset_called = False
                self.safe_stop_called = False

            def reset(self):
                self.reset_called = True

            def safe_stop(self):
                self.safe_stop_called = True

        experiment = experiment_module.Experiment("RemoteLabs")
        device = Device()
        experiment.addDevice(device)
        experiment._runtime_state = "ready"
        experiment.executor = mock.Mock()
        ipc_socket = mock.Mock()
        ipc_thread = mock.Mock()
        experiment.ipc_socket = ipc_socket
        experiment.ipc_thread = ipc_thread
        loop = mock.Mock()

        async def run_in_executor(executor, function, *args):
            return function(*args)

        loop.run_in_executor = mock.AsyncMock(side_effect=run_in_executor)
        with tempfile.TemporaryDirectory() as directory:
            experiment.ipc_path = Path(directory) / "remla.sock"
            experiment.ipc_path.touch()
            with mock.patch.object(
                experiment_module.asyncio, "get_running_loop", return_value=loop
            ):
                await experiment.shutdown("foreground_signal")
                await experiment.shutdown("foreground_signal")

            self.assertFalse(experiment.ipc_path.exists())

        self.assertTrue(device.reset_called)
        self.assertTrue(device.safe_stop_called)
        self.assertEqual(experiment._runtime_state, "stopped")
        loop.run_in_executor.assert_awaited_once_with(
            experiment.executor, experiment.shutdownExperiment
        )
        ipc_socket.close.assert_called_once_with()
        ipc_thread.join.assert_called_once_with(timeout=1)
        experiment.executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)

    async def test_shutdown_releases_resources_when_reset_fails(self):
        experiment = experiment_module.Experiment("RemoteLabs")
        experiment._runtime_state = "ready"
        experiment.executor = mock.Mock()
        experiment.resetExperiment = mock.Mock(side_effect=RuntimeError("reset failed"))
        experiment.ipc_socket = mock.Mock()
        experiment.ipc_thread = mock.Mock()
        server = mock.Mock()
        server.wait_closed = mock.AsyncMock()
        experiment.server = server
        loop = mock.Mock()
        loop.is_running.return_value = True

        async def run_in_executor(executor, function, *args):
            return function(*args)

        loop.run_in_executor = mock.AsyncMock(side_effect=run_in_executor)
        experiment.loop = loop
        with mock.patch.object(
            experiment_module.asyncio, "get_running_loop", return_value=loop
        ):
            with self.assertRaisesRegex(RuntimeError, "reset failed"):
                await experiment.shutdown("foreground_signal")

        server.close.assert_called_once_with()
        server.wait_closed.assert_awaited_once_with()
        self.assertIsNone(experiment.ipc_socket)
        experiment.executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)
        loop.call_soon.assert_called_once_with(loop.stop)
        self.assertEqual(experiment._runtime_state, "stopped")


class ExperimentFaultTests(unittest.IsolatedAsyncioTestCase):
    async def test_fault_transition_blocks_admission_and_publishes_legacy_event(self):
        experiment = experiment_module.Experiment("RemoteLabs")
        experiment._runtime_state = "ready"
        experiment.ownership.connect("owner")
        experiment.sendCommandToAllClients = mock.AsyncMock()

        await experiment.enter_fault("Operation timed out: camera/capture")

        self.assertEqual(experiment._runtime_state, "faulted")
        self.assertEqual(experiment.last_fault, "Operation timed out: camera/capture")
        self.assertFalse(experiment.can_accept_commands("owner"))
        experiment.sendCommandToAllClients.assert_awaited_once_with(
            "fault/Operation timed out: camera/capture"
        )


if __name__ == "__main__":
    unittest.main()
