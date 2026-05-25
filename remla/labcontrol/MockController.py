import copy
import datetime
import re
from pathlib import Path
from typing import Any

from remla.labcontrol import Controllers


class BaseMockController:
    deviceType = "mock"

    def __init__(
        self,
        name: str,
        declared_type: str,
        config: dict[str, Any] | None = None,
        dependencies: dict[str, Any] | None = None,
    ):
        self.name = name
        self.declared_type = declared_type
        self.config = config or {}
        self.dependencies = dependencies or {}
        self.experiment = None
        self.command_history = []
        self.real_class = getattr(Controllers, declared_type, None)
        self._copy_config_attributes()
        self.state = self._base_state()
        self.initialize_state()

    def _copy_config_attributes(self) -> None:
        for key, value in self.config.items():
            setattr(self, key, value)
        for key, value in self.dependencies.items():
            setattr(self, key, value)

    def _base_state(self) -> dict[str, Any]:
        return {
            "mock": True,
            "type": self.declared_type,
            "commands": 0,
            "lastCommand": None,
            "lastResponse": None,
        }

    def initialize_state(self) -> None:
        pass

    def reset_state(self) -> None:
        self.state = self._base_state()
        self.initialize_state()

    def _parse(self, cmd: str, params: list[str]) -> Any:
        parser = None
        if self.real_class is not None:
            parser = getattr(self.real_class, f"{cmd}_parser", None)
        if parser is None:
            return params
        try:
            return parser(self, params)
        except AttributeError:
            return params

    def cmdHandler(self, cmd, params, deviceName):
        parsed = self._parse(cmd, params)
        method = getattr(self, cmd, None)
        if callable(method):
            result = method(parsed)
        else:
            result = self._generic(cmd, parsed)
        if not isinstance(result, tuple):
            result = ("MESSAGE", result)
        self._record(cmd, parsed, result)
        return result

    def _generic(self, cmd: str, params: Any):
        self.state[cmd] = self._json_safe(params)
        return f"{self.name}/{cmd}/{self._format_value(params)}"

    def _record(self, cmd: str, params: Any, response: Any) -> None:
        self.state["commands"] = self.state.get("commands", 0) + 1
        self.state["lastCommand"] = {
            "command": cmd,
            "params": self._json_safe(params),
        }
        self.state["lastResponse"] = self._json_safe(response)
        entry = {
            "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "command": cmd,
            "params": self._json_safe(params),
            "response": self._json_safe(response),
            "state": self._json_safe(self.state),
        }
        self.command_history.append(entry)
        self.command_history = self.command_history[-50:]

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, BaseMockController):
            return value.name
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(v) for v in value]
        return value

    def _format_value(self, value: Any) -> str:
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return str(value)

    def _single_value(self, value: Any) -> Any:
        if isinstance(value, (list, tuple)) and len(value) == 1:
            return value[0]
        return value

    def reset(self):
        self.reset_state()
        return f"{self.name}/reset/ok"

    def getState(self):
        return self.state

    def setState(self, state):
        self.state = state

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.declared_type,
            "mockClass": self.__class__.__name__,
            "state": self._json_safe(self.state),
            "config": self._json_safe(self.config),
            "dependencies": {
                key: value.name for key, value in self.dependencies.items()
            },
            "history": self.command_history,
        }


class MockPDUOutlet(BaseMockController):
    def initialize_state(self) -> None:
        self.outlets = self.config.get("outlets", [1, 2, 3, 4, 5, 6, 7, 8])
        self.outletMap = self.config.get("outletMap", {})
        self.state["outlets"] = {str(outlet): "Off" for outlet in self.outlets}
        self.state["hostname"] = self.config.get("hostname")

    def on(self, outlet):
        self.state["outlets"][str(outlet)] = "On"
        return f"{self.name}/outlet/{outlet}/On"

    def off(self, outlet):
        self.state["outlets"][str(outlet)] = "Off"
        return f"{self.name}/outlet/{outlet}/Off"

    def reset(self):
        for outlet in self.outlets:
            self.state["outlets"][str(outlet)] = "Off"
        return f"{self.name}/reset/ok"


