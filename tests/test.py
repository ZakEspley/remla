from remla.labcontrol.MockController import (
    BaseMockController,
    MockAbsorberController,
    MockPDUOutlet,
    MockStepperMotor,
)
from remla.labcontrol.Experiment import Experiment
from remla.main import _lab_display_name
from remla.yaml import createDevicesFromYml


def test_mock_device_factory_resolves_dependencies():
    devices = createDevicesFromYml(
        {
            "Motor": {
                "type": "S42CStepperMotor",
                "EN": 26,
                "STEP": 20,
                "DIR": 21,
                "bounds": [0, 100],
                "refPoints": {"home": 0, "sample": 50},
            },
            "Servo": {"type": "GeneralPWMServo", "PWM": 10},
            "Controller": {
                "type": "AbsorberController",
                "stepper": "Motor",
                "actuator": "Servo",
                "magnet": "Servo",
                "initialState": {"s0": None, "h0": "A1"},
                "holderMap": {"A1": "h0"},
            },
        },
        mock=True,
    )

    assert isinstance(devices["Motor"], MockStepperMotor)
    assert isinstance(devices["Controller"], MockAbsorberController)
    assert devices["Motor"].declared_type == "S42CStepperMotor"
    assert devices["Controller"].dependencies["stepper"] is devices["Motor"]


def test_mock_controller_updates_state_and_validates_parser():
    device = MockStepperMotor(
        "Stage",
        "S42CStepperMotor",
        {"bounds": [0, 100], "refPoints": {"sample": 42}},
    )

    assert device.cmdHandler("move", ["5"], "Stage") == ("MESSAGE", "Stage/position/5")
    assert device.state["position"] == 5
    assert device.cmdHandler("goto", ["sample"], "Stage") == (
        "MESSAGE",
        "Stage/position/42",
    )
    assert device.command_history[-1]["command"] == "goto"


def test_mock_state_snapshot_uses_experiment_devices():
    experiment = Experiment("Test", mock=True)
    device = MockPDUOutlet("Power", "PDUOutlet", {"outlets": [3]})
    experiment.addDevice(device)
    device.cmdHandler("on", ["3"], "Power")

    state = experiment.getMockState()
    assert state["mock"] is True
    assert state["devices"]["Power"]["state"]["outlets"]["3"] == "On"


def test_mock_absorber_controller_updates_subcontrollers():
    devices = createDevicesFromYml(
        {
            "Stage": {
                "type": "S42CStepperMotor",
                "EN": 26,
                "STEP": 20,
                "DIR": 21,
                "bounds": [0, 100],
                "refPoints": {"h0": 10, "s0": 50},
            },
            "Actuator": {"type": "FS5103RContinuousMotor", "PWM": 22},
            "Magnet": {"type": "GeneralPWMServo", "PWM": 10},
            "AbsorberController": {
                "type": "AbsorberController",
                "stepper": "Stage",
                "actuator": "Actuator",
                "magnet": "Magnet",
                "initialState": {"h0": "A1", "s0": ""},
                "holderMap": {"A1": "h0"},
                "throttle": 0.3,
            },
        },
        mock=True,
    )

    response = devices["AbsorberController"].cmdHandler(
        "place", ["(s0", "A1)"], "AbsorberController"
    )

    assert response == ("MESSAGE", "AbsorberController/place/1")
    assert devices["AbsorberController"].state["total"]["s0"] == "A1"
    assert devices["AbsorberController"].state["loaded"]["s0"] is True
    assert isinstance(devices["Stage"], BaseMockController)
    assert devices["Stage"].state["position"] == 50
    assert devices["Actuator"].state["disabled"] is True
    assert devices["Actuator"].state["throttleCount"] == 8
    assert devices["Actuator"].state["disableCount"] == 1
    assert devices["Magnet"].state["angle"] == -90.0
    assert devices["Magnet"].state["gotoCount"] == 2
    assert devices["Magnet"].state["disableCount"] == 1
    assert devices["Stage"].command_history[-1]["command"] == "goto"
    assert devices["AbsorberController"].state["subcontrollers"]["stepper"]["commands"] == 2
    assert devices["AbsorberController"].state["subcontrollers"]["actuator"]["state"]["throttleCount"] == 8
    assert devices["AbsorberController"].state["subcontrollers"]["magnet"]["state"]["gotoCount"] == 2

    devices["AbsorberController"].cmdHandler(
        "place", ["(s0", "A1)"], "AbsorberController"
    )

    assert devices["AbsorberController"].state["placeCount"] == 2
    assert devices["AbsorberController"].state["subcontrollers"]["stepper"]["commands"] == 2
    assert devices["AbsorberController"].state["subcontrollers"]["actuator"]["state"]["throttleCount"] == 8
    assert devices["AbsorberController"].state["subcontrollers"]["magnet"]["state"]["gotoCount"] == 2
    assert devices["AbsorberController"].state["lastPlace"]["skipped"] == [
        {"slot": "s0", "absorber": "A1", "reason": "already in target"}
    ]

    devices["AbsorberController"].cmdHandler(
        "place", ["(s0", ")", "(s1", "A2)"], "AbsorberController"
    )

    assert devices["AbsorberController"].command_history[-1]["params"] == [
        ["s0", ""],
        ["s1", "A2"],
    ]


def test_lab_display_name_uses_website_folder():
    assert (
        _lab_display_name(
            {"website": {"index": "remoteLabs/GammaRadiation/index.html"}},
            "gamma1.yml",
        )
        == "Gamma Radiation"
    )


if __name__ == "__main__":
    test_mock_device_factory_resolves_dependencies()
    test_mock_controller_updates_state_and_validates_parser()
    test_mock_state_snapshot_uses_experiment_devices()
    test_mock_absorber_controller_updates_subcontrollers()
    test_lab_display_name_uses_website_folder()
    print("mock hardware tests passed")
