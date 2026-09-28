from pathlib import Path
import tempfile
import unittest
from unittest import mock

from remla.device_config import validate_device_arguments
from remla.labcontrol.Controllers import StepperI2C
from remla.yaml import resolve_environment_reference
import remla.yaml as yaml_module


class DeviceConfigTests(unittest.TestCase):
    def test_resolves_exact_secret_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "asdipdu-password").write_text("secret\n")
            with mock.patch.object(yaml_module, "secretsDirectory", Path(directory)):
                self.assertEqual(
                    resolve_environment_reference("${secret:asdipdu-password}", "PDU", "password"),
                    "secret",
                )

    def test_missing_environment_reference_is_rejected_without_value_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(yaml_module, "secretsDirectory", Path(directory)):
                with self.assertRaisesRegex(ValueError, "asdipdu-password"):
                    resolve_environment_reference("${secret:asdipdu-password}", "PDU", "password")
    def test_reports_all_unsupported_options(self):
        class Camera:
            def __init__(self, name, numCameras, streamPath="cam"):
                pass

        with self.assertRaisesRegex(
            TypeError,
            "unsupported configuration options: cameraSwitchMode, persistentPublisher",
        ):
            validate_device_arguments(
                "Camera",
                Camera,
                {
                    "numCameras": 4,
                    "streamPath": "cam",
                    "cameraSwitchMode": "restart",
                    "persistentPublisher": True,
                },
            )

    def test_allows_declared_options(self):
        class Camera:
            def __init__(self, name, numCameras, streamPath="cam"):
                pass

        validate_device_arguments(
            "Camera",
            Camera,
            {"numCameras": 4, "streamPath": "cam"},
        )

    def test_allows_classes_with_keyword_arguments(self):
        class Camera:
            def __init__(self, name, **options):
                pass

        validate_device_arguments("Camera", Camera, {"customOption": True})

    def test_stepper_initial_position_is_a_supported_lab_option(self):
        validate_device_arguments(
            "Stage",
            StepperI2C,
            {"terminal": 4, "bounds": [-9750, 0], "initialPosition": 0},
        )

    def test_stepper_reset_returns_to_its_configured_initial_position(self):
        stepper = StepperI2C.__new__(StepperI2C)
        stepper.initialPosition = 0
        stepper.currentPosition = -120
        stepper.homeSwitch = None
        stepper.move = mock.Mock()

        stepper.reset()

        stepper.move.assert_called_once_with(120)


if __name__ == "__main__":
    unittest.main()
