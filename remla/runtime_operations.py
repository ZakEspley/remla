import math
import uuid
from dataclasses import dataclass


class OutstandingOperationLimit(Exception):
    pass


class OperationTransitionError(Exception):
    pass


@dataclass
class Operation:
    operation_id: str
    owner_id: str
    device: str
    command: str
    lock_group: str | None
    submitted_at: float
    timeout_seconds: float
    deadline: float
    status: str = "queued"
    started_at: float | None = None
    finished_at: float | None = None
    result: dict | None = None
    error: dict | None = None

    def to_dict(self) -> dict:
        return {
            "operation_id": self.operation_id,
            "owner_id": self.owner_id,
            "device": self.device,
            "command": self.command,
            "lock_group": self.lock_group,
            "submitted_at": self.submitted_at,
            "timeout_seconds": self.timeout_seconds,
            "deadline": self.deadline,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
        }


class OwnershipManager:
    def __init__(self):
        self.active_owner = None
        self.waiting_users = []
        self.handoff_user = None
        self.handoff_state = "none"
        self._handoff_connected = False

    def connect(self, user_id: str) -> None:
        if user_id in (self.active_owner, self.handoff_user) or user_id in self.waiting_users:
            return
        if self.active_owner is None and self.handoff_user is None:
            self.active_owner = user_id
            self.handoff_state = "active"
            return
        self.waiting_users.append(user_id)

    def enqueue(self, user_id: str) -> None:
        if user_id not in (self.active_owner, self.handoff_user) and user_id not in self.waiting_users:
            self.waiting_users.append(user_id)

    def promote_waiting_user(self) -> None:
        if self.active_owner is None and self.handoff_user is None:
            self._promote_next_user()

    def disconnect(self, user_id: str) -> None:
        if user_id in self.waiting_users:
            self.waiting_users.remove(user_id)
            return
        if user_id == self.handoff_user:
            if self.handoff_state in {"resetting", "faulted"}:
                self._handoff_connected = False
                return
            self.handoff_user = None
            self.handoff_state = "none"
            self._promote_next_user()
            return
        if user_id != self.active_owner:
            return

        self.active_owner = None
        self.handoff_state = "none"
        self._promote_next_user()

    def choose_handoff(self, user_id: str, choice: str) -> None:
        if user_id != self.handoff_user or self.handoff_state != "pending":
            raise OperationTransitionError("user does not have a pending handoff")
        if choice == "continue":
            self.active_owner = user_id
            self.handoff_user = None
            self.handoff_state = "active"
            return
        if choice == "reset":
            self.handoff_state = "resetting"
            return
        raise ValueError("handoff choice must be 'continue' or 'reset'")

    def complete_reset(self, success: bool) -> None:
        if self.handoff_state != "resetting":
            raise OperationTransitionError("no reset is pending")
        if success:
            if self._handoff_connected:
                self.active_owner = self.handoff_user
                self.handoff_user = None
                self.handoff_state = "active"
            else:
                self.handoff_user = None
                self.handoff_state = "none"
                self._promote_next_user()
            return
        self.handoff_state = "faulted"

    def can_submit(self, user_id: str) -> bool:
        return self.handoff_state == "active" and user_id == self.active_owner

    def _promote_next_user(self) -> None:
        if not self.waiting_users:
            return
        self.handoff_user = self.waiting_users.pop(0)
        self.handoff_state = "pending"
        self._handoff_connected = True


class OperationRegistry:
    def __init__(self, max_outstanding_per_owner: int, clock):
        if (
            type(max_outstanding_per_owner) is not int
            or max_outstanding_per_owner <= 0
        ):
            raise ValueError("outstanding operation limit must be a positive integer")
        self.max_outstanding_per_owner = max_outstanding_per_owner
        self.clock = clock
        self.operations = {}

    def submit(
        self,
        owner_id: str,
        device: str,
        command: str,
        lock_group: str | None,
        timeout_seconds: float,
    ) -> Operation:
        if not isinstance(timeout_seconds, (int, float)) or not math.isfinite(
            timeout_seconds
        ) or timeout_seconds <= 0:
            raise ValueError("operation timeout must be a finite positive number")
        if self._outstanding_count(owner_id) >= self.max_outstanding_per_owner:
            raise OutstandingOperationLimit("owner has too many outstanding operations")

        submitted_at = self.clock()
        operation = Operation(
            operation_id=str(uuid.uuid4()),
            owner_id=owner_id,
            device=device,
            command=command,
            lock_group=lock_group,
            submitted_at=submitted_at,
            timeout_seconds=timeout_seconds,
            deadline=submitted_at + timeout_seconds,
        )
        self.operations[operation.operation_id] = operation
        return operation

    def start(self, operation_id: str, timestamp: float) -> Operation:
        operation = self._get_queued(operation_id)
        if timestamp >= operation.deadline:
            self.timeout(operation_id, timestamp)
            raise OperationTransitionError("operation timed out before it started")
        operation.status = "running"
        operation.started_at = timestamp
        return operation

    def complete(self, operation_id: str, result: dict, timestamp: float) -> Operation:
        operation = self._get_nonterminal(operation_id)
        operation.status = "completed"
        operation.finished_at = timestamp
        operation.result = result
        return operation

    def fail(self, operation_id: str, error: dict, timestamp: float) -> Operation:
        operation = self._get_nonterminal(operation_id)
        operation.status = "failed"
        operation.finished_at = timestamp
        operation.error = error
        return operation

    def timeout(self, operation_id: str, timestamp: float) -> Operation:
        operation = self._get_nonterminal(operation_id)
        operation.status = "timed_out"
        operation.finished_at = timestamp
        operation.error = {"code": "timeout"}
        return operation

    def cancel_waiting_for_owner(self, owner_id: str, timestamp: float) -> list[str]:
        return self._cancel_waiting(timestamp, lambda operation: operation.owner_id == owner_id)

    def cancel_all_waiting(self, timestamp: float) -> list[str]:
        return self._cancel_waiting(timestamp, lambda operation: True)

    def _cancel_waiting(self, timestamp: float, predicate) -> list[str]:
        cancelled = []
        for operation in self.operations.values():
            if predicate(operation) and operation.status == "queued":
                operation.status = "cancelled"
                operation.finished_at = timestamp
                cancelled.append(operation.operation_id)
        return cancelled

    def unfinished_snapshot(self) -> list[dict]:
        return [
            operation.to_dict()
            for operation in self.operations.values()
            if operation.status in {"cancelled", "timed_out"}
        ]

    def _outstanding_count(self, owner_id: str) -> int:
        return sum(
            operation.owner_id == owner_id
            and operation.status in {"queued", "running"}
            for operation in self.operations.values()
        )

    def _get_queued(self, operation_id: str) -> Operation:
        operation = self.operations[operation_id]
        if operation.status != "queued":
            raise OperationTransitionError("operation is not queued")
        return operation

    def _get_nonterminal(self, operation_id: str) -> Operation:
        operation = self.operations[operation_id]
        if operation.status not in {"queued", "running"}:
            raise OperationTransitionError("operation is already terminal")
        return operation
