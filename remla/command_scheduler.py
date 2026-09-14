import asyncio


class CommandScheduler:
    def __init__(self, operation_registry, clock):
        self.operation_registry = operation_registry
        self.clock = clock
        self._lock_groups = {}

    async def execute(self, operation, command):
        if operation.lock_group is None:
            return await self._execute(operation, command)

        lock = self._lock_groups.setdefault(operation.lock_group, asyncio.Lock())
        async with lock:
            return await self._execute(operation, command)

    async def _execute(self, operation, command):
        self.operation_registry.start(operation.operation_id, timestamp=self.clock())
        try:
            result = await asyncio.wait_for(command(), timeout=operation.timeout_seconds)
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
