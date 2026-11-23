from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from typer.testing import CliRunner

from remla import main
from remla.yaml import yaml


OMITTED = object()
VALID_CAPTURE = {
    "enabled": True,
    "streamPath": "cam",
    "sensorMode": {"width": 2592, "height": 1944},
    "format": "png",
}


class SnapshotConfigTests(unittest.TestCase):
    def run_lab(self, still_capture=OMITTED):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            yaml.dump({"currentLab": "lab.yml"}, root / "settings.yml")
            lab = {"devices": {}, "locks": {}}
            if still_capture is not OMITTED:
                lab["stillCapture"] = still_capture
            yaml.dump(lab, root / "lab.yml")

            stack.enter_context(mock.patch.object(main, "settingsDirectory", root))
            stack.enter_context(mock.patch.object(main, "remoteLabsDirectory", root))
            stack.enter_context(mock.patch.object(main, "pidFilePath", root / "pid"))
            stack.enter_context(mock.patch.object(main, "cameraSetupLockPath", root / "maintenance"))
            stack.enter_context(mock.patch.object(main, "_is_remla_running", return_value=False))
            stack.enter_context(mock.patch.object(main, "get_boot_status", return_value=False))
            stack.enter_context(mock.patch.object(main, "cycle_initialize_cameras"))
            stack.enter_context(mock.patch.object(main, "get_camera_logger"))
            stack.enter_context(mock.patch.object(main.signal, "signal"))
            stack.enter_context(mock.patch.object(main.logging, "basicConfig"))
            stack.enter_context(mock.patch.object(main, "_teardown_foreground_startup"))
            experiment_type = stack.enter_context(mock.patch.object(main, "Experiment"))
            experiment = experiment_type.return_value
            experiment.load_persisted_state.return_value = None
            hardware = stack.enter_context(mock.patch.object(main, "initialize_hardware_resources"))
            constructors = stack.enter_context(mock.patch.object(main, "createDevicesFromYml", return_value={}))

            result = CliRunner().invoke(main.app, ["run", "--foreground"])

        return result, hardware, constructors, experiment

    def assert_rejected_before_hardware(self, config):
        result, hardware, constructors, experiment = self.run_lab(config)
        # Check ordering independently of how the CLI presents validation errors.
        hardware.assert_not_called()
        constructors.assert_not_called()
        experiment.startServer.assert_not_called()
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("stillCapture", result.output + str(result.exception))

    def test_omitted_and_false_allow_existing_labs_to_start(self):
        for config in (OMITTED, False):
            with self.subTest(config=config):
                result, hardware, constructors, experiment = self.run_lab(config)
                self.assertEqual(result.exit_code, 0, result.output + str(result.exception))
                hardware.assert_called_once_with()
                constructors.assert_called_once_with({})
                experiment.startServer.assert_called_once_with()

    def test_explicit_png_opt_in_is_accepted(self):
        result, hardware, constructors, experiment = self.run_lab(deepcopy(VALID_CAPTURE))
        self.assertEqual(result.exit_code, 0, result.output + str(result.exception))
        hardware.assert_called_once_with()
        constructors.assert_called_once_with({})
        experiment.startServer.assert_called_once_with()

    def test_malformed_top_level_values_are_rejected(self):
        for config in (None, True, 0, 1, "false", "png", [], [VALID_CAPTURE], {}):
            with self.subTest(config=config):
                self.assert_rejected_before_hardware(config)

    def test_enabled_opt_in_requires_every_explicit_field(self):
        for field in VALID_CAPTURE:
            with self.subTest(missing=field):
                config = deepcopy(VALID_CAPTURE)
                del config[field]
                self.assert_rejected_before_hardware(config)

    def test_unknown_fields_are_rejected_in_both_mappings(self):
        for nested in (False, True):
            with self.subTest(sensor_mode=nested):
                config = deepcopy(VALID_CAPTURE)
                target = config["sensorMode"] if nested else config
                target["unexpected"] = 1
                self.assert_rejected_before_hardware(config)

    def test_enabled_must_be_boolean_not_integer_or_string(self):
        for enabled in (None, 0, 1, "true", [], {}):
            with self.subTest(enabled=enabled):
                config = deepcopy(VALID_CAPTURE)
                config["enabled"] = enabled
                self.assert_rejected_before_hardware(config)

    def test_only_the_cam_stream_path_is_supported(self):
        for path in (None, True, 1, "", "other", "/cam", "cam/subpath", "../cam", []):
            with self.subTest(path=path):
                config = deepcopy(VALID_CAPTURE)
                config["streamPath"] = path
                self.assert_rejected_before_hardware(config)

    def test_only_png_is_supported(self):
        for output_format in (None, True, 1, "", "jpeg", "jpg", "dng", "PNG", []):
            with self.subTest(format=output_format):
                config = deepcopy(VALID_CAPTURE)
                config["format"] = output_format
                self.assert_rejected_before_hardware(config)

    def test_sensor_mode_requires_a_width_and_height_mapping(self):
        for mode in (None, True, 2592, "2592x1944", [], [2592, 1944], {},
                     {"width": 2592}, {"height": 1944}):
            with self.subTest(mode=mode):
                config = deepcopy(VALID_CAPTURE)
                config["sensorMode"] = mode
                self.assert_rejected_before_hardware(config)

    def test_sensor_dimensions_are_positive_integers_and_never_booleans(self):
        for dimension in ("width", "height"):
            for value in (None, True, False, 0, -1, 2592.0, "2592", [], {}):
                with self.subTest(dimension=dimension, value=value):
                    config = deepcopy(VALID_CAPTURE)
                    config["sensorMode"][dimension] = value
                    self.assert_rejected_before_hardware(config)

    def test_broker_limit_is_enforced_before_hardware(self):
        for width, height in ((8193, 1), (1, 8193), (4000, 3000)):
            with self.subTest(width=width, height=height):
                config = deepcopy(VALID_CAPTURE)
                config["sensorMode"] = {"width": width, "height": height}
                self.assert_rejected_before_hardware(config)


if __name__ == "__main__":
    unittest.main()
