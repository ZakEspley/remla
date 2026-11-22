import subprocess
import sys
import types
import unittest
from unittest import mock

from typer.testing import CliRunner

from remla import main


class CameraDiagnosticsTests(unittest.TestCase):
    INACTIVE = b"LoadState=loaded\nActiveState=inactive\nSubState=dead\n"
    ACTIVE = b"LoadState=loaded\nActiveState=active\nSubState=running\n"

    def setUp(self):
        self.runner = CliRunner()

    def test_check_reports_runtime_imports_without_opening_camera(self):
        with mock.patch("remla.main.check_picamera2_runtime", return_value="0.3.23") as check:
            result = self.runner.invoke(main.app, ["camera", "check"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("0.3.23", result.output)
        check.assert_called_once_with()

    def test_modes_warns_without_flag_and_refuses_active_service(self):
        with (
            mock.patch(
                "remla.camera_diagnostics.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout=self.ACTIVE),
            ),
            mock.patch("remla.main.list_camera_modes") as modes,
        ):
            result = self.runner.invoke(main.app, ["camera", "modes"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("opens the camera", result.output)
        self.assertIn("mediamtx.service is active", result.output)
        modes.assert_not_called()

    def test_modes_refuses_active_service_without_opening_camera(self):
        with (
            mock.patch(
                "remla.camera_diagnostics.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout=self.ACTIVE),
            ) as run,
            mock.patch("remla.main.list_camera_modes") as modes,
        ):
            result = self.runner.invoke(main.app, ["camera", "modes"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("active", result.output)
        run.assert_called_once()
        modes.assert_not_called()

    def test_modes_refuses_active_remla_even_if_mediamtx_is_stopped(self):
        with (
            mock.patch(
                "remla.camera_diagnostics.subprocess.run",
                side_effect=[
                    mock.Mock(returncode=0, stdout=self.INACTIVE),
                    mock.Mock(returncode=0, stdout=self.ACTIVE),
                ],
            ),
            mock.patch("remla.main.list_camera_modes") as modes,
        ):
            result = self.runner.invoke(main.app, ["camera", "modes"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("remla.service is active", result.output)
        modes.assert_not_called()

    def test_modes_refuses_unknown_service_state(self):
        with (
            mock.patch("remla.camera_diagnostics.subprocess.run", return_value=mock.Mock(returncode=1)),
            mock.patch("remla.main.list_camera_modes") as modes,
        ):
            result = self.runner.invoke(main.app, ["camera", "modes"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Cannot verify", result.output)
        modes.assert_not_called()

    def test_modes_refuses_transitional_and_missing_services(self):
        for state, substate, load in (
            ("activating", "start", "loaded"),
            ("deactivating", "stop-sigterm", "loaded"),
            ("activating", "auto-restart", "loaded"),
            ("inactive", "dead", "not-found"),
        ):
            with self.subTest(state=state, substate=substate, load=load):
                output = f"LoadState={load}\nActiveState={state}\nSubState={substate}\n".encode()
                with (
                    mock.patch("remla.camera_diagnostics.subprocess.run", return_value=mock.Mock(returncode=0, stdout=output)),
                    mock.patch("remla.main.list_camera_modes") as modes,
                ):
                    result = self.runner.invoke(main.app, ["camera", "modes"])
                self.assertNotEqual(result.exit_code, 0)
                modes.assert_not_called()

    def test_modes_reports_sensor_metadata_after_both_services_inactive(self):
        mode = {"size": [2592, 1944], "bit_depth": 10, "format": "SGBRG10_CSI2P"}
        with (
            mock.patch(
                "remla.camera_diagnostics.subprocess.run",
                return_value=mock.Mock(returncode=0, stdout=self.INACTIVE),
            ) as run,
            mock.patch("remla.main.list_camera_modes", return_value={"sensor": "ov5647", "modes": [mode]}) as modes,
        ):
            result = self.runner.invoke(main.app, ["camera", "modes"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("ov5647", result.output)
        self.assertIn("2592x1944", result.output)
        self.assertIn("10-bit", result.output)
        self.assertIn("opens the camera", result.output)
        self.assertEqual(run.call_count, 2)
        modes.assert_called_once_with(0)

    def test_modes_rejects_negative_camera_index(self):
        with mock.patch("remla.main.list_camera_modes") as modes:
            result = self.runner.invoke(main.app, ["camera", "modes", "--camera-index", "-1"])

        self.assertNotEqual(result.exit_code, 0)
        modes.assert_not_called()

    def test_check_fails_when_isolated_runtime_cannot_import_picamera2(self):
        with mock.patch("remla.main.check_picamera2_runtime", side_effect=RuntimeError("not importable")):
            result = self.runner.invoke(main.app, ["camera", "check"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("not importable", result.output)

    def test_enumeration_times_out_with_bounded_child(self):
        from remla.camera_diagnostics import list_camera_modes

        with mock.patch(
            "remla.camera_diagnostics.subprocess.run", side_effect=subprocess.TimeoutExpired("probe", 15)
        ) as run:
            with self.assertRaisesRegex(RuntimeError, "did not complete"):
                list_camera_modes(0)

        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_probe_closes_picamera2_after_reading_modes(self):
        from remla.camera_diagnostics import _probe_modes

        camera = mock.Mock()
        camera.sensor_modes = [{"size": (2592, 1944), "bit_depth": 10, "format": "SGBRG10_CSI2P"}]
        picamera = mock.Mock(return_value=camera)
        picamera.global_camera_info.return_value = [{"Model": "ov5647"}]
        with (
            mock.patch.dict(sys.modules, {"picamera2": types.SimpleNamespace(Picamera2=picamera)}),
            mock.patch("remla.camera_diagnostics.require_idle_services") as idle,
        ):
            result = _probe_modes(0)

        self.assertEqual(result["modes"][0]["size"], [2592, 1944])
        idle.assert_called_once_with()
        camera.close.assert_called_once_with()

    def test_probe_closes_camera_on_invalid_mode_data(self):
        from remla.camera_diagnostics import _probe_modes

        camera = mock.Mock(sensor_modes=[{"size": (1, 1)}])
        picamera = mock.Mock(return_value=camera)
        picamera.global_camera_info.return_value = [{"Model": "ov5647"}]
        with (
            mock.patch.dict(sys.modules, {"picamera2": types.SimpleNamespace(Picamera2=picamera)}),
            mock.patch("remla.camera_diagnostics.require_idle_services"),
            self.assertRaises(KeyError),
        ):
            _probe_modes(0)

        camera.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
