import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from remla.runtime_state import LabConfigIdentity, RuntimeStateStore, StateWriteError


class RuntimeStateStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "runtime-state.json"
        self.store = RuntimeStateStore(self.path)

    def identity(self, content=b"lab-a"):
        return LabConfigIdentity.from_content("lab-a.yml", content)

    def test_missing_state_is_a_recoverable_diagnostic(self):
        result = self.store.load(self.identity())

        self.assertIsNone(result.snapshot)
        self.assertEqual(result.diagnostic, "missing")

    def test_valid_state_round_trips(self):
        snapshot = self.store.new_snapshot(
            lab_config_identity=self.identity(),
            lifecycle_state="ready",
            device_states={"camera": {"observed": {"enabled": True}}},
        )

        self.store.save(snapshot)
        result = self.store.load(self.identity())

        self.assertEqual(result.snapshot, snapshot)
        self.assertIsNone(result.diagnostic)

    def test_corrupt_state_is_a_recoverable_diagnostic(self):
        self.path.write_text("not json")

        result = self.store.load(self.identity())

        self.assertIsNone(result.snapshot)
        self.assertEqual(result.diagnostic, "corrupt")
        self.assertIn("could not be read", result.message)

    def test_invalid_utf8_state_is_a_recoverable_diagnostic(self):
        self.path.write_bytes(b"\xff")

        result = self.store.load(self.identity())

        self.assertIsNone(result.snapshot)
        self.assertEqual(result.diagnostic, "corrupt")

    def test_unknown_schema_is_a_recoverable_diagnostic(self):
        self.path.write_text(json.dumps({"schema_version": 99, "lab_config": {}}))

        result = self.store.load(self.identity())

        self.assertIsNone(result.snapshot)
        self.assertEqual(result.diagnostic, "schema_mismatch")

    def test_incomplete_current_schema_is_a_recoverable_diagnostic(self):
        self.path.write_text(json.dumps({"schema_version": 1, "lab_config": {}}))

        result = self.store.load(self.identity())

        self.assertIsNone(result.snapshot)
        self.assertEqual(result.diagnostic, "schema_mismatch")

    def test_malformed_current_schema_is_a_recoverable_diagnostic(self):
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": True,
                    "lab_config": self.identity().to_dict(),
                    "saved_at": "now",
                    "lifecycle": {"state": "ready", "fault": None},
                    "devices": {},
                    "operations": {"unfinished": "not-a-list"},
                    "last_error": None,
                }
            )
        )

        result = self.store.load(self.identity())

        self.assertIsNone(result.snapshot)
        self.assertEqual(result.diagnostic, "schema_mismatch")

    def test_unhashable_lifecycle_state_is_a_recoverable_diagnostic(self):
        snapshot = self.store.new_snapshot(self.identity(), "ready", {})
        snapshot["lifecycle"]["state"] = []
        self.path.write_text(json.dumps(snapshot))

        result = self.store.load(self.identity())

        self.assertIsNone(result.snapshot)
        self.assertEqual(result.diagnostic, "schema_mismatch")
        self.assertIn("not compatible", result.message)

    def test_mismatched_lab_configuration_is_a_recoverable_diagnostic(self):
        snapshot = self.store.new_snapshot(self.identity(), "ready", {})
        self.store.save(snapshot)

        result = self.store.load(LabConfigIdentity.from_content("lab-b.yml", b"lab-b"))

        self.assertIsNone(result.snapshot)
        self.assertEqual(result.diagnostic, "lab_mismatch")
        self.assertIn("will not use", result.message)
        self.assertIn("To resolve", result.message)

    def test_changed_lab_content_has_an_actionable_mismatch_message(self):
        snapshot = self.store.new_snapshot(self.identity(b"original"), "ready", {})
        self.store.save(snapshot)

        result = self.store.load(self.identity(b"changed"))

        self.assertEqual(result.diagnostic, "lab_mismatch")
        self.assertIn("lab-a.yml", result.message)
        self.assertIn("will not use the saved state automatically", result.message)
        self.assertIn("archive or discard", result.message)

    def test_write_failure_raises_a_specific_error(self):
        snapshot = self.store.new_snapshot(self.identity(), "ready", {})

        with mock.patch("remla.runtime_state.os.replace", side_effect=OSError("disk")):
            with self.assertRaisesRegex(StateWriteError, "disk"):
                self.store.save(snapshot)

    def test_directory_creation_failure_raises_a_specific_error(self):
        snapshot = self.store.new_snapshot(self.identity(), "ready", {})

        with mock.patch.object(Path, "mkdir", side_effect=OSError("directory")):
            with self.assertRaisesRegex(StateWriteError, "directory"):
                self.store.save(snapshot)

    def test_serialization_failure_raises_a_specific_error_and_cleans_up(self):
        snapshot = self.store.new_snapshot(self.identity(), "ready", {"device": object()})

        with self.assertRaises(StateWriteError):
            self.store.save(snapshot)

        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_save_fsyncs_the_state_file_and_parent_directory(self):
        snapshot = self.store.new_snapshot(self.identity(), "ready", {})

        with mock.patch("remla.runtime_state.os.fsync", wraps=os.fsync) as fsync:
            self.store.save(snapshot)

        self.assertEqual(fsync.call_count, 2)

    def test_lab_identity_changes_when_configuration_content_changes(self):
        first = LabConfigIdentity.from_content("lab-a.yml", b"first")
        second = LabConfigIdentity.from_content("lab-a.yml", b"second")

        self.assertEqual(first.name, second.name)
        self.assertNotEqual(first.sha256, second.sha256)


if __name__ == "__main__":
    unittest.main()
