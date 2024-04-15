import socket
import sys
import os
import time
from signal import signal, SIGINT
import json
import logging
import threading
import queue
import RPi.GPIO as gpio
from pathlib import Path


class NoDeviceError(Exception):

    def __init__(self, device_name):
        self.device_name = device_name

    def __str__(self):
        return "NoDeviceError: This experiment doesn't have a device, '{0}'".format(self.device_name)

class Experiment(object):

    def __init__(self, name, rootDirectory="remoteLabs", admin=False, messenger=False):
        self.devices = {}

        # Marlon's addition
        self.locks = {}  # lock dict
        # self.queue?

        self.allStates = {}
        if messenger:
            self.messenger = Messenger(self)
        else:
            self.messenger = None
        self.messengerThread = None
        self.messengerSocket = None
        self.socketPath = ''
        self.socket = None
        self.connection = None
        self.clientAddress = None
        self.name = name
        self.initializedStates = False
        self.admin = admin
        self.directory = os.path.join("/home", "pi", rootDirectory, name)
        self.logName = os.path.join(self.directory, self.name + ".log")
        self.jsonFile = os.path.join(self.directory, self.name + ".json")
        logging.basicConfig(filename=self.logName, level=logging.INFO,
                            format="%(levelname)s - %(asctime)s - %(filename)s - %(funcName)s \r\n %(message)s \r\n")
        logging.info("""
        ##############################################################
        ####                Starting New Log                      ####
        ##############################################################    
        """)

    def addDevice(self, device):
        device.experiment = self
        logging.info("Adding Device - " + device.name)
        self.devices[device.name] = device
        # self.locks[device.name] = threading.Lock()

    def addLock(self, devices):
        lock = threading.Lock()
        for deviceName in devices:
            self.locks[deviceName.name] = lock

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

    def setSocketPath(self, path):
        logging.info("Setting Socket Path to " + str(path))
        self.socketPath = path

    def __waitToConnect(self):
        print("Experiment running... connect when ready")
        logging.info("Awaiting connection...")
        while True:
            try:
                self.connection, self.clientAddress = self.socket.accept()
                logging.info("Client Connected")
                self.__dataConnection(self.connection)
                time.sleep(0.01)
            except socket.timeout:
                logging.debug("Socket Timeout")
                continue
            except socket.error as err:
                logging.error("Socket Error!", exc_info=True)
                break

    def responsePrinter(self, q):
        while True:
            if not q.empty():
                response, deviceName = q.get()
                print("RESPONSE", response)
                if response is not None:
                    print("Sending data")
                    self.connection.send(response.encode())
                self.allStates[deviceName] = self.devices[deviceName].getState()
                with open(self.jsonFile, "w") as f:
                    json.dump(self.allStates, f)
            else:
                time.sleep(0.01)

    def __dataConnection(self, connection):
        responseQueue = queue.Queue()
        responseThread = threading.Thread(target=self.responsePrinter, args=(responseQueue,))
        responseThread.start()

        while True:
            try:
                while True:
                    data = self.connection.recv(1024)
                    if data:
                        self.commandHandler(data, responseQueue)
                    else:
                        break
                    time.sleep(0.01)
            except socket.error as err:
                logging.error("Connected Socket Error!", exc_info=True)
                return
            finally:
                self.closeHandler()

    def deviceNames(self):
        names = []
        for deviceName in self.devices:
            names.append(deviceName)
        return names

    def commandHandler(self, data, queue):
        data = data.decode('utf-8')
        logging.info("Handling Command - " + data)
        deviceName, command, params = data.strip().split("/")
        params = params.split(",")
        if deviceName not in self.devices:
            raise NoDeviceError(deviceName)

        commandThread = threading.Thread(target=self.devices[deviceName].cmdHandler,
                                         args=(command, params, queue, deviceName))
        commandThread.start()

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
                f = open(self.socketPath, 'w')
                f.close()

            if self.messenger is not None:
                self.messengerThread = threading.Thread(target=self.messenger.setup, daemon=True)
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
                print(f"Error accessing {self.socketPath}\nTry running 'sudo chown pi: {self.socketPath}'")
                os._exit(0)
                return
            else:
                print(f"Socket file not found. Did you configure uv4l-uvc.conf to use {self.socketPath}?")
                raise
        except socket.error as err:
            logging.error("Socket Error!", exc_info=True)
            print(f"Socket error: {err}")

    
    