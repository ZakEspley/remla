import hashlib
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install.sh"
SERVICE = ROOT / "packaging" / "remla.service"
WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"
PYPROJECT = ROOT / "pyproject.toml"
MAIN = ROOT / "remla" / "main.py"


class PiInstallerTests(unittest.TestCase):
    def test_downloaded_release_rejects_each_bad_or_missing_checksum(self):
        assets = ["remla-0.5.0-py3-none-any.whl", "requirements.txt", "remla.service", "49-remla.rules"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in assets:
                (root / name).write_bytes(name.encode())
            curl = root / "curl"
            curl.write_text(
                '#!/bin/sh\n'
                'while [ "$#" -gt 0 ]; do\n'
                '  if [ "$1" = "--output" ]; then output="$2"; shift 2; else url="$1"; shift; fi\n'
                'done\n'
                'cp "$REMLA_TEST_ASSETS_DIR/${url##*/}" "$output"\n'
            )
            curl.chmod(0o755)
            env = {**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                   "REMLA_TEST_ASSETS_DIR": str(root), "REMLA_OPERATOR": "test-operator"}
            for name in assets:
                checksums = "".join(
                    f"{hashlib.sha256((root / asset).read_bytes()).hexdigest()}  {asset}\n"
                    for asset in assets
                )
                (root / "SHA256SUMS").write_text(checksums)
                (root / name).write_bytes(b"corrupted")
                with self.subTest(asset=name, case="corrupt"):
                    result = subprocess.run(
                        ["bash", str(INSTALLER), "--version", "0.5.0", "--dry-run"],
                        env=env, text=True, capture_output=True,
                    )
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                (root / name).write_bytes(name.encode())
                (root / "SHA256SUMS").write_text(
                    "".join(line for line in checksums.splitlines(keepends=True)
                            if not line.endswith(f"  {name}\n"))
                )
                with self.subTest(asset=name, case="missing"):
                    result = subprocess.run(
                        ["bash", str(INSTALLER), "--version", "0.5.0", "--dry-run"],
                        env=env, text=True, capture_output=True,
                    )
                    self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_release_version_is_consistent(self):
        self.assertEqual(tomllib.loads(PYPROJECT.read_text())["project"]["version"], "0.5.0")
        self.assertIn('__version__ = "0.5.0"', MAIN.read_text())
        lock = tomllib.loads((ROOT / "uv.lock").read_text())
        self.assertEqual(next(pkg["version"] for pkg in lock["package"] if pkg["name"] == "remla"), "0.5.0")

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
            wheel = Path(directory) / "remla-0.4.5-py3-none-any.whl"
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
        self.assertIn("/opt/remla/releases/0.4.5", result.stdout)
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
        self.assertIn("unittest discover -s tests -t .", content)
        self.assertIn("remla-*.tar.gz install.sh requirements.txt remla.service 49-remla.rules", content)

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

    def test_installer_grants_the_service_user_serial_and_camera_device_access(self):
        content = INSTALLER.read_text()

        self.assertIn('usermod --append --groups remlausers,gpio,i2c,dialout,video "$SERVICE_USER"', content)
        self.assertIn("SupplementaryGroups=gpio i2c remlausers video", SERVICE.read_text())

    def test_installer_exposes_os_camera_bindings_in_release_runtime(self):
        content = INSTALLER.read_text()
        self.assertIn("python3-picamera2", content)
        self.assertIn('python3 -m venv --system-site-packages "$release_directory/venv"', content)
        self.assertIn('"$release_directory/venv/bin/python" -c', content)
        self.assertNotIn('"$release_directory/venv/bin/remla" camera check', content)


class PackageBuildTests(unittest.TestCase):
    def test_built_wheel_contains_runtime_assets(self):
        version = tomllib.loads(PYPROJECT.read_text())["project"]["version"]
        wheels = list((ROOT / "dist").glob(f"remla-{version}-*.whl"))
        self.assertEqual(len(wheels), 1, "build the current version's wheel before running this test")

        with zipfile.ZipFile(wheels[0]) as wheel:
            names = set(wheel.namelist())

        self.assertIn("remla/setup/mediamtx.service", names)
        self.assertIn("remla/overlays/remla-camera-mux-4port.dtbo", names)
        self.assertIn("remla/camera_diagnostics.py", names)


if __name__ == "__main__":
    unittest.main()
