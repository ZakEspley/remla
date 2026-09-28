import asyncio
import grp
import json
import logging
import os
import socket
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

import websockets

from remla.command_scheduler import CommandScheduler
from remla.runtime_operations import (
    OperationRegistry,
    OperationTransitionError,
    OutstandingOperationLimit,
    OwnershipManager,
)
from remla.settings import *
from remla.runtime_state import RuntimeStateStore, StateWriteError


class NoDeviceError(Exception):
    def __init__(self, device_name):
        self.device_name = device_name

    def __str__(self):
        return "NoDeviceError: This experiment doesn't have a device, '{0}'".format(
            self.device_name
        )


class CommandAdmissionError(Exception):
    pass


JSON_SUBPROTOCOL = "remla-json-v1"


def runMethod(device, method, params):
    if hasattr(device, "cmdHandler"):
        func = getattr(device, "cmdHandler")
        result = func(method, params, device.name)
        return result
    else:
        logging.error(f"Device {device} does not have a cmdHandler method")
        raise


def getMediaMTXPath(path):
    url = f"http://127.0.0.1:9997/v3/paths/get/{quote(path, safe='')}"
    try:
        with urlopen(url, timeout=0.25) as response:
            return json.load(response)
    except (OSError, URLError, ValueError):
        return {}


