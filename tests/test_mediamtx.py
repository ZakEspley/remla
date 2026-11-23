import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from remla import main

from remla.mediamtx import (
    MediaMTXInstallError,
    _verify_checksum,
    archive_platform,
    latest_release,
)


class MediaMTXInstallerTests(unittest.TestCase):
    def test_archive_platform(self):
        self.assertEqual(archive_platform("aarch64"), "linux_arm64")
        self.assertEqual(archive_platform("armv7l"), "linux_armv7")
        self.assertEqual(archive_platform("x86_64"), "linux_amd64")

        with self.assertRaises(MediaMTXInstallError):
            archive_platform("unknown")

    @patch("remla.mediamtx.urlopen")
    def test_latest_release_selects_matching_archive(self, mocked_urlopen):
        release = {
            "tag_name": "v1.20.0",
            "assets": [
                {
                    "name": "checksums.sha256",
                    "browser_download_url": "https://example.test/checksums.sha256",
                },
                {
                    "name": "mediamtx_v1.20.0_linux_arm64.tar.gz",
                    "browser_download_url": "https://example.test/arm64.tar.gz",
                },
                {
                    "name": "mediamtx_v1.20.0_linux_armv7.tar.gz",
                    "browser_download_url": "https://example.test/armv7.tar.gz",
                },
            ],
        }
        mocked_urlopen.return_value = io.BytesIO(json.dumps(release).encode())

        result = latest_release("armv7l")

        self.assertEqual(result.version, "1.20.0")
        self.assertEqual(result.archive_name, "mediamtx_v1.20.0_linux_armv7.tar.gz")
        self.assertEqual(result.archive_url, "https://example.test/armv7.tar.gz")

    @patch("remla.mediamtx.urlopen")
    def test_latest_release_rejects_new_major_version(self, mocked_urlopen):
        release = {
            "tag_name": "v2.0.0",
            "assets": [
                {
                    "name": "checksums.sha256",
                    "browser_download_url": "https://example.test/checksums.sha256",
                },
                {
                    "name": "mediamtx_v2.0.0_linux_arm64.tar.gz",
                    "browser_download_url": "https://example.test/arm64.tar.gz",
                },
            ],
        }
        mocked_urlopen.return_value = io.BytesIO(json.dumps(release).encode())

        with self.assertRaises(MediaMTXInstallError):
            latest_release("aarch64")

    def test_verify_checksum(self):
        with tempfile.TemporaryDirectory() as temp_name:
            temp_directory = Path(temp_name)
            archive = temp_directory / "mediamtx.tar.gz"
            checksums = temp_directory / "checksums.sha256"
            archive.write_bytes(b"release archive")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            checksums.write_text(f"{digest}  {archive.name}\n")

            _verify_checksum(archive, checksums, archive.name)

            checksums.write_text(f"{'0' * 64}  {archive.name}\n")
            with self.assertRaises(MediaMTXInstallError):
                _verify_checksum(archive, checksums, archive.name)


class MediaMTXCommandTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_stop_requires_root_without_touching_services(self):
        with (
            patch.object(main.os, "geteuid", return_value=1000),
            patch.object(main.subprocess, "run") as run,
        ):
            result = self.runner.invoke(main.app, ["mediamtx", "stop"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("sudo remla mediamtx stop", result.output)
        run.assert_not_called()

    def test_stop_only_stops_mediamtx(self):
        with (
            patch.object(main.os, "geteuid", return_value=0),
            patch.object(main.subprocess, "run") as run,
        ):
            result = self.runner.invoke(main.app, ["mediamtx", "stop"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("interrupt", result.output.lower())
        run.assert_called_once_with(["systemctl", "stop", "mediamtx.service"], check=True)

    def test_stop_reports_systemctl_failure(self):
        import subprocess

        with (
            patch.object(main.os, "geteuid", return_value=0),
            patch.object(
                main.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, ["systemctl", "stop", "mediamtx.service"]),
            ),
        ):
            result = self.runner.invoke(main.app, ["mediamtx", "stop"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Could not stop MediaMTX", result.output)

    def test_stop_reports_missing_systemctl(self):
        with (
            patch.object(main.os, "geteuid", return_value=0),
            patch.object(main.subprocess, "run", side_effect=OSError("systemctl unavailable")),
        ):
            result = self.runner.invoke(main.app, ["mediamtx", "stop"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("systemctl unavailable", result.output)

    def test_snapshot_install_routes_operator_stop_through_broker(self):
        with (
            patch.object(main.os, "geteuid", return_value=0),
            patch.object(main, "snapshotBrokerStatePath") as state,
            patch.object(main, "snapshotBrokerPath") as helper,
            patch.object(main.subprocess, "run") as run,
        ):
            state.exists.return_value = True
            helper.is_file.return_value = True
            result = self.runner.invoke(main.app, ["mediamtx", "stop"])
        self.assertEqual(result.exit_code, 0, result.output)
        run.assert_called_once_with([str(helper), "--stop-stream"], check=True, timeout=90)

    def test_missing_snapshot_broker_fails_closed_when_state_exists(self):
        with (
            patch.object(main.os, "geteuid", return_value=0),
            patch.object(main, "snapshotBrokerStatePath") as state,
            patch.object(main, "snapshotBrokerPath") as helper,
            patch.object(main.subprocess, "run") as run,
        ):
            state.exists.return_value = True
            helper.is_file.return_value = False
            result = self.runner.invoke(main.app, ["mediamtx", "stop"])
        self.assertNotEqual(result.exit_code, 0)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
