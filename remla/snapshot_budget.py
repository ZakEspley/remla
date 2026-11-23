"""Durable, fail-closed interruption budget for snapshot requests."""

import fcntl
import json
import math
import os
import tempfile
import time
from pathlib import Path


class SnapshotBudgetError(Exception):
    pass


class SnapshotBudget:
    def __init__(self, path: Path, clock=time.time, cooldown=10, max_per_hour=100):
        self.path = path
        self.clock = clock
        self.cooldown = cooldown
        self.max_per_hour = max_per_hour

    def reserve(self) -> None:
        """Charge a capture attempt before opening the camera, even if it fails."""
        try:
            lock_fd = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(lock_fd, "r+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                now = self.clock()
                if self.path.exists():
                    if self.path.stat().st_size > 4096:
                        raise SnapshotBudgetError("Invalid snapshot budget")
                    with self.path.open("r") as state_file:
                        state = json.load(state_file)
                    attempts = state["attempts"]
                    if (set(state) != {"attempts"} or not isinstance(attempts, list)
                            or len(attempts) > self.max_per_hour or any(
                                type(value) not in (float, int) or not math.isfinite(value) for value in attempts
                            ) or attempts != sorted(attempts)):
                        raise SnapshotBudgetError("Invalid snapshot budget")
                else:
                    attempts = []
                if attempts and now < attempts[-1]:
                    raise SnapshotBudgetError("Snapshot clock moved backwards")
                attempts = [value for value in attempts if now - value < 3600]
                if attempts and now - attempts[-1] < self.cooldown:
                    raise SnapshotBudgetError("Snapshot cooldown is active")
                if len(attempts) >= self.max_per_hour:
                    raise SnapshotBudgetError("Snapshot interruption budget is exhausted")
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, prefix=".snapshot-budget-",
                                                     delete=False) as output:
                        temporary = Path(output.name)
                        os.fchmod(output.fileno(), 0o600)
                        json.dump({"attempts": attempts + [now]}, output)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, self.path)
                    dir_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise SnapshotBudgetError("Cannot verify snapshot interruption budget") from error
