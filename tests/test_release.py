import tempfile
import unittest
import hashlib
from unittest import mock
from pathlib import Path

from remla.release import ReleaseError, ReleaseInstaller


class ReleaseInstallerTests(unittest.TestCase):
    def test_verify_assets_rejects_missing_or_changed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / "remla-0.4.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel")
            checksums = root / "SHA256SUMS"
            checksums.write_text(
                f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}\n"
            )
            installer = ReleaseInstaller(root / "install")

            installer.verify_assets(checksums, [wheel])

            wheel.write_bytes(b"changed wheel")

            with self.assertRaises(ReleaseError):
                installer.verify_assets(checksums, [wheel])

    def test_activation_preserves_previous_release_for_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = ReleaseInstaller(root)
            first = root / "releases" / "0.4.0" / "venv"
            second = root / "releases" / "0.4.1" / "venv"
            first.mkdir(parents=True)
            second.mkdir(parents=True)

            installer.activate("0.4.0")
            installer.activate("0.4.1")

            self.assertEqual((root / "current").resolve(), second)
            self.assertEqual((root / "previous").resolve(), first)

            rolled_back = installer.rollback()

            self.assertEqual(rolled_back, "0.4.0")
            self.assertEqual((root / "current").resolve(), first)
            self.assertEqual((root / "previous").resolve(), second)

    def test_upgrade_rolls_back_when_service_restart_fails(self):
        from remla import main

        installer = mock.Mock()
        installer.install.return_value = "0.4.1"
        installer.rollback.return_value = "0.4.0"
        restart_failure = main.subprocess.CalledProcessError(1, ["systemctl", "restart"])

        with mock.patch.object(main, "ReleaseInstaller", return_value=installer), \
             mock.patch.object(main.subprocess, "run", side_effect=[restart_failure, None]) as run, \
             mock.patch.object(main, "alert") as alert:
            main.upgrade("0.4.1")

        installer.rollback.assert_called_once_with()
        self.assertEqual(run.call_count, 2)
        alert.assert_called_once()

    def test_upgrade_preserves_current_release_when_install_fails(self):
        from remla import main

        installer = mock.Mock()
        installer.install.side_effect = main.ReleaseError("download failed")

        with mock.patch.object(main, "ReleaseInstaller", return_value=installer), \
             mock.patch.object(main, "alert") as alert:
            main.upgrade()

        installer.rollback.assert_not_called()
        alert.assert_called_once_with("Unable to upgrade ReMLA: download failed")


if __name__ == "__main__":
    unittest.main()
