import asyncio
from contextlib import asynccontextmanager

from remla.runtime_operations import OperationTransitionError


class CommandScheduler:
    def __init__(self, operation_registry, clock):
        self.operation_registry = operation_registry
        self.clock = clock
        self._lock_groups = {}
        self._running_commands = {}

    def add_lock_group(self, name):
        self._lock_groups.setdefault(name, asyncio.Lock())

    async def execute(self, operation, command):
        lock = None
        if operation.lock_group is not None:
            lock = self._lock_groups.setdefault(operation.lock_group, asyncio.Lock())
            await lock.acquire()

        try:
            return await self._execute(operation, command, lock)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            self._release_lock_when_command_finishes(lock, operation.operation_id)
            lock = None
            raise
        finally:
            if lock is not None:
                lock.release()

    async def _execute(self, operation, command, lock):
        try:
            self.operation_registry.start(operation.operation_id, timestamp=self.clock())
        except OperationTransitionError as error:
            if operation.status == "timed_out":
                raise asyncio.TimeoutError() from error
            raise
        command_task = asyncio.create_task(command())
        self._running_commands[operation.operation_id] = (operation, command_task)
        command_task.add_done_callback(
            lambda task: self._running_commands.pop(operation.operation_id, None)
        )

        try:
            result = await asyncio.wait_for(
                asyncio.shield(command_task), timeout=operation.timeout_seconds
            )
        except asyncio.TimeoutError:
            self.operation_registry.timeout(operation.operation_id, timestamp=self.clock())
            raise
        except Exception as error:
            self.operation_registry.fail(
                operation.operation_id,
                error={"code": type(error).__name__, "message": str(error)},
                timestamp=self.clock(),
            )
            raise

        self.operation_registry.complete(
            operation.operation_id,
            result=result,
            timestamp=self.clock(),
        )
        return result

    def _release_lock_when_command_finishes(self, lock, operation_id):
        if lock is None:
            return

        running_command = self._running_commands.get(operation_id)
        if running_command is None:
            lock.release()
            return
        command_task = running_command[1]

        def release_lock(task):
            try:
                task.result()
            except (asyncio.CancelledError, Exception):
                pass
            lock.release()

        command_task.add_done_callback(release_lock)

    async def wait_for_owner(self, owner_id):
        tasks = [
            task
            for operation, task in self._running_commands.values()
            if operation.owner_id == owner_id
        ]
        if tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tasks), return_exceptions=True)

    async def wait_for_idle(self):
        tasks = [task for _, task in self._running_commands.values()]
        if tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tasks), return_exceptions=True)

    def has_running_commands(self):
        return bool(self._running_commands)

    @asynccontextmanager
    async def reset_barrier(self):
        locks = [self._lock_groups[name] for name in sorted(self._lock_groups)]
        for lock in locks:
            await lock.acquire()
        try:
            yield
        finally:
            for lock in reversed(locks):
                lock.release()