class MockPlug(BaseMockController):
    def initialize_state(self) -> None:
        self.state.update(
            {
                "host": self.config.get("host"),
                "port": self.config.get("port", 9999),
                "relayState": "OFF",
                "connected": False,
            }
        )

    def setRelay(self, relay):
        relay = self._single_value(relay)
        self.state["relayState"] = relay
        return f"{self.name}/relayState/{relay}"

    def reset(self):
        self.state["relayState"] = "OFF"
        return f"{self.name}/relayState/OFF"


class MockStepperMotor(BaseMockController):
    def initialize_state(self) -> None:
        self.refPoints = self.config.get("refPoints", {})
        bounds = self.config.get("bounds", [None, None])
        self.state.update(
            {
                "position": 0,
                "lastTarget": None,
                "bounds": bounds,
                "refPoints": self.refPoints,
                "homed": False,
            }
        )

    def move(self, steps):
        steps = int(self._single_value(steps))
        self.state["position"] += steps
        self.state["lastMove"] = steps
        return f"{self.name}/position/{self.state['position']}"

    def goto(self, ref):
        ref = self._single_value(ref)
        self.state["lastTarget"] = ref
        self.state["position"] = self.refPoints.get(ref, ref)
        return f"{self.name}/position/{self.state['position']}"

    def admingoto(self, ref):
        return self.goto(ref)

    def degMove(self, deg):
        deg = float(self._single_value(deg))
        self.state["lastDegreeMove"] = deg
        return f"{self.name}/degrees/{deg}"

    def home(self, params=None):
        self.state["position"] = 0
        self.state["homed"] = True
        return f"{self.name}/position/0"

    def reset(self):
        self.state["position"] = 0
        self.state["lastTarget"] = "reset"
        return f"{self.name}/position/0"


class MockDCMotor(BaseMockController):
    def initialize_state(self) -> None:
        self.state.update(
            {
                "running": False,
                "throttle": 0,
                "disabled": False,
                "pwm": self.config.get("PWM"),
                "limitPin": self.config.get("limitPin"),
                "reversed": self.config.get("_reversed", False),
            }
        )

    def throttle(self, throttle):
        throttle = self._single_value(throttle)
        self.state["running"] = float(throttle) != 0
        self.state["disabled"] = False
        self.state["throttle"] = throttle
        return f"{self.name}/throttle/{throttle}"

    def disable(self, params=None):
        self.state["running"] = False
        self.state["disabled"] = True
        return f"{self.name}/disabled/True"

    def reset(self):
        self.state["running"] = False
        self.state["throttle"] = 0
        return f"{self.name}/throttle/0"


class MockServo(BaseMockController):
    def initialize_state(self) -> None:
        self.state.update(
            {
                "running": False,
                "angle": 0,
                "disabled": False,
                "pwm": self.config.get("PWM"),
            }
        )

    def goto(self, angle):
        angle = float(self._single_value(angle))
        self.state["running"] = True
        self.state["disabled"] = False
        self.state["angle"] = angle
        return f"{self.name}/angle/{angle}"

    def disable(self, params=None):
        self.state["running"] = False
        self.state["disabled"] = True
        return f"{self.name}/disabled/True"

    def reset(self):
        self.state["running"] = False
        self.state["angle"] = 0
        return f"{self.name}/angle/0"


class MockMultiplexer(BaseMockController):
    def initialize_state(self) -> None:
        self.channels = self.config.get("channels", [0, 1, 2, 3, 4, 5, 6, 7])
        self.state.update(
            {
                "pins": self.config.get("pins", []),
                "inhibitorPin": self.config.get("inhibitorPin"),
                "channels": self.channels,
                "lastPress": None,
                "pressCount": 0,
            }
        )

    def press(self, channel):
        channel = self._single_value(channel)
        self.state["lastPress"] = channel
        self.state["pressCount"] += 1
        return f"{self.name}/press/{channel}"

    def reset(self):
        self.state["lastPress"] = None
        return f"{self.name}/press/None"


