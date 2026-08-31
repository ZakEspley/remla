import importlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def get_system_helpers():
    return importlib.import_module("remla.systemHelpers")


class BootStatusTests(unittest.TestCase):
    def test_system_helpers_imports_directly(self):
        result = subprocess.run(
            [sys.executable, "-c", "import remla.systemHelpers"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_marker_records_the_current_boot(self):
        system_helpers = get_system_helpers()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "boot.marker"
            logger = mock.Mock()

            with (
                mock.patch.object(system_helpers, "runMarker", marker),
                mock.patch.object(system_helpers.psutil, "boot_time", return_value=100),
                mock.patch.object(system_helpers, "get_camera_logger", return_value=logger),
            ):
                self.assertTrue(system_helpers.get_boot_status())

            self.assertEqual(marker.read_text(), "100")
            logger.error.assert_called_once()

    def test_matching_marker_does_not_report_a_new_boot(self):
        system_helpers = get_system_helpers()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "boot.marker"
            marker.write_text("100")
            logger = mock.Mock()

            with (
                mock.patch.object(system_helpers, "runMarker", marker),
                mock.patch.object(system_helpers.psutil, "boot_time", return_value=100),
                mock.patch.object(system_helpers, "get_camera_logger", return_value=logger),
            ):
                self.assertFalse(system_helpers.get_boot_status())

            self.assertEqual(marker.read_text(), "100")
            logger.info.assert_called_once()

    def test_changed_marker_reports_a_new_boot_and_updates_the_marker(self):
        system_helpers = get_system_helpers()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "boot.marker"
            marker.write_text("99")
            logger = mock.Mock()

            with (
                mock.patch.object(system_helpers, "runMarker", marker),
                mock.patch.object(system_helpers.psutil, "boot_time", return_value=100),
                mock.patch.object(system_helpers, "get_camera_logger", return_value=logger),
            ):
                self.assertTrue(system_helpers.get_boot_status())

            self.assertEqual(marker.read_text(), "100")
            logger.info.assert_called_once()


if __name__ == "__main__":
    unittest.main()
