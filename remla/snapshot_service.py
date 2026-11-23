"""Owner-checked, single-flight calls to the narrowly privileged snapshot helper."""

import asyncio
import json
import subprocess

from remla.snapshot_budget import SnapshotBudget
from remla.settings import snapshotBudgetPath


HELPER = "/usr/local/libexec/remla-snapshot-helper"


class SnapshotBusy(Exception):
    pass


class SnapshotNotOwner(Exception):
    pass


class SnapshotUnavailable(Exception):
    pass


def call_snapshot_helper(config) -> bytes:
    try:
        result = subprocess.run(
            ["/usr/bin/sudo", "-n", HELPER],
            input=json.dumps({"width": config.width, "height": config.height}).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SnapshotUnavailable("Snapshot helper did not complete") from error
    if result.returncode != 0:
        raise SnapshotUnavailable("Snapshot helper refused or failed capture")
    if not result.stdout.startswith(b"\x89PNG\r\n\x1a\n") or len(result.stdout) > 25_000_000:
        raise SnapshotUnavailable("Snapshot helper returned an invalid image")
    return result.stdout


class SnapshotService:
    def __init__(self, budget=None, capture=None):
        self.budget = budget or SnapshotBudget(snapshotBudgetPath)
        self.capture = capture or call_snapshot_helper
        self._lock = asyncio.Lock()

    async def capture_async(self, config):
        return await asyncio.to_thread(self.capture, config)

    async def capture_png(self, config, is_owner) -> bytes:
        if self._lock.locked():
            raise SnapshotBusy("A snapshot is already in progress")
        async with self._lock:
            if not is_owner():
                raise SnapshotNotOwner()
            self.budget.reserve()
            worker = asyncio.create_task(self.capture_async(config))
            try:
                image = await asyncio.shield(worker)
            except asyncio.CancelledError:
                try:
                    await worker  # Do not release single-flight until the worker has terminated.
                except Exception:
                    pass
                raise
            if not is_owner():
                raise SnapshotNotOwner()
            return image
