import asyncio
import importlib
import os
import socket
import tempfile
import threading
import unittest
from unittest import mock


experiment_module = importlib.import_module("remla.labcontrol.Experiment")


class ExperimentLifecycleTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