class MockInstrument(BaseMockController):
    def initialize_state(self) -> None:
        self.state.update(
            {
                "usbAddress": self.config.get("usbAddress"),
                "setting": "",
                "lastPress": None,
            }
        )

    def press(self, params):
        value = self._single_value(params)
        self.state["setting"] = value
        self.state["lastPress"] = value
        return f"{self.name}/setting/{value}"


class MockCamera(BaseMockController):
    def initialize_state(self) -> None:
        self.cameraNames = self.config.get("cameraNamesDict") or {}
        self.cameraDict = {"a": None, "b": None, "c": None, "d": None, "off": None}
        self.state.update(
            {
                "camera": self.config.get("initialCamera", "a"),
                "cameraName": None,
                "numCameras": self.config.get("numCameras"),
                "videoNumber": self.config.get("videoNumber", 0),
                "i2cbus": self.config.get("i2cbus"),
                "controlPins": self.config.get("controlPins"),
                "imageSettings": {},
            }
        )

    def camera(self, camera):
        camera = self._single_value(camera)
        self.state["camera"] = camera
        self.state["cameraName"] = None
        return f"{self.name}/camera/{camera}"

    def cameraName(self, camera_name):
        camera_name = self._single_value(camera_name)
        camera_slot = self.cameraNames.get(camera_name, camera_name)
        self.state["cameraName"] = camera_name
        self.state["camera"] = camera_slot
        return f"{self.name}/camera/{camera_slot}"

    def imageMod(self, params):
        if isinstance(params, (list, tuple)) and len(params) >= 2:
            self.state["imageSettings"][str(params[0])] = params[1]
        return f"{self.name}/imageMod/{self._format_value(params)}"

    def reset(self):
        return self.camera(self.config.get("initialCamera", "a"))


class MockGPIOOutput(BaseMockController):
    def initialize_state(self) -> None:
        self.state.update(
            {
                "pin": self.config.get("pin"),
                "state": "ON" if self.config.get("initialState", False) else "OFF",
            }
        )

    def on(self, params=None):
        self.state["state"] = "ON"
        return f"{self.name}/state/ON"

    def off(self, params=None):
        self.state["state"] = "OFF"
        return f"{self.name}/state/OFF"

    def reset(self):
        self.state["state"] = "OFF"
        return f"{self.name}/state/OFF"


class MockPushButton(BaseMockController):
    def initialize_state(self) -> None:
        self.state.update(
            {
                "pin": self.config.get("pin"),
                "initialState": self.config.get("initialState", False),
                "lastPress": None,
                "pressCount": 0,
            }
        )

    def press(self, params=None):
        self.state["lastPress"] = "pressed"
        self.state["pressCount"] += 1
        return f"{self.name}/press/pressed"


class MockPWMChannel(BaseMockController):
    def initialize_state(self) -> None:
        self.state.update(
            {
                "pin": self.config.get("pin"),
                "frequency": self.config.get("frequency"),
                "dutyCycle": self.config.get("defaultDutyCycle", 0),
            }
        )

    def power(self, duty_cycle):
        duty_cycle = self._single_value(duty_cycle)
        self.state["dutyCycle"] = duty_cycle
        return f"{self.name}/power/{duty_cycle}"

    def reset(self):
        self.state["dutyCycle"] = self.config.get("defaultDutyCycle", 0)
        return f"{self.name}/power/{self.state['dutyCycle']}"


class MockSwitch(BaseMockController):
    def initialize_state(self) -> None:
        self.state.update(
            {
                "pin": self.config.get("pin"),
                "status": self.config.get("state", False),
            }
        )

    def getStatus(self, params=None):
        return self.state["status"]


