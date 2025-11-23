import asyncio
import json
import logging
import os
import socket
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from signal import SIGINT, signal

import RPi.GPIO as gpio
import websockets

from remla.settings import *


class NoDeviceError(Exception):
    def __init__(self, device_name):
        self.device_name = device_name

    def __str__(self):
        return "NoDeviceError: This experiment doesn't have a device, '{0}'".format(
            self.device_name
        )


def runMethod(device, method, params):
    if hasattr(device, "cmdHandler"):
        func = getattr(device, "cmdHandler")
        result = func(method, params, device.name)
        return result
    else:
        logging.error(f"Device {device} does not have a cmdHandler method")
        raise


class Experiment(object):
    def __init__(self, name, host="localhost", port=8675, admin=False):
        self.name = name
        self.host = host
        self.port = port
        self.devices = {}

        self.lockGroups = {}
        self.lockMapping = {}

        self.allStates = {}
        self.clients = deque()
        self.activeClient = None

        self.initializedStates = False
        self.admin = admin
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.logPath = logsDirectory / f"{self.name}.log"
        # self.jsonFile = os.path.join(self.directory, self.name + ".json")
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
        self.startIpcListener()
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    # -----------------------
    # JSON helpers
    # -----------------------
    def _now_meta(self, replyId=None):
        return {
            "timestamp": int(time.time()),
            "version": "1.0.0",
            "messageId": uuid.uuid4().hex,
            "replyId": replyId,
        }

    def build_packet(self, ptype: str, payload, replyId=None) -> str:
        packet = {"meta": self._now_meta(replyId), "type": ptype, "payload": payload}
        return json.dumps(packet)

    def _map_response_type_to_packet_type(self, response_type: str) -> str:
        rt = (response_type or "").upper()
        if rt == "ALERT":
            return "alert"
        if rt == "COMMAND":
            return "command"
        if rt == "QUEUE":
            return "queue"
        return "debug"

    def parse_incoming_message(self, raw: str):
        """
        Accept either legacy "device/cmd/arg1,arg2" or JSON packet (type == 'command').
        Return (deviceName, commandName, parameters_dict, replyId)
        Legacy parameters become {"args": [...]}
        """
        # try JSON first
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and obj.get("type") == "command" and "payload" in obj:
                payload = obj["payload"]
                device = payload.get("deviceName")
                cmd = payload.get("commandName")
                params = payload.get("parameters", {})
                if isinstance(params, dict):
                    params_dict = params
                elif isinstance(params, list):
                    params_dict = {"args": params}
                else:
                    params_dict = {"args": [params]}
                replyId = obj.get("meta", {}).get("messageId")
                return device, cmd, params_dict, replyId
        except Exception:
            pass

        # fallback legacy "device/cmd/arg1,arg2"
        try:
            deviceName, cmd, params = raw.strip().split("/")
        except ValueError:
            raise ValueError("Invalid legacy command format")
        params_list = params.split(",") if params != "" else []
        return deviceName, cmd, {"args": params_list}, None

    def logException(self, task):
        if task.exception():
            logging.exception("Unknown Exception: %s", task.exception())

    def addDevice(self, device):
        device.experiment = self
        logging.info("Adding Device - " + device.name)
        self.devices[device.name] = device

    def addLockGroup(self, name: str, devices):
        lock = asyncio.Lock()
        self.lockGroups[name] = lock
        for device in devices:
            self.lockMapping[device.name] = name

    def recallState(self):
        logging.info("Recalling State")
        with open(self.jsonFile, "r") as f:
            self.allStates = json.load(f)
        for name, device in self.devices.items():
            device.setState(self.allStates[name])
        self.initializedStates = True

    def getControllerStates(self):
        logging.info("Getting Controller States")
        for name, device in self.devices.items():
            self.allStates[name] = device.getState()
        with open(self.jsonFile, "w") as f:
            json.dump(self.allStates, f)
        self.initializedStates = True

    async def handleConnection(self, websocket, path):
        print("Connection!:", websocket, path)
        self.clients.append(websocket)  # Track all clients by their WebSocket
        try:
            if self.activeClient is None and self.clients:
                self.activeClient = websocket
                await self.sendAlert(
                    websocket, "Experiment/controlStatus/1,You have control of the lab equipment."
                )
            else:
                await self.sendAlert(
                    websocket,
                    "Experiment/controlStatus/0,You are connected but do not have control of the lab equipment.",
                )
            async for command in websocket:
                if websocket == self.activeClient:
                    task = asyncio.create_task(self.processCommand(command, websocket))
                    task.add_done_callback(self.logException)
                else:
                    asyncio.create_task(
                        self.sendAlert(
                            websocket, "Experiment/controlStatus/0,You do not have control to send commands."
                        )
                    )
        finally:
            self.clients.remove(websocket)  # Remove client that closed connection
            if (
                websocket == self.activeClient
            ):  # if the removed client was the active client
                self.activeClient = (
                    self.clients[0] if len(self.clients) > 0 else None
                )  # set the first client in the list to be the new active client
                if self.activeClient is not None:
                    await self.sendAlert(
                        self.activeClient, "Experiment/controlStatus/1,You are the new active client."
                    )
                print("the first client has changed!")
                self.resetExperiment()
                # logging.info("Looping through devices - resetting them.")
                # for deviceName, device in self.devices.items():
                #     logging.info("Running reset and cleanup on device " + deviceName)
                #     device.reset()
                # logging.info("Everything reset properly!")

    async def processCommand(self, command, websocket):
        print(f"Processing Command {command} from {websocket}")
        logging.info("Processing Command - %s", command)
        try:
            deviceName, cmd, params_dict, replyId = self.parse_incoming_message(command)
        except Exception as e:
            await self.sendDataToClient(
                websocket, self.build_packet("debug", {"error": f"Invalid command: {str(e)}"})
            )
            return

        if deviceName not in self.devices:
            await self.sendDataToClient(
                websocket, self.build_packet("debug", {"error": f"No device named {deviceName}"}, replyId)
            )
            return

        await self.runDeviceMethod(deviceName, cmd, params_dict, websocket, replyId)

    async def runDeviceMethod(self, deviceName, method, params, websocket, replyId=None):
        device = self.devices.get(deviceName)

        lockGroupName = self.lockMapping.get(deviceName)
        if lockGroupName:
            async with self.lockGroups[lockGroupName]:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    self.executor, runMethod, device, method, params
                )
                # normalize controller responses:
                # (type, payload) or dict or string
                if isinstance(response, (list, tuple)) and len(response) >= 2:
                    response_type = response[0]
                    result = response[1]
                elif isinstance(response, dict):
                    response_type = "MESSAGE"
                    result = response
                else:
                    response_type = "MESSAGE"
                    result = response
        else:
            logging.error("All devices need a lock")
            raise
            # result = await self.runMethod(device, method, params)
        # Always send JSON packets to client
        if result is not None:
            logging.info("Device %s ran %s with result: %s", deviceName, method, result)
            packet_type = self._map_response_type_to_packet_type(response_type)
            payload = {
                "deviceName": deviceName,
                "commandName": method,
                "responseType": response_type,
                "result": result,
            }
            await self.sendDataToClient(websocket, self.build_packet(packet_type, payload, replyId))
        else:
            payload = {"deviceName": deviceName, "commandName": method, "info": "ran"}
            await self.sendDataToClient(websocket, self.build_packet("debug", payload, replyId))

    def startServer(self):
        # This function sets up and runs the WebSocket server indefinitely
        # loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        start_server = websockets.serve(self.handleConnection, self.host, self.port)

        print(f"Server started at ws://{self.host}:{self.port}")
        self.loop.run_until_complete(start_server)
        self.loop.run_forever()

    async def sendDataToClient(self, websocket, data):
        """
        Always send JSON. Accept either:
         - a dict/list (serialized as packet)
         - a JSON string (sent as-is)
         - anything else -> wrapped into a debug packet
        """
        try:
            if isinstance(data, (dict, list)):
                payload = json.dumps(data)
            elif isinstance(data, str):
                # if it's valid JSON string, send as-is; else wrap as debug packet
                try:
                    json.loads(data)
                    payload = data
                except Exception:
                    payload = self.build_packet("debug", {"message": data})
            else:
                payload = json.dumps(data)
            await websocket.send(payload)
        except websockets.exceptions.ConnectionClosed:
            logging.warning("Failed to send message: %s - Connection was closed.", data)
            print(f"Failed to send message: {data} - Connection was closed.")

    async def sendMessage(self, websocket, message):
        await self.sendDataToClient(websocket, self.build_packet("debug", {"message": message}))

    async def sendAlert(self, websocket, alertMsg):
        await self.sendDataToClient(websocket, self.build_packet("alert", {"message": alertMsg}))

    async def sendCommandToClient(self, websocket, command):
        await self.sendDataToClient(websocket, self.build_packet("command", {"command": command}))

    def deviceNames(self):
        names = []
        for deviceName in self.devices:
            names.append(deviceName)
        return names

    async def onClientDisconnect(self, websocket):
        # Remove client from the client queue if they disconnect
        if websocket in self.clients:
            self.clients.remove(websocket)
        if websocket == self.activeClient:
            self.activeClient = None
            # Pass control to the next available client in the queue
            while self.clientQueue:
                potentialController = self.clientQueue.popleft()
                if potentialController.open:
                    self.activeClient = potentialController
                    await self.sendMessage(
                        self.activeClient, "You now have control of the lab equipment."
                    )
                    break
            if not self.activeClient:
                print("No active clients")
                logging.info("No active clients")
                self.activeClient = None

            logging.info(f"Active client disconnected: {websocket}.")
        else:
            logging.info(f"Non-active client disconnected: {websocket}.")

    def exitHandler(self, signalReceived, frame):
        logging.info("Attempting to exit")
        if self.socket is not None:
            self.socket.close()
            logging.info("Socket is closed")

        # if self.messengerSocket is not None:
        #     self.messengerSocket.close()
        #     logging.info("Messenger socket closed")

        if not self.admin:
            self.resetExperiment()
        else:
            gpio.cleanup()
        exit(0)

    def setupSignalHandlers(self):
        signal.signal(signal.SIGINT, self.exitHandler)
        signal.signal(signal.SIGTERM, self.exitHandler)

    def closeHandler(self):
        logging.info("Client Disconnected. Handling Close.")
        if self.connection is not None:
            self.connection.close()
            logging.info("Connection to client closed.")
        if not self.admin:
            for deviceName, device in self.devices.items():
                logging.info("Running reset on device " + deviceName)
                device.reset()

    def setup(self):
        try:
            if not self.initializedStates:
                self.getControllerStates()
            if not os.path.exists(self.socketPath):
                f = open(self.socketPath, "w")
                f.close()

            # if self.messenger is not None:
            #     self.messengerThread = threading.Thread(
            #         target=self.messenger.setup, daemon=True
            #     )
            #     self.messengerThread.start()
            os.unlink(self.socketPath)
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            signal(SIGINT, self.exitHandler)
            signal(SIGTERM, self.exitHandler)
            self.socket.bind(self.socketPath)
            self.socket.listen(1)
            self.socket.setTimeout(1)
            self.__waitToConnect()
        except OSError:
            if os.path.exists(self.socketPath):
                print(
                    f"Error accessing {self.socketPath}\nTry running 'sudo chown pi: {self.socketPath}'"
                )
                os._exit(0)
                return
            else:
                print(
                    f"Socket file not found. Did you configure uv4l-uvc.conf to use {self.socketPath}?"
                )
                raise
            logging.error("Socket Error!", exc_info=True)
            print(f"Socket error: {err}")

    def startIpcListener(self, ipc_path="/tmp/remla_cmd.sock"):
        # Remove old socket if exists
        if os.path.exists(ipc_path):
            os.unlink(ipc_path)
        ipc_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        ipc_sock.bind(ipc_path)
        ipc_sock.listen(1)
        print(f"IPC listener started at {ipc_path}")
 
        def ipc_loop():
            while True:
                conn, _ = ipc_sock.accept()
                data = conn.recv(1024).decode().strip()
                if data in ["boot", "contact"]:
                    # Send message to active client
                    if self.activeClient:
                        packet = self.build_packet("alert", {"message": f"Experiment/message/{data}"})
                        future = asyncio.run_coroutine_threadsafe(
                            self.sendDataToClient(self.activeClient, packet), self.loop
                        )
                        print(f"Sent {data} message to active client.")
                    else:
                        print(f"No active client to send {data} message.")
                conn.close()
 
        threading.Thread(target=ipc_loop, daemon=True).start()

    def resetExperiment(self):
        logging.info("Resetting experiment to original state.")
        for deviceName, device in self.devices.items():
            logging.info(f"Resetting device {deviceName}")
            device.reset()
        logging.info("Experiment reset complete.")