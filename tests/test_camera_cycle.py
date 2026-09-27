import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from remla import main


class CameraCycleCommandTests(unittest.TestCase):
    def test_init_never_cycles_cameras(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(main.os, "geteuid", return_value=0))
                stack.enter_context(mock.patch.object(main, "settingsDirectory", root / "settings"))
                stack.enter_context(mock.patch.object(main, "logsDirectory", root / "logs"))
                stack.enter_context(mock.patch.object(main, "websiteDirectory", root / "website"))
                stack.enter_context(mock.patch.object(main, "websiteStaticDirectory", root / "website" / "static"))
                stack.enter_context(mock.patch.object(main, "websiteJSDirectory", root / "website" / "js"))
                stack.enter_context(mock.patch.object(main, "websiteCSSDirectory", root / "website" / "css"))
                stack.enter_context(mock.patch.object(main, "websiteImgsDirectory", root / "website" / "images"))
                stack.enter_context(mock.patch.object(main, "remoteLabsDirectory", root / "labs"))
                stack.enter_context(mock.patch.object(main, "runMarker", root / "boot.marker"))
                stack.enter_context(mock.patch.object(main, "is_package_installed", return_value=True))
                stack.enter_context(mock.patch.object(main, "enable_service", return_value=True))
                stack.enter_context(mock.patch.object(main, "echoResult"))
                stack.enter_context(mock.patch.object(main, "_mediamtx"))
                stack.enter_context(mock.patch.object(main, "_nginx"))
                stack.enter_context(mock.patch.object(main, "_createSettingsFile"))
                restore_permissions = stack.enter_context(
                    mock.patch.object(main, "restore_runtime_storage_permissions")
                )
                stack.enter_context(mock.patch.object(main, "createServiceFile"))
                stack.enter_context(mock.patch.object(main, "createRemlaPolicy"))
                stack.enter_context(mock.patch.object(main, "configure_camera_hardware"))
                stack.enter_context(mock.patch.object(main.subprocess, "run"))
                cycle_cameras = stack.enter_context(
                    mock.patch.object(main, "cycle_initialize_cameras")
                )
                main.init()

        cycle_cameras.assert_not_called()
        restore_permissions.assert_called_once_with()

    def test_camera_setup_requires_root(self):
        with (
            mock.patch.object(main.os, "geteuid", return_value=1000),
            mock.patch.object(main, "alert") as alert,
            self.assertRaises(main.typer.Abort),
        ):
            main.camera_setup()

        alert.assert_called_once_with("This command must be run as root.")

    def test_camera_setup_stops_service_before_reconfiguring(self):
        inactive_result = mock.Mock(returncode=3)
        with (
            mock.patch.object(main.os, "geteuid", return_value=0),
            mock.patch.object(main.typer, "confirm", return_value=True),
            mock.patch.object(main.subprocess, "run", side_effect=[inactive_result, None]) as run,
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(main, "cameraSetupLockPath", Path(directory) / "camera.lock"),
            mock.patch.object(main, "configure_camera_hardware") as configure,
            mock.patch.object(main, "success"),
        ):
            main.camera_setup()

        run.assert_has_calls(
            [
                mock.call(["systemctl", "is-active", "--quiet", "remla.service"], check=False),
                mock.call(["systemctl", "stop", "remla.service"], check=True),
            ]
        )
        configure.assert_called_once_with()

    def test_camera_setup_restores_an_active_service_when_no_change_is_made(self):
        active_result = mock.Mock(returncode=0)
        with (
            mock.patch.object(main.os, "geteuid", return_value=0),
            mock.patch.object(main.typer, "confirm", return_value=True),
            mock.patch.object(main.subprocess, "run", side_effect=[active_result, None, None]) as run,
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(main, "cameraSetupLockPath", Path(directory) / "camera.lock"),
            mock.patch.object(main, "configure_camera_hardware", return_value=False),
            mock.patch.object(main, "success") as success,
        ):
            main.camera_setup()

        self.assertEqual(run.call_count, 3)
        success.assert_not_called()

    def test_camera_setup_refuses_an_existing_maintenance_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "camera.lock"
            lock_path.touch()
            with (
                mock.patch.object(main.os, "geteuid", return_value=0),
                mock.patch.object(main.typer, "confirm", return_value=True),
                mock.patch.object(main, "cameraSetupLockPath", lock_path),
                mock.patch.object(main, "alert") as alert,
                mock.patch.object(main.subprocess, "run") as run,
                self.assertRaises(main.typer.Abort),
            ):
                main.camera_setup()

        alert.assert_called_once_with("Camera setup is already active or a reboot is still required.")
        run.assert_not_called()

    def test_camera_setup_removes_lock_when_service_state_check_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "camera.lock"
            with (
                mock.patch.object(main.os, "geteuid", return_value=0),
                mock.patch.object(main.typer, "confirm", return_value=True),
                mock.patch.object(main, "cameraSetupLockPath", lock_path),
                mock.patch.object(main.subprocess, "run", side_effect=OSError("systemctl unavailable")),
                self.assertRaisesRegex(OSError, "systemctl unavailable"),
            ):
                main.camera_setup()

            self.assertFalse(lock_path.exists())

    def test_boot_configuration_is_replaced_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.txt"
            config_path.write_text("old\n")

            main.replace_boot_config(config_path, ["new\n"])

            self.assertEqual(config_path.read_text(), "new\n")

    def test_run_refuses_to_start_during_camera_maintenance(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "camera.lock"
            lock_path.touch()
            with (
                mock.patch.object(main, "cameraSetupLockPath", lock_path),
                mock.patch.object(main, "alert") as alert,
                self.assertRaises(main.typer.Abort),
            ):
                main.run()

        alert.assert_called_once_with("Camera boot configuration is pending. Reboot before starting ReMLA.")


if __name__ == "__main__":
    unittest.main()