class MockAbsorberController(BaseMockController):
    def initialize_state(self) -> None:
        initial = copy.deepcopy(self.config.get("initialState", {}))
        self.state.update(
            {
                "loaded": {
                    slot: bool(absorber)
                    for slot, absorber in initial.items()
                    if str(slot).startswith("s")
                },
                "total": initial,
                "requestedPositions": [],
                "lastTransfer": None,
                "placeCount": 0,
                "transferCount": 0,
                "subcontrollers": {},
            }
        )
        self._update_subcontroller_status()

    def _update_subcontroller_status(self) -> None:
        subcontrollers = {}
        for role, controller in self.dependencies.items():
            subcontrollers[role] = {
                "name": controller.name,
                "type": controller.declared_type,
                "mockClass": controller.__class__.__name__,
                "commands": controller.state.get("commands", 0),
                "lastCommand": controller.state.get("lastCommand"),
                "lastResponse": controller.state.get("lastResponse"),
                "state": controller._json_safe(controller.state),
            }
        self.state["subcontrollers"] = subcontrollers

    def _run_dependency(self, dependency_name: str, cmd: str, params: list[Any]) -> Any:
        dependency = self.dependencies.get(dependency_name)
        if dependency is None:
            return None
        response = dependency.cmdHandler(
            cmd, [str(param) for param in params], dependency.name
        )
        self._update_subcontroller_status()
        return response

    def _parse(self, cmd: str, params: list[str]) -> Any:
        if cmd == "place":
            return self._parse_pairs(params)
        return super()._parse(cmd, params)

    def _parse_pairs(self, params: Any) -> list[tuple[str, str]]:
        if isinstance(params, dict):
            moves = []
            for group in ("unload", "load", "internal"):
                moves.extend(tuple(move) for move in params.get(group, []))
            for chain in params.get("chains", []):
                moves.extend(tuple(move) for move in chain)
            return moves

        if not isinstance(params, (list, tuple)):
            return []
        if all(isinstance(item, (list, tuple)) and len(item) == 2 for item in params):
            return [(str(slot), str(absorber)) for slot, absorber in params]

        command_text = ",".join(str(item) for item in params)
        matches = re.findall(r"\(([^,)]*),([^)]*)\)", command_text)
        if matches:
            return [(slot.strip(), absorber.strip()) for slot, absorber in matches]

        cleaned = [str(item).replace("(", "").replace(")", "").strip() for item in params]
        pairs = []
        i = 0
        while i + 1 < len(cleaned):
            pairs.append((cleaned[i], cleaned[i + 1]))
            i += 2
        return pairs

    def _find_absorber_slot(self, absorber: str) -> str | None:
        for slot, current_absorber in self.state.get("total", {}).items():
            if current_absorber == absorber:
                return slot
        return None

    def _transfer(self, slot1: str, slot2: str) -> None:
        absorber = self.state.get("total", {}).get(slot1, "")
        throttle = self.config.get("throttle", 1.0)

        self._run_dependency("stepper", "goto", [slot1])
        self._run_dependency("actuator", "throttle", [throttle])
        self._run_dependency("actuator", "throttle", [0])
        self._run_dependency("actuator", "throttle", [-throttle])
        self._run_dependency("actuator", "throttle", [0])
        self._run_dependency("stepper", "goto", [slot2])
        self._run_dependency("actuator", "throttle", [throttle])
        self._run_dependency("actuator", "throttle", [0])
        self._run_dependency("magnet", "goto", [45])
        self._run_dependency("actuator", "throttle", [-throttle])
        self._run_dependency("actuator", "throttle", [0])
        self._run_dependency("actuator", "disable", [])
        self._run_dependency("magnet", "goto", [-90])
        self._run_dependency("magnet", "disable", [])

        self.state.setdefault("total", {})[slot1] = ""
        self.state.setdefault("total", {})[slot2] = absorber
        if slot1 in self.state.setdefault("loaded", {}):
            self.state["loaded"][slot1] = False
        if slot2 in self.state["loaded"]:
            self.state["loaded"][slot2] = absorber not in ("", None)
        self.state["transferCount"] += 1
        self.state["lastTransfer"] = {"from": slot1, "to": slot2, "absorber": absorber}
        self._update_subcontroller_status()

    def place(self, params):
        requested_positions = self._parse_pairs(params)
        self.state["placeCount"] += 1
        self.state["requestedPositions"] = [
            {"slot": slot, "absorber": absorber}
            for slot, absorber in requested_positions
        ]
        skipped = []

        for target_slot, desired_absorber in requested_positions:
            current_absorber = self.state.get("total", {}).get(target_slot)
            if desired_absorber in ("", "None", "null", None):
                if current_absorber not in ("", None):
                    holder_slot = self.config.get("holderMap", {}).get(current_absorber)
                    if holder_slot is not None:
                        self._transfer(target_slot, holder_slot)
                else:
                    skipped.append(
                        {
                            "slot": target_slot,
                            "absorber": desired_absorber,
                            "reason": "already empty",
                        }
                    )
                continue

            source_slot = self._find_absorber_slot(desired_absorber)
            if source_slot is None:
                skipped.append(
                    {
                        "slot": target_slot,
                        "absorber": desired_absorber,
                        "reason": "absorber not found",
                    }
                )
                continue
            if source_slot == target_slot:
                skipped.append(
                    {
                        "slot": target_slot,
                        "absorber": desired_absorber,
                        "reason": "already in target",
                    }
                )
                continue

            if current_absorber not in ("", None):
                holder_slot = self.config.get("holderMap", {}).get(current_absorber)
                if holder_slot is not None:
                    self._transfer(target_slot, holder_slot)

            self._transfer(source_slot, target_slot)

        self.state["lastPlace"] = {
            "requested": self.state["requestedPositions"],
            "skipped": skipped,
            "transferCount": self.state["transferCount"],
        }
        self._update_subcontroller_status()
        return f"{self.name}/place/{len(requested_positions)}"

    def reset(self):
        for dependency_name in ("actuator", "magnet", "stepper"):
            self._run_dependency(dependency_name, "reset", [])
        self.reset_state()
        self._update_subcontroller_status()
        return f"{self.name}/reset/ok"


