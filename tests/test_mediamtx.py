import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