def waitForMediaMTXOnline(path, previous_source_id, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        path_state = getMediaMTXPath(path)
        source = path_state.get("source") or {}
        source_id = source.get("id")
        if path_state.get("online", False) and source_id and source_id != previous_source_id:
            return True
        time.sleep(0.02)
    return False


class Experiment(object):
    def __init__(
        self,
        name,
        host="localhost",
        port=8675,
        admin=False,
        lab_config_identity=None,
        state_store=None,
        max_outstanding_operations=16,
        default_command_timeout=180,
        handoff_timeout=60,
    ):
        self.name = name
        self.host = host
        self.port = port
        self.devices = {}

        self.lockGroups = {}
        self.lockMapping = {}
        self.max_outstanding_operations = max_outstanding_operations
        self.default_command_timeout = default_command_timeout
        self.handoff_timeout = handoff_timeout
        self.ownership = OwnershipManager()
        self.operation_registry = OperationRegistry(
            max_outstanding_per_owner=max_outstanding_operations,
            clock=time.monotonic,
        )
        self.command_scheduler = CommandScheduler(self.operation_registry, time.monotonic)

        self.allStates = {}
        self.lab_config_identity = lab_config_identity
        self.state_store = state_store or RuntimeStateStore(runtimeStatePath)
        self.persisted_state = None
        self.state_diagnostic = None
        self.state_writable = lab_config_identity is not None
        self.clients = deque()
        self.activeClient = None
        self._handoff_timeout_task = None
        self._client_command_tasks = {}
        self._operation_tasks = {}

        self.initializedStates = False
        self.admin = admin
        self.executor = None
        self.loop = None
        self.ipc_socket = None
        self.ipc_thread = None
        self.ipc_path = None
        self.server = None
        self._runtime_initialization_lock = threading.Lock()
        self._shutdown_lock = asyncio.Lock()
        self._shutdown_future = None
        self._runtime_state = "new"
        self.last_fault = None
        self.logPath = logsDirectory / f"{self.name}.log"

    def initialize_runtime(self):
        with self._runtime_initialization_lock:
            if self._runtime_state == "ready":
                return

            self._runtime_state = "initializing"
            executor = None
            loop = None
            try:
                executor = ThreadPoolExecutor(max_workers=4)
                loop = asyncio.new_event_loop()
                logging.basicConfig(
                    filename=self.logPath,
                    level=logging.INFO,
                    format="%(levelname)s - %(asctime)s - %(filename)s - %(funcName)s \r\n %(message)s \r\n",
                )
                logging.info("""
                ##############################################################
                ####                Starting New Log                      ####
                ##############################################################
                """)
                ipc_socket, ipc_thread = self.startIpcListener(loop=loop)
                self.executor = executor
                self.loop = loop
                self.ipc_socket = ipc_socket
                self.ipc_thread = ipc_thread
                self._runtime_state = "ready"
            except Exception:
                self.executor = None
                self.loop = None
                self.ipc_socket = None
                self.ipc_thread = None
                self._runtime_state = "new"
                if executor is not None:
                    executor.shutdown(wait=False, cancel_futures=True)
                if loop is not None:
                    loop.close()
                raise

    def logException(self, task):
        if task.cancelled():
            return
        error = task.exception()
        if error:
            logging.error("Unknown Exception: %s", error)

    def addDevice(self, device):
        device.experiment = self
        logging.info("Adding Device - " + device.name)
        self.devices[device.name] = device

    def addLockGroup(self, name: str, devices):
        if name in self.lockGroups:
            raise ValueError(f"Lock group '{name}' is defined more than once")
        for device in devices:
            existing_group = self.lockMapping.get(device.name)
            if existing_group is not None:
                raise ValueError(
                    f"Device '{device.name}' already belongs to lock group "
                    f"'{existing_group}'"
                )
        lock = asyncio.Lock()
        self.lockGroups[name] = lock
        self.command_scheduler.add_lock_group(name)
        for device in devices:
            self.lockMapping[device.name] = name

    def validate_lock_groups(self):
        missing_devices = sorted(set(self.devices) - set(self.lockMapping))
        if missing_devices:
            raise ValueError(
                "Devices must belong to exactly one lock group: "
                + ", ".join(missing_devices)
            )

    def recallState(self):
        return self.load_persisted_state()

    def load_persisted_state(self):
        if self.lab_config_identity is None:
            return None

        result = self.state_store.load(self.lab_config_identity)
        self.persisted_state = result.snapshot
        self.state_diagnostic = result.diagnostic
        self.state_writable = result.diagnostic in (None, "missing")
        self.initializedStates = True

        if result.message is not None:
            logging.warning(result.message)
        elif result.diagnostic not in (None, "missing"):
            logging.warning("Unable to load persisted runtime state: %s", result.diagnostic)
        return result

    def getControllerStates(self):
        logging.info("Getting Controller States")
        for name, device in self.devices.items():
            self.allStates[name] = device.getState()
        if self.lab_config_identity is not None and self.state_writable:
            device_states = {
                name: {"observed": state, "desired_safe": None}
                for name, state in self.allStates.items()
            }
            snapshot = self.state_store.new_snapshot(
                self.lab_config_identity,
                "ready",
                device_states,
            )
            try:
                self.state_store.save(snapshot)
            except StateWriteError as error:
                self.state_diagnostic = "write_failed"
                self.state_writable = False
                logging.warning("Unable to persist runtime state: %s", error)
        self.initializedStates = True

    async def handleConnection(self, websocket, path):
        request_headers = getattr(websocket, "request_headers", {})
        requested_subprotocol = request_headers.get("Sec-WebSocket-Protocol")
        if requested_subprotocol and websocket.subprotocol is None:
            await websocket.close(code=1002, reason="Unsupported WebSocket subprotocol")
            return
        print("Connection!:", websocket, path)
        self.clients.append(websocket)  # Track all clients by their WebSocket
        self.ownership.connect(websocket)
        try:
            if self.can_accept_commands(websocket):
                self.activeClient = websocket
                await self.sendAlert(
                    websocket, "Experiment/controlStatus/1,You have control of the lab equipment."
                )
            elif self.ownership.handoff_user == websocket:
                await self.sendAlert(
                    websocket,
                    "Experiment/controlStatus/0,Choose CONTROL/handoff/continue or CONTROL/handoff/reset.",
                )
            else:
                await self.sendAlert(
                    websocket,
                    "Experiment/controlStatus/0,You are connected but do not have control of the lab equipment.",
                )
            async for command in websocket:
                if self.uses_json_protocol(websocket):
                    await self.process_json_frame(command, websocket)
                    continue
                if command.startswith("CONTROL/handoff/"):
                    await self.processControlCommand(command, websocket)
                elif self.can_accept_commands(websocket):
                    task = asyncio.create_task(self.processCommand(command, websocket))
                    self.track_client_command_task(websocket, task)
                else:
                    asyncio.create_task(
                        self.sendAlert(
                            websocket, "Experiment/controlStatus/0,You do not have control to send commands."
                        )
                    )
        finally:
            self.clients.remove(websocket)  # Remove client that closed connection
            await self.disconnect_client(websocket)

    async def process_json_frame(self, frame, websocket):
        try:
            message = json.loads(frame)
            message_id = message["meta"]["messageId"]
            if message["type"] != "command":
                raise ValueError("Only command frames are accepted from clients")
            payload = message["payload"]
            device_name = payload["deviceName"]
            command_name = payload["commandName"]
            parameters = payload.get("parameters", {})
            if not isinstance(parameters, dict):
                raise ValueError("parameters must be an object")
        except (TypeError, KeyError, ValueError, json.JSONDecodeError) as error:
            await self.send_json_result(websocket, None, 400, False, "invalid_parameters", str(error))
            return
        try:
            uuid.UUID(message_id)
        except (TypeError, ValueError, AttributeError):
            await self.send_json_result(websocket, None, 400, False, "invalid_parameters", "messageId must be a UUID")
            return
        if not message.get("meta", {}).get("version", "").startswith("1."):
            await self.send_json_result(websocket, message_id, 400, False, "invalid_parameters", "Unsupported protocol version")
            return

        if device_name == "Experiment" and command_name == "handoff":
            choice = parameters.get("choice")
            if choice not in {"continue", "reset"}:
                await self.send_json_result(websocket, message_id, 400, False, "invalid_parameters", "choice must be continue or reset")
                return
            accepted = await self.processControlCommand(f"CONTROL/handoff/{choice}", websocket)
            if accepted:
                await self.send_json_result(websocket, message_id, 200, True, message="Handoff choice accepted")
            else:
                await self.send_json_result(websocket, message_id, 403, False, "not_owner", "Handoff choice was not accepted")
            return

        if not self.can_accept_commands(websocket):
            await self.send_json_result(websocket, message_id, 403, False, "not_owner", "You do not have control of the lab.")
            return
        if device_name not in self.devices:
            await self.send_json_result(websocket, message_id, 404, False, "unknown_command", "Unknown device")
            return

        arguments = parameters.get("arguments")
        if arguments is None:
            arguments = list(parameters.values())
        if not isinstance(arguments, list):
            await self.send_json_result(websocket, message_id, 400, False, "invalid_parameters", "arguments must be a list")
            return
        try:
            await self.runDeviceMethod(device_name, command_name, arguments, websocket)
        except (AttributeError, ValueError) as error:
            await self.send_json_result(websocket, message_id, 400, False, "invalid_parameters", str(error))
            return
        except asyncio.TimeoutError:
            await self.enter_fault(f"Operation timed out: {device_name}/{command_name}")
            await self.send_json_result(websocket, message_id, 500, False, "device_faulted", "Operation timed out")
            return
        except Exception as error:
            if error.__class__.__name__ in {"ArgumentError", "ArgumentNumberError"}:
                await self.send_json_result(websocket, message_id, 400, False, "invalid_parameters", str(error))
                return
            logging.exception("JSON command failed: %s/%s", device_name, command_name)
            await self.send_json_result(websocket, message_id, 500, False, "internal_error", "Command failed")
            return
        await self.send_json_result(websocket, message_id, 200, True, message="Command completed")

    def track_client_command_task(self, websocket, task):
        tasks = self._client_command_tasks.setdefault(websocket, set())
        tasks.add(task)

        def complete_task(completed_task):
            tasks.discard(completed_task)
            if not tasks:
                self._client_command_tasks.pop(websocket, None)
            self.logException(completed_task)

        task.add_done_callback(complete_task)

    async def disconnect_client(self, websocket):
        was_active_owner = websocket == self.ownership.active_owner
        was_handoff_user = websocket == self.ownership.handoff_user
        if was_active_owner:
            self.activeClient = None
            await self.drain_owner_operations(websocket)

        previous_handoff_user = self.ownership.handoff_user
        self.ownership.disconnect(websocket)
        self.activeClient = self.ownership.active_owner
        if (
            (was_active_owner or was_handoff_user)
            and self.ownership.active_owner is None
            and self.ownership.handoff_user is None
        ):
            await self.reset_after_owner_disconnect()
        if self.ownership.handoff_user != previous_handoff_user:
            await self.notify_handoff_user()

    async def reset_after_owner_disconnect(self):
        self._runtime_state = "resetting"
        try:
            await self.cancel_queued_operations()
            await self.command_scheduler.wait_for_idle()
            if self.executor is None:
                self.resetExperiment()
            else:
                loop = asyncio.get_running_loop()
                async with self.command_scheduler.reset_barrier():
                    await loop.run_in_executor(
                        self.executor, self.resetExperiment, "owner_disconnect_empty"
                    )
        except Exception as error:
            await self.enter_fault(f"Owner disconnect reset failed: {error}")
            return False
        self._runtime_state = "ready"
        return True

    async def drain_owner_operations(self, owner_id):
        cancelled_operation_ids = self.operation_registry.cancel_waiting_for_owner(
            owner_id, timestamp=time.monotonic()
        )
        await self.cancel_operation_tasks(cancelled_operation_ids)
        operation_ids_by_task = {
            task: operation_id for operation_id, task in self._operation_tasks.items()
        }
        tasks_to_cancel = []
        for task in self._client_command_tasks.get(owner_id, set()):
            operation_id = operation_ids_by_task.get(task)
            if operation_id is None:
                task.cancel()
                tasks_to_cancel.append(task)

        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        await self.command_scheduler.wait_for_owner(owner_id)

    async def cancel_queued_operations(self):
        cancelled_operation_ids = self.operation_registry.cancel_all_waiting(
            timestamp=time.monotonic()
        )
        await self.cancel_operation_tasks(cancelled_operation_ids)

    async def cancel_operation_tasks(self, operation_ids):
        tasks_to_cancel = [
            task
            for operation_id in operation_ids
            if (task := self._operation_tasks.get(operation_id)) is not None
            and task is not asyncio.current_task()
        ]
        for task in tasks_to_cancel:
            task.cancel()
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    async def processControlCommand(self, command, websocket):
        if self._runtime_state != "ready":
            await self.sendAlert(
                websocket, "Experiment/controlStatus/0,The experiment is not accepting control actions."
            )
            return False
        try:
            _, _, choice = command.split("/", 2)
            self.ownership.choose_handoff(websocket, choice)
        except (OperationTransitionError, ValueError):
            await self.sendAlert(
                websocket,
                "Experiment/controlStatus/0,You do not have a pending control handoff.",
            )
            return False
        self.cancel_handoff_timeout()
        if choice == "continue":
            self.activeClient = websocket
            await self.sendAlert(websocket, "Experiment/controlStatus/1,You have control of the lab equipment.")
            return True

        return await self.complete_handoff_reset(
            websocket,
            "Experiment/controlStatus/1,Reset complete. You have control of the lab equipment.",
            "handoff_choice",
        )

    def schedule_handoff_timeout(self):
        self.cancel_handoff_timeout()
        handoff_user = self.ownership.handoff_user
        if handoff_user is None or self.ownership.handoff_state != "pending":
            return
        self._handoff_timeout_task = asyncio.create_task(
            self.expire_handoff_after_timeout(handoff_user)
        )

    def cancel_handoff_timeout(self):
        timeout_task = self._handoff_timeout_task
        if timeout_task is not None and timeout_task is not asyncio.current_task():
            timeout_task.cancel()
        self._handoff_timeout_task = None

    async def notify_handoff_user(self):
        handoff_user = self.ownership.handoff_user
        if handoff_user is None:
            self.cancel_handoff_timeout()
            return
        await self.sendAlert(
            handoff_user,
            "Experiment/controlStatus/0,Choose CONTROL/handoff/continue or CONTROL/handoff/reset.",
        )
        self.schedule_handoff_timeout()

    async def expire_handoff_after_timeout(self, handoff_user):
        try:
            await asyncio.sleep(self.handoff_timeout)
        except asyncio.CancelledError:
            return

        if (
            self.ownership.handoff_user != handoff_user
            or self.ownership.handoff_state != "pending"
        ):
            return
        self.ownership.choose_handoff(handoff_user, "reset")
        await self.complete_handoff_reset(
            handoff_user,
            "Experiment/controlStatus/1,Handoff timed out. Reset complete. You have control of the lab equipment.",
            "handoff_timeout",
        )

    async def complete_handoff_reset(self, websocket, success_message, reset_reason):
        self._runtime_state = "resetting"
        try:
            await self.cancel_queued_operations()
            await self.command_scheduler.wait_for_idle()
            loop = asyncio.get_running_loop()
            async with self.command_scheduler.reset_barrier():
                await loop.run_in_executor(self.executor, self.resetExperiment, reset_reason)
        except Exception as error:
            self.ownership.complete_reset(success=False)
            self.activeClient = self.ownership.active_owner
            await self.enter_fault(f"Reset failed: {error}")
            await self.sendAlert(websocket, f"Experiment/resetFailed/{error}")
            return False

        self.ownership.complete_reset(success=True)
        self._runtime_state = "ready"
        self.activeClient = self.ownership.active_owner
        if self.activeClient == websocket:
            await self.sendAlert(websocket, success_message)
        elif self.ownership.handoff_user is not None:
            await self.notify_handoff_user()
        return True

    async def processCommand(self, command, websocket):
        print(f"Processing Command {command} from {websocket}")
        logging.info("Processing Command - " + command)
        deviceName, cmd, params = command.strip().split("/")
        params = params.split(",")
        if deviceName not in self.devices:
            print("Raising no device error")
            raise NoDeviceError(deviceName)

        try:
            await self.runDeviceMethod(deviceName, cmd, params, websocket)
        except CommandAdmissionError:
            await self.sendAlert(
                websocket, "Experiment/operationRejected/notAcceptingCommands"
            )
        except OutstandingOperationLimit:
            await self.sendAlert(
                websocket, "Experiment/operationRejected/outstandingOperationLimit"
            )
        except asyncio.TimeoutError:
            await self.enter_fault(f"Operation timed out: {deviceName}/{cmd}")
            await self.sendAlert(
                websocket, f"Experiment/operationTimedOut/{deviceName}/{cmd}"
            )

    def can_accept_commands(self, websocket):
        return self._runtime_state == "ready" and self.ownership.can_submit(websocket)

    async def enter_fault(self, message):
        self._runtime_state = "faulted"
        self.last_fault = message
        await self.cancel_queued_operations()
        if self.executor is not None:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(self.executor, self.safeStopExperiment)
            except Exception as error:
                logging.error("Safe stop failed while entering fault: %s", error)
        await self.sendCommandToAllClients(f"fault/{message}")

    async def recover_from_fault(self, action):
        if self._runtime_state != "faulted":
            return {"ok": False, "error": "not_faulted"}
        if self.command_scheduler.has_running_commands():
            return {"ok": False, "error": "operations_running"}
        if action == "resume":
            self._runtime_state = "ready"
            return {"ok": True, "state": "ready"}
        if action == "reset":
            self._runtime_state = "resetting"
            try:
                await self.cancel_queued_operations()
                loop = asyncio.get_running_loop()
                async with self.command_scheduler.reset_barrier():
                    if self.executor is not None:
                        await loop.run_in_executor(self.executor, self.resetExperiment)
            except Exception as error:
                await self.enter_fault(f"Recovery reset failed: {error}")
                return {"ok": False, "error": "reset_failed"}
            self._runtime_state = "ready"
            return {"ok": True, "state": "ready"}
        if action == "shutdown":
            await self.shutdown("fault")
            return {"ok": True, "state": "stopped"}
        return {"ok": False, "error": "invalid_action"}

    async def runDeviceMethod(self, deviceName, method, params, websocket):
        if not self.can_accept_commands(websocket):
            raise CommandAdmissionError("experiment is not accepting commands")
        device = self.devices.get(deviceName)
        if device is None:
            raise NoDeviceError(deviceName)

        lock_group = self.lockMapping.get(deviceName)
        if lock_group is None:
            raise RuntimeError(f"Device '{deviceName}' has no lock group")
        operation = self.operation_registry.submit(
            websocket,
            deviceName,
            method,
            lock_group,
            self.default_command_timeout,
        )
        task = asyncio.current_task()
        if task is not None:
            self._operation_tasks[operation.operation_id] = task
        try:
            response = await self.command_scheduler.execute(
                operation,
                lambda: self._execute_device_method(device, method, params),
            )
        finally:
            if self._operation_tasks.get(operation.operation_id) is task:
                self._operation_tasks.pop(operation.operation_id, None)

        response_type = "MESSAGE"
        result = response
        if isinstance(response, (list, tuple)):
            if len(response) > 1:
                response_type = response[0]
                result = response[1]
            elif len(response) == 1:
                result = response[0]
            else:
                result = None

        if result is not None:
            logging.info(f"Device {deviceName} ran {method} with result: {result}")
            if response_type == "ALERT":
                await self.sendAlert(websocket, f"{result}")
            else:
                await self.sendMessage(websocket, f"{result}")
        else:
            await self.sendMessage(websocket, f"{deviceName} ran {method}")

    async def _execute_device_method(self, device, method, params):
        if device.__class__.__name__ == "ArduCamMultiCamera" and method in {"camera", "cameraName"}:
            logging.info("Executing accepted camera command %s/%s", method, params[0])
        camera_switch = (
            method in {"camera", "cameraName"}
            and device.__class__.__name__ == "PiCamera2MultiCam"
            and getattr(device, "cameraSwitchMode", "restart") != "hot"
            and (not params or str(params[0]).lower() != "off")
        )
        switch_id = str(time.monotonic_ns()) if camera_switch else None
        loop = asyncio.get_event_loop()
        if camera_switch:
            stream_path = getattr(device, "streamPath", "cam")
            path_state = await loop.run_in_executor(self.executor, getMediaMTXPath, stream_path)
            previous_source_id = (path_state.get("source") or {}).get("id")
            switch_started_at = time.monotonic()
            await self.sendCommandToAllClients(f"cameraSwitchStarted/{switch_id}")
        try:
            response = await loop.run_in_executor(
                self.executor, runMethod, device, method, params
            )
        except Exception:
            if camera_switch:
                await self.sendCommandToAllClients(f"cameraSwitchFailed/{switch_id}")
            raise
        if camera_switch:
            pipeline_ready_at = time.monotonic()
            persistent_publisher = getattr(device, "persistentPublisher", False)
            if persistent_publisher:
                online = await loop.run_in_executor(
                    self.executor, device.waitForPublisherFrame
                )
            else:
                online = await loop.run_in_executor(
                    self.executor,
                    waitForMediaMTXOnline,
                    stream_path,
                    previous_source_id,
                )
            online_at = time.monotonic()
            pipeline_ms = round((pipeline_ready_at - switch_started_at) * 1000)
            online_ms = round((online_at - switch_started_at) * 1000)
            if online:
                state = "frame" if persistent_publisher else "online"
                await self.sendCommandToAllClients(
                    f"cameraSwitchReady/{switch_id}/{state}/{pipeline_ms}/{online_ms}"
                )
            else:
                await self.sendCommandToAllClients(
                    f"cameraSwitchFailed/{switch_id}/timeout/{pipeline_ms}/{online_ms}"
                )
        return response

    def startServer(self):
        with self._runtime_initialization_lock:
            if self._runtime_state != "ready":
                raise RuntimeError("Experiment runtime is not initialized")
            loop = self.loop
        asyncio.set_event_loop(loop)

        print(f"Server started at ws://{self.host}:{self.port}")
        try:
            self.server = loop.run_until_complete(
                websockets.serve(
                    self.handleConnection,
                    self.host,
                    self.port,
                    subprotocols=[JSON_SUBPROTOCOL],
                )
            )
            loop.run_forever()
        finally:
            if self._runtime_state != "stopped":
                loop.run_until_complete(self.shutdown("server_stopped"))
            loop.close()

    async def sendDataToClient(self, websocket, dataStr: str):
        try:
            await websocket.send(dataStr)
        except websockets.exceptions.ConnectionClosed:
            logging.warning(
                f"Failed to send message: {dataStr} - Connection was closed."
            )
            print(f"Failed to send message: {dataStr} - Connection was closed.")

    def uses_json_protocol(self, websocket):
        return getattr(websocket, "subprotocol", None) == JSON_SUBPROTOCOL

    def json_event_frame(self, name, data):
        return json.dumps(
            {
                "meta": {
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "version": "1.0.0",
                    "messageId": str(uuid.uuid4()),
                    "replyId": None,
                },
                "type": "event",
                "payload": {"name": name, "data": data},
            }
        )

    async def send_json_result(self, websocket, reply_id, status, ok, code=None, detail=None, message=None):
        payload = {"status": status, "ok": ok}
        if ok:
            payload["message"] = message
        else:
            payload["error"] = {"code": code, "detail": detail}
        frame = json.dumps(
            {
                "meta": {
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "version": "1.0.0",
                    "messageId": str(uuid.uuid4()),
                    "replyId": reply_id,
                },
                "type": "result",
                "payload": payload,
            }
        )
        await self.sendDataToClient(websocket, frame)

    async def sendMessage(self, websocket, message: str):
        if self.uses_json_protocol(websocket):
            await self.sendDataToClient(websocket, self.json_event_frame("message", {"message": message}))
            return
        updatedMessage = f"MESSAGE: {message}"
        await self.sendDataToClient(websocket, updatedMessage)

    async def sendAlert(self, websocket, alertMsg: str):
        if self.uses_json_protocol(websocket):
            await self.sendDataToClient(
                websocket,
                self.json_event_frame(
                    "alert",
                    {"severity": "info", "title": "ReMLA", "message": alertMsg},
                ),
            )
            return
        updatedAlertMsg = f"ALERT: {alertMsg}"
        await self.sendDataToClient(websocket, updatedAlertMsg)

    async def sendCommandToClient(self, websocket, command: str):
        if self.uses_json_protocol(websocket):
            if command.startswith("fault/"):
                await self.sendDataToClient(websocket, self.json_event_frame("fault", {"message": command[6:]}))
                return
            await self.sendDataToClient(websocket, self.json_event_frame("command", {"command": command}))
            return
        updatedCommand = f"COMMAND: {command}"
        await self.sendDataToClient(websocket, updatedCommand)

    async def sendCommandToAllClients(self, command: str):
        for client in list(self.clients):
            await self.sendCommandToClient(client, command)

    def deviceNames(self):
        names = []
        for deviceName in self.devices:
            names.append(deviceName)
        return names

    def startIpcListener(self, ipc_path=ipcSocketPath, loop=None):
        ipc_path = str(ipc_path)
        if loop is None:
            loop = self.loop
        if loop is None:
            raise RuntimeError("Experiment runtime is not initialized")
        if os.path.exists(ipc_path):
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.connect(ipc_path)
            except (ConnectionRefusedError, FileNotFoundError):
                os.unlink(ipc_path)
            except OSError as error:
                raise RuntimeError(f"Unable to inspect IPC listener at {ipc_path}") from error
            else:
                raise RuntimeError(f"IPC listener is already running at {ipc_path}")
            finally:
                probe.close()
        ipc_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound = False

        def ipc_loop():
            while True:
                try:
                    conn, _ = ipc_sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                conn.settimeout(0.25)
                try:
                    data = conn.recv(1024).decode().strip()
                except (OSError, socket.timeout):
                    conn.close()
                    continue
                future = asyncio.run_coroutine_threadsafe(
                    self.handle_ipc_command(data), loop
                )
                try:
                    result = future.result(timeout=30)
                except FutureTimeout:
                    result = {"ok": False, "error": "request_timeout"}
                except Exception as error:
                    logging.exception("IPC command failed")
                    result = {"ok": False, "error": str(error)}
                try:
                    conn.sendall(json.dumps(result).encode())
                except OSError:
                    pass
                conn.close()


        try:
            ipc_sock.bind(ipc_path)
            if ipcSocketGroup is not None:
                group_id = grp.getgrnam(ipcSocketGroup).gr_gid
                os.chown(ipc_path, -1, group_id)
                os.chmod(ipc_path, 0o660)
            bound = True
            ipc_sock.listen(1)
            ipc_sock.settimeout(0.25)
            self.ipc_path = Path(ipc_path)
            print(f"IPC listener started at {ipc_path}")
            ipc_thread = threading.Thread(target=ipc_loop, daemon=True)
            ipc_thread.start()
        except Exception:
            if bound and os.path.exists(ipc_path):
                os.unlink(ipc_path)
            ipc_sock.close()
            raise
        return ipc_sock, ipc_thread

    async def handle_ipc_command(self, command):
        if command.startswith("recover/"):
            _, action = command.split("/", 1)
            return await self.recover_from_fault(action)
        if command in {"boot", "contact"}:
            if self.activeClient is not None:
                await self.sendAlert(self.activeClient, f"Experiment/message/{command}")
                return {"ok": True}
            return {"ok": False, "error": "no_active_client"}
        return {"ok": False, "error": "unknown_command"}

    def request_shutdown(self, reason):
        loop = self.loop
        if loop is None:
            return None
        if not loop.is_running():
            loop.run_until_complete(self.shutdown(reason))
            return None
        if self._shutdown_future is None or self._shutdown_future.done():
            self._shutdown_future = asyncio.run_coroutine_threadsafe(
                self.shutdown(reason), loop
            )
        return self._shutdown_future

    async def shutdown(self, reason):
        async with self._shutdown_lock:
            if self._runtime_state == "stopped":
                return

            logging.info("Shutting down experiment: %s", reason)
            fault_shutdown = self._runtime_state == "faulted" or reason == "fault"
            self._runtime_state = "stopping"
            self.cancel_handoff_timeout()
            shutdown_error = None
            try:
                await self.cancel_queued_operations()
                loop = asyncio.get_running_loop()
                if fault_shutdown and self.executor is not None:
                    await loop.run_in_executor(self.executor, self.safeStopExperiment)
                await self.command_scheduler.wait_for_idle()
                if not fault_shutdown and self.executor is not None:
                    async with self.command_scheduler.reset_barrier():
                        await loop.run_in_executor(self.executor, self.shutdownExperiment)
            except BaseException as error:
                shutdown_error = error
                self.last_fault = f"Shutdown failed: {error}"
            finally:
                if self.server is not None:
                    self.server.close()
                    try:
                        await self.server.wait_closed()
                    except Exception as error:
                        if shutdown_error is None:
                            shutdown_error = error
                    self.server = None
                self.close_ipc_listener()
                if self.executor is not None:
                    self.executor.shutdown(wait=True, cancel_futures=True)
                self._runtime_state = "stopped"

            if self.loop is not None and self.loop.is_running():
                self.loop.call_soon(self.loop.stop)
            if shutdown_error is not None:
                raise shutdown_error

    def close_ipc_listener(self):
        if self.ipc_socket is not None:
            self.ipc_socket.close()
            self.ipc_socket = None
        if self.ipc_thread is not None:
            if self.ipc_thread is not threading.current_thread():
                self.ipc_thread.join(timeout=1)
            self.ipc_thread = None
        if self.ipc_path is not None:
            self.ipc_path.unlink(missing_ok=True)

    def resetExperiment(self, reason="unspecified"):
        logging.info("Resetting experiment to original state. reason=%s", reason)
        print(f"Resetting experiment reason={reason}")
        for deviceName, device in self.devices.items():
            logging.info(f"Resetting device {deviceName}")
            device.reset()
        logging.info("Experiment reset complete.")

    def shutdownExperiment(self):
        reset_error = None
        try:
            self.resetExperiment()
        except Exception as error:
            reset_error = error

        try:
            self.safeStopExperiment()
        except Exception as safe_stop_error:
            if reset_error is not None:
                raise RuntimeError(
                    f"Reset failed: {reset_error}; safe stop failed: {safe_stop_error}"
                ) from reset_error
            raise

        if reset_error is not None:
            raise reset_error

    def safeStopExperiment(self):
        errors = []
        for deviceName, device in self.devices.items():
            logging.info(f"Safely stopping device {deviceName}")
            try:
                device.safe_stop()
            except Exception as error:
                errors.append(f"{deviceName}: {error}")
        if errors:
            raise RuntimeError("Safe stop failed for " + "; ".join(errors))
