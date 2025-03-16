import asyncio
import json
import logging
import os
import socket
import threading
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
                await self.sendMessage(
                    websocket, "You have control of the lab equipment."
                )
            else:
                await self.sendMessage(
                    websocket,
                    "You are connected but do not have control of the lab equipment.",
                )
            async for command in websocket:
                if websocket == self.activeClient:
                    asyncio.create_task(self.processCommand(command, websocket))
                else:
                    asyncio.create_task(
                        self.sendMessage(
                            websocket, "You do not have control to send commands."
                        )
                    )
        finally:
            if websocket == self.activeClient:
                self.clients.pop()  # Remove client from tracking
                self.activeClient = self.clients[0] if len(self.clients) > 0 else None

    async def processCommand(self, command, websocket):
        print(f"Processing Command {command} from {websocket}")
        logging.info("Processing Command - " + command)
        deviceName, cmd, params = command.strip().split("/")
        params = params.split(",")
        if deviceName not in self.devices:
            print("Raising no device error")
            raise NoDeviceError(deviceName)

        await self.runDeviceMethod(deviceName, cmd, params, websocket)

    async def runDeviceMethod(self, deviceName, method, params, websocket):
        device = self.devices.get(deviceName)

        lockGroupName = self.lockMapping.get(deviceName)
        if lockGroupName:
            async with self.lockGroups[lockGroupName]:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor, runMethod, device, method, params
                )
        else:
            logging.error("All devices need a lock")
            raise
            # result = await self.runMethod(device, method, params)
        if result is not None:
            await self.sendMessage(websocket, f"{deviceName} - {result}")
        else:
            await self.sendMessage(websocket, f"{deviceName} ran {method}")

    def startServer(self):
        # This function sets up and runs the WebSocket server indefinitely
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        start_server = websockets.serve(self.handleConnection, self.host, self.port)

        print(f"Server started at ws://{self.host}:{self.port}")
        loop.run_until_complete(start_server)
        loop.run_forever()

    async def sendDataToClient(self, websocket, dataStr: str):
        try:
            await websocket.send(dataStr)
        except websockets.exceptions.ConnectionClosed:
            logging.warning(
                f"Failed to send message: {dataStr} - Connection was closed."
            )
            print(f"Failed to send message: {dataStr} - Connection was closed.")

    async def sendMessage(self, websocket, message: str):
        updatedMessage = f"MESSAGE: {message}"
        await self.sendDataToClient(websocket, updatedMessage)

    async def sendAlert(self, websocket, alertMsg: str):
        updatedAlertMsg = f"ALERT: {alertMsg}"
        await self.sendDataToClient(websocket, updatedAlertMsg)

    async def sendCommandToClient(self, websocket, command: str):
        updatedCommand = f"COMMAND: {command}"
        await self.sendDataToClient(websocket, updatedCommand)

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

        if self.messengerSocket is not None:
            self.messengerSocket.close()
            logging.info("Messenger socket closed")

        if not self.admin:
            logging.info("Looping through devices shutting them down.")
            for deviceName, device in self.devices.items():
                logging.info("Running reset and cleanup on device " + deviceName)
                device.reset()
            logging.info("Everything shutdown properly. Exiting")
        gpio.cleanup()
        exit(0)

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

            if self.messenger is not None:
                self.messengerThread = threading.Thread(
                    target=self.messenger.setup, daemon=True
                )
                self.messengerThread.start()
            os.unlink(self.socketPath)
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            signal(SIGINT, self.exitHandler)
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
        except socket.error as err:
            logging.error("Socket Error!", exc_info=True)
            print(f"Socket error: {err}")
