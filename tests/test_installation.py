import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install.sh"
SERVICE = ROOT / "packaging" / "remla.service"
WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"


class PiInstallerTests(unittest.TestCase):
    def test_installed_environment_uses_shared_configuration_paths(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from remla.settings import ipcSocketPath, remoteLabsDirectory, settingsDirectory; "
                "print(settingsDirectory); print(remoteLabsDirectory); print(ipcSocketPath)",
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "REMLA_CONFIG_HOME": "/etc",
                "REMLA_LABS_DIRECTORY": "/var/lib/remla/labs",
                "REMLA_IPC_SOCKET": "/run/remla_cmd.sock",
            },
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["/etc/remla", "/var/lib/remla/labs", "/run/remla_cmd.sock"],
        )

    def test_dry_run_uses_local_wheel_and_dedicated_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "remla-0.4.0.dev0-py3-none-any.whl"
            wheel.touch()

            result = subprocess.run(
                ["bash", str(INSTALLER), "--dry-run", "--wheel", str(wheel)],
                cwd=ROOT,
                env={**os.environ, "REMLA_OPERATOR": "pi"},
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/opt/remla/releases/0.4.0.dev0", result.stdout)
        self.assertIn("/usr/local/bin/remla", result.stdout)
        self.assertIn("remla.service", result.stdout)
        self.assertIn("operator pi", result.stdout)

    def test_service_runs_the_stable_runtime_as_service_user(self):
        content = SERVICE.read_text()

        self.assertIn("User=remla", content)
        self.assertIn("Group=remla", content)
        self.assertIn("Environment=REMLA_PID_FILE=/run/remla/remla.pid", content)
        self.assertIn("Environment=REMLA_IPC_SOCKET=/run/remla/remla_cmd.sock", content)
        self.assertIn("RuntimeDirectoryMode=0755", content)
        self.assertIn("ConditionPathExists=!/run/remla-camera-setup.lock", content)
        self.assertIn("ExecStart=/opt/remla/current/bin/remla run --foreground", content)
        self.assertIn("Restart=always", content)

    def test_release_workflow_publishes_every_installer_asset(self):
        content = WORKFLOW.read_text()

        self.assertIn("uv build", content)
        self.assertIn("dist/install.sh", content)
        self.assertIn("dist/requirements.txt", content)
        self.assertIn("dist/SHA256SUMS", content)

    def test_installer_copies_local_assets_before_service_user_installs_them(self):
        content = INSTALLER.read_text()

        self.assertIn('wheel_asset="$release_directory/$(basename "$WHEEL")"', content)
        self.assertIn('install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0644 "$WHEEL" "$wheel_asset"', content)
        self.assertIn('--force-reinstall "$wheel_asset"', content)

    def test_installer_normalizes_nginx_web_root_permissions(self):
        content = INSTALLER.read_text()

        self.assertIn("chown -R root:root /var/www/remla", content)
        self.assertIn("find /var/www/remla -type d -exec chmod 0755 {} +", content)
        self.assertIn("find /var/www/remla -type f -exec chmod 0644 {} +", content)


class PackageBuildTests(unittest.TestCase):
    def test_built_wheel_contains_runtime_assets(self):
        wheels = list((ROOT / "dist").glob("remla-*.whl"))
        self.assertEqual(len(wheels), 1, "build exactly one wheel before running this test")

        with zipfile.ZipFile(wheels[0]) as wheel:
            names = set(wheel.namelist())

        self.assertIn("remla/setup/mediamtx.service", names)
        self.assertIn("remla/overlays/remla-camera-mux-4port.dtbo", names)


if __name__ == "__main__":
    unittest.main()
