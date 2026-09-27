import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock


class RuntimeImportTests(unittest.TestCase):
    def test_foreground_signal_shutdown_cleans_startup_pid(self):
        from remla import main

        experiment = mock.Mock()
        experiment.request_shutdown.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "remla.pid"
            pid_path.touch()

            with self.assertRaises(KeyboardInterrupt):
                main._request_foreground_shutdown(experiment, pid_path)

            self.assertFalse(pid_path.exists())
        experiment.request_shutdown.assert_called_once_with("foreground_signal")

    def test_foreground_signal_keeps_pid_until_async_shutdown_finishes(self):
        from remla import main

        experiment = mock.Mock()
        experiment.request_shutdown.return_value = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "remla.pid"
            pid_path.touch()

            main._request_foreground_shutdown(experiment, pid_path)

            self.assertTrue(pid_path.exists())

    def test_startup_teardown_requests_shutdown_and_removes_pid(self):
        from remla import main

        experiment = mock.Mock()
        experiment._runtime_state = "ready"
        with tempfile.TemporaryDirectory() as directory:
            pid_path = Path(directory) / "remla.pid"
            pid_path.touch()

            main._teardown_foreground_startup(experiment, pid_path)

            self.assertFalse(pid_path.exists())
        experiment.request_shutdown.assert_called_once_with("startup_failure")

    def test_recovery_ipc_client_returns_service_result(self):
        from remla import main

        socket_factory = mock.MagicMock()
        socket_client = socket_factory.return_value.__enter__.return_value
        socket_client.recv.return_value = b'{"ok": true, "state": "ready"}'

        with mock.patch.object(main.socket, "socket", socket_factory):
            result = main._send_ipc_command("recover/reset")

        self.assertEqual(result, {"ok": True, "state": "ready"})
        socket_client.sendall.assert_called_once_with(b"recover/reset")

    def test_start_starts_the_remla_service(self):
        from remla import main

        with (
            mock.patch.object(main.subprocess, "run") as run,
            mock.patch.object(main, "success") as success,
        ):
            main.start()

        run.assert_called_once_with(["systemctl", "start", "remla.service"], check=True)
        success.assert_called_once_with("Started remla")

    def test_main_imports_without_raspberry_pi_hardware(self):
        result = subprocess.run(
            [sys.executable, "-c", "import remla.main"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_controller_import_does_not_create_hardware_resources(self):
        script = textwrap.dedent(
            """
            import sys
            import types

            calls = []
            fake_pi = object()
            fake_visa_manager = object()

            pigpio = types.ModuleType("pigpio")
            pigpio.pi = lambda: (calls.append("pigpio.pi"), fake_pi)[1]
            pigpio.__getattr__ = lambda name: 0

            pyvisa = types.ModuleType("pyvisa")
            pyvisa.ResourceManager = lambda backend: (
                calls.append(f"pyvisa.ResourceManager:{backend}"), fake_visa_manager
            )[1]

            rpi = types.ModuleType("RPi")
            rpi.__path__ = []
            gpio = types.ModuleType("RPi.GPIO")
            gpio.BCM = 11
            gpio.setmode = lambda mode: calls.append(f"gpio.setmode:{mode}")
            gpio.__getattr__ = lambda name: 0

            class HardwareBase:
                def __init__(self, *args, **kwargs):
                    pass

            dlipower = types.ModuleType("dlipower")
            dlipower.PowerSwitch = HardwareBase

            rpistepper = types.ModuleType("RPistepper")
            rpistepper.Motor = HardwareBase

            tplink = types.ModuleType("tplink_smarthome")
            tplink.TPLinkSmartDevice = HardwareBase

            adafruit_motor = types.ModuleType("adafruit_motor")
            stepper = types.ModuleType("adafruit_motor.stepper")
            stepper.__getattr__ = lambda name: 0
            adafruit_motor.stepper = stepper

            adafruit_motorkit = types.ModuleType("adafruit_motorkit")
            adafruit_motorkit.MotorKit = HardwareBase

            sys.modules.update(
                {
                    "pigpio": pigpio,
                    "pyvisa": pyvisa,
                    "RPi": rpi,
                    "RPi.GPIO": gpio,
                    "dlipower": dlipower,
                    "RPistepper": rpistepper,
                    "tplink_smarthome": tplink,
                    "adafruit_motor": adafruit_motor,
                    "adafruit_motor.stepper": stepper,
                    "adafruit_motorkit": adafruit_motorkit,
                }
            )

            import importlib

            controllers = importlib.import_module("remla.labcontrol.Controllers")
            importlib.import_module("remla.main")

            assert calls == [], calls
            resources = controllers.initialize_hardware_resources()
            assert resources.pi is fake_pi
            assert resources.gpio is gpio
            assert resources.visa_manager is fake_visa_manager
            assert controllers.initialize_hardware_resources() is resources
            assert calls == [
                "pigpio.pi",
                "gpio.setmode:11",
                "pyvisa.ResourceManager:@py",
            ], calls
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