class GenericMockController(BaseMockController):
    pass


MOCK_CONTROLLER_TYPES = {
    "PDUOutlet": MockPDUOutlet,
    "Plug": MockPlug,
    "StepperSimple": MockStepperMotor,
    "StepperI2C": MockStepperMotor,
    "FilterStepperI2C": MockStepperMotor,
    "PololuStepperMotor": MockStepperMotor,
    "S42CStepperMotor": MockStepperMotor,
    "DCMotorI2C": MockDCMotor,
    "PololuDCMotor": MockDCMotor,
    "FS5103RContinuousMotor": MockDCMotor,
    "GeneralPWMServo": MockServo,
    "AbsorberController": MockAbsorberController,
    "Multiplexer": MockMultiplexer,
    "Keithley6514Electrometer": MockInstrument,
    "Keithley2000Multimeter": MockInstrument,
    "ArduCamMultiCamera": MockCamera,
    "ElectronicScreen": MockGPIOOutput,
    "SingleGPIO": MockGPIOOutput,
    "PushButton": MockPushButton,
    "PWMChannel": MockPWMChannel,
    "LimitSwitch": MockSwitch,
    "HomeSwitch": MockSwitch,
}


def create_mock_controller(
    name: str,
    declared_type: str,
    config: dict[str, Any] | None = None,
    dependencies: dict[str, Any] | None = None,
) -> BaseMockController:
    controller_class = MOCK_CONTROLLER_TYPES.get(declared_type, GenericMockController)
    return controller_class(
        name=name,
        declared_type=declared_type,
        config=config,
        dependencies=dependencies,
    )


MockController = BaseMockController
