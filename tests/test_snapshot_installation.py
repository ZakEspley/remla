import subprocess
import stat
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/install-snapshot.sh"


class SnapshotInstallationTests(unittest.TestCase):
    def test_installer_is_executable_as_documented(self):
        self.assertTrue(SCRIPT.stat().st_mode & stat.S_IXUSR)

    def test_provisioning_is_explicit_and_dry_run_has_no_side_effects(self):
        result = subprocess.run(["bash", str(SCRIPT), "--dry-run"], capture_output=True, text=True, check=True)
        self.assertIn("Would provision", result.stdout)
        self.assertIn("would not start/stop", result.stdout)

    def test_broker_units_and_policy_are_opt_in_assets(self):
        installer = SCRIPT.read_text()
        for asset in ("remla-snapshot-helper", "remla-snapshot-capture.service",
                      "remla-snapshot-recovery.service", "remla-snapshot-recovery.timer",
                      "remla-snapshot-sudoers", "remla-snapshot-tmpfiles.conf"):
            with self.subTest(asset=asset):
                self.assertTrue((ROOT / "packaging" / asset).is_file())
                self.assertIn(asset, installer)
        self.assertIn("visudo -cf", installer)
        self.assertIn("systemd-analyze verify", installer)
        self.assertIn("transaction.json", installer)

    def test_installer_holds_broker_lock_while_replacing_recovery_assets(self):
        installer = SCRIPT.read_text()
        self.assertIn('flock -n "$broker_lock"', installer)
        self.assertLess(installer.index('flock -n "$broker_lock"'),
                        installer.index('[[ ! -e "$STATE/transaction.json" ]]'))
        self.assertLess(installer.index('flock -n "$broker_lock"'),
                        installer.index('install -o root -g root -m 0755 "$ASSETS/remla-snapshot-helper"'))
        self.assertLess(installer.index('install -o root -g root -m 0755 "$ASSETS/remla-snapshot-helper"'),
                        installer.index("printf 'coordinated\\n'"))
        self.assertNotIn('flock -u "$broker_lock"', installer)


if __name__ == "__main__":
    unittest.main()
