import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from remla import setupcmd
from remla import systemHelpers


class SetupCommandTests(unittest.TestCase):
    def test_lab_selection_does_not_deploy_the_website(self):
        with tempfile.TemporaryDirectory() as directory:
            lab_directory = Path(directory)
            lab_path = lab_directory / "lab.yml"
            index_path = lab_directory / "index.html"
            lab_path.write_text("lab")
            index_path.write_text("index")
            settings = {}
            lab_settings = {
                "network": {"port": 8080, "wsPort": 8675, "domain": "lab.local"},
                "website": {"index": Path("index.html"), "commonStaticFolder": False, "staticFolder": None},
            }

            with (
                mock.patch.object(setupcmd, "remoteLabsDirectory", lab_directory),
                mock.patch.object(setupcmd, "getSettings", return_value=settings),
                mock.patch.object(setupcmd, "searchForFilePattern", return_value=[Path("lab.yml")]),
                mock.patch.object(setupcmd.yaml, "load", return_value=lab_settings),
                mock.patch.object(setupcmd.yaml, "dump"),
                mock.patch.object(setupcmd, "_setup", return_value=(None, None)) as deploy,
            ):
                setupcmd.lab("lab.yml")

        deploy.assert_not_called()
        self.assertEqual(settings["currentLab"], Path("lab.yml"))

    def test_interactive_selection_does_not_deploy_the_website(self):
        with tempfile.TemporaryDirectory() as directory:
            lab_directory = Path(directory)
            lab_path = lab_directory / "lab.yml"
            lab_path.write_text("lab")
            settings = {}
            lab_settings = {
                "network": {"port": 8080, "wsPort": 8675, "domain": "lab.local"},
                "website": {"index": Path("index.html"), "commonStaticFolder": False, "staticFolder": None},
            }

            with (
                mock.patch.object(setupcmd, "remoteLabsDirectory", lab_directory),
                mock.patch.object(setupcmd, "getSettings", return_value=settings),
                mock.patch.object(setupcmd, "promptForNumericFile", return_value=lab_path),
                mock.patch.object(setupcmd.yaml, "load", return_value=lab_settings),
                mock.patch.object(setupcmd.yaml, "dump"),
                mock.patch.object(setupcmd.Confirm, "ask", side_effect=[False, False, False, False]),
                mock.patch.object(setupcmd, "_setup", return_value=(None, None)) as deploy,
            ):
                setupcmd.interactive()

        deploy.assert_not_called()
        self.assertEqual(settings["currentLab"], Path("lab.yml"))

    def test_website_deployment_requires_root(self):
        with (
            mock.patch.object(setupcmd.os, "geteuid", return_value=1000),
            mock.patch.object(setupcmd, "alert") as alert,
            self.assertRaises(setupcmd.typer.Abort),
        ):
            setupcmd.deploy_website()

        alert.assert_called_once_with("Website deployment must be run as root.")

    def test_website_deployment_uses_the_selected_lab(self):
        with tempfile.TemporaryDirectory() as directory:
            lab_directory = Path(directory)
            lab_path = lab_directory / "lab.yml"
            lab_path.write_text("lab")
            lab_settings = {"network": {}, "website": {}}

            with (
                mock.patch.object(setupcmd.os, "geteuid", return_value=0),
                mock.patch.object(setupcmd, "remoteLabsDirectory", lab_directory),
                mock.patch.object(setupcmd, "getSettings", return_value={"currentLab": Path("lab.yml")}),
                mock.patch.object(setupcmd.yaml, "load", return_value=lab_settings),
                mock.patch.object(setupcmd, "_setup", return_value=(None, None)) as deploy,
                mock.patch.object(setupcmd.subprocess, "run") as run,
                mock.patch.object(setupcmd, "success") as success,
            ):
                setupcmd.deploy_website()

        deploy.assert_called_once_with(lab_settings)
        run.assert_called_once_with(["systemctl", "reload", "nginx"], check=True)
        success.assert_called_once_with("Deployed the selected lab website.")

    def test_website_asset_copy_rejects_paths_outside_the_lab_root(self):
        with tempfile.TemporaryDirectory() as directory:
            lab_directory = Path(directory)
            (lab_directory / "index.html").write_text("index")
            destination = lab_directory / "website" / "index.html"

            with mock.patch.object(setupcmd, "remoteLabsDirectory", lab_directory):
                setupcmd.copy_lab_asset(Path("index.html"), destination)
                with self.assertRaisesRegex(ValueError, "inside the lab directory"):
                    setupcmd.copy_lab_asset(Path("/etc/shadow"), lab_directory / "website" / "secret")

            self.assertEqual(destination.read_text(), "index")

    def test_lab_specific_static_files_override_common_static_files(self):
        with tempfile.TemporaryDirectory() as directory:
            lab_directory = Path(directory)
            (lab_directory / "static").mkdir()
            (lab_directory / "lab-static").mkdir()
            (lab_directory / "static" / "site.css").write_text("common")
            (lab_directory / "lab-static" / "site.css").write_text("lab")
            destination = lab_directory / "website" / "static"

            with mock.patch.object(setupcmd, "remoteLabsDirectory", lab_directory):
                setupcmd.copy_lab_asset(Path("static"), destination, directory=True)
                setupcmd.copy_lab_asset(Path("lab-static"), destination, directory=True)

            self.assertEqual((destination / "site.css").read_text(), "lab")

    def test_website_asset_copy_rejects_a_fifo_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            lab_directory = Path(directory)
            fifo = lab_directory / "index.html"
            os.mkfifo(fifo)

            with mock.patch.object(setupcmd, "remoteLabsDirectory", lab_directory):
                with self.assertRaisesRegex(ValueError, "not a file"):
                    setupcmd.copy_lab_asset(fifo.name, lab_directory / "website" / "index.html")

    def test_nginx_configuration_snapshot_rejects_a_fifo_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "remla.conf"
            os.mkfifo(config_path)

            with mock.patch.object(setupcmd, "nginxConfPath", config_path):
                with self.assertRaisesRegex(ValueError, "not a regular file"):
                    setupcmd.snapshot_nginx_config()

    def test_website_deployment_rejects_matching_http_and_websocket_ports(self):
        lab_settings = {
            "network": {"port": 8080, "wsPort": 8080, "domain": "lab.local"},
            "website": {"index": "index.html", "commonStaticFolder": False, "staticFolder": None},
        }

        with self.assertRaisesRegex(ValueError, "must differ"):
            setupcmd._setup(lab_settings)

    def test_nginx_configuration_replaces_legacy_group_writable_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup_directory = root / "setup"
            settings_directory = root / "settings"
            available_directory = root / "available"
            enabled_directory = root / "enabled"
            for path in (setup_directory, settings_directory, available_directory, enabled_directory):
                path.mkdir()
            (setup_directory / "localhost.conf").write_text("server_name {{ hostname }};")
            legacy_config = settings_directory / "remla.conf"
            legacy_config.write_text("legacy")
            nginx_config = available_directory / "remla.conf"
            nginx_config.symlink_to(legacy_config)

            with (
                mock.patch.object(systemHelpers, "setupDirectory", setup_directory),
                mock.patch.object(systemHelpers, "nginxConfPath", nginx_config),
                mock.patch.object(systemHelpers, "nginxAvailablePath", available_directory),
                mock.patch.object(systemHelpers, "nginxEnabledPath", enabled_directory),
            ):
                systemHelpers.updateRemlaNginxConf(8080, "lab.local", 8675)

            self.assertFalse(nginx_config.is_symlink())
            self.assertEqual(nginx_config.read_text(), "server_name lab.local;")
            self.assertEqual((enabled_directory / "remla.conf").resolve(), nginx_config)


if __name__ == "__main__":
    unittest.main()
