import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path


SCHEMA_VERSION = 1
REQUIRED_SNAPSHOT_FIELDS = {
    "schema_version",
    "lab_config",
    "saved_at",
    "lifecycle",
    "devices",
    "operations",
    "last_error",
}
LIFECYCLE_STATES = {"starting", "ready", "resetting", "stopping", "stopped", "faulted"}


class StateWriteError(Exception):
    pass


@dataclass
class StateLoadResult:
    snapshot: dict | None
    diagnostic: str | None
    message: str | None


@dataclass(frozen=True)
class LabConfigIdentity:
    name: str
    sha256: str

    @classmethod
    def from_content(cls, name: str, content: bytes) -> "LabConfigIdentity":
        return cls(name=name, sha256=sha256(content).hexdigest())

    @classmethod
    def from_file(cls, name: str, path: Path) -> "LabConfigIdentity":
        return cls.from_content(name, path.read_bytes())

    def to_dict(self) -> dict:
        return {"name": self.name, "sha256": self.sha256}


class RuntimeStateStore:
    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.Lock()

    def new_snapshot(
        self,
        lab_config_identity: LabConfigIdentity,
        lifecycle_state: str,
        device_states: dict,
    ) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "lab_config": lab_config_identity.to_dict(),
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "lifecycle": {"state": lifecycle_state, "fault": None},
            "devices": device_states,
            "operations": {"unfinished": []},
            "last_error": None,
        }

    def save(self, snapshot: dict) -> None:
        with self._write_lock:
            self._save(snapshot)

    def _save(self, snapshot: dict) -> None:
        if not self._is_valid_snapshot(snapshot):
            raise StateWriteError("invalid runtime state snapshot")

        temporary_path = None

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_name(
                f".{self.path.name}.{uuid.uuid4().hex}.tmp"
            )
            with temporary_path.open("w") as state_file:
                json.dump(snapshot, state_file, sort_keys=True)
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temporary_path, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except (OSError, TypeError, ValueError, OverflowError) as error:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise StateWriteError(str(error)) from error

    def load(self, expected_lab_config_identity: LabConfigIdentity) -> StateLoadResult:
        if not self.path.exists():
            return StateLoadResult(snapshot=None, diagnostic="missing", message=None)

        try:
            snapshot = json.loads(self.path.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return StateLoadResult(
                snapshot=None,
                diagnostic="corrupt",
                message=(
                    "Persisted runtime state could not be read and was left unchanged. "
                    "To resolve, inspect or explicitly archive/discard the state file before "
                    "starting a new state record."
                ),
            )

        if not self._is_valid_snapshot(snapshot):
            return StateLoadResult(
                snapshot=None,
                diagnostic="schema_mismatch",
                message=(
                    "Persisted runtime state is not compatible with this ReMLA version and "
                    "was left unchanged. To resolve, inspect or explicitly archive/discard "
                    "the state file before starting a new state record."
                ),
            )
        if snapshot["lab_config"] != expected_lab_config_identity.to_dict():
            stored_identity = snapshot["lab_config"]
            message = (
                f"Saved runtime state belongs to lab {stored_identity['name']} "
                f"with configuration hash {stored_identity['sha256']}. "
                f"The active lab is {expected_lab_config_identity.name} with configuration "
                f"hash {expected_lab_config_identity.sha256}. ReMLA will not use the "
                "saved state automatically. To resolve, restore the recorded lab "
                "configuration to inspect the state, or explicitly archive or discard "
                "the saved state after confirming it is no longer needed."
            )
            return StateLoadResult(
                snapshot=None,
                diagnostic="lab_mismatch",
                message=message,
            )
        return StateLoadResult(snapshot=snapshot, diagnostic=None, message=None)

    @staticmethod
    def _is_valid_snapshot(snapshot: object) -> bool:
        if not isinstance(snapshot, dict) or not REQUIRED_SNAPSHOT_FIELDS.issubset(snapshot):
            return False
        if type(snapshot["schema_version"]) is not int:
            return False
        if snapshot["schema_version"] != SCHEMA_VERSION:
            return False
        lab_config = snapshot["lab_config"]
        if (
            not isinstance(lab_config, dict)
            or not isinstance(lab_config.get("name"), str)
            or not isinstance(lab_config.get("sha256"), str)
            or len(lab_config["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in lab_config["sha256"])
        ):
            return False
        if not isinstance(snapshot["saved_at"], str):
            return False
        try:
            datetime.fromisoformat(snapshot["saved_at"])
        except ValueError:
            return False

        lifecycle = snapshot["lifecycle"]
        if (
            not isinstance(lifecycle, dict)
            or not isinstance(lifecycle.get("state"), str)
            or lifecycle["state"] not in LIFECYCLE_STATES
        ):
            return False
        if lifecycle.get("fault") is not None and not isinstance(lifecycle.get("fault"), dict):
            return False

        devices = snapshot["devices"]
        if not isinstance(devices, dict) or not all(
            isinstance(name, str) and isinstance(state, dict)
            for name, state in devices.items()
        ):
            return False

        operations = snapshot["operations"]
        if not isinstance(operations, dict) or not isinstance(
            operations.get("unfinished"), list
        ):
            return False
        return snapshot["last_error"] is None or isinstance(snapshot["last_error"], dict)
