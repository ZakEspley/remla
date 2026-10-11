import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from remla import secrets
from remla import main


class SecretStoreTests(unittest.TestCase):
    def test_set_list_and_remove_secret_without_exposing_value(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_directory = Path(directory)
            with mock.patch.object(secrets.grp, "getgrnam", return_value=SimpleNamespace(gr_gid=1000)), mock.patch.object(secrets.os, "chown"):
                secrets.set_secret("pdu-password", "value", secret_directory)

            self.assertEqual(secrets.list_secrets(secret_directory), ["pdu-password"])
            self.assertEqual((secret_directory / "pdu-password").read_text(), "value")
            secrets.remove_secret("pdu-password", secret_directory)
            self.assertEqual(secrets.list_secrets(secret_directory), [])

    def test_rejects_unsafe_secret_name(self):
        with self.assertRaises(ValueError):
            secrets.secret_path("../password")

    def test_restart_uses_systemd_restart(self):
        with mock.patch.object(main.subprocess, "run") as run, mock.patch.object(main, "success"):
            main.restart()

        run.assert_called_once_with(["systemctl", "restart", "remla.service"], check=True)
