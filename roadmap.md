# Roadmap

## Scope and confirmed decisions
- This is the implementation plan for reliable runtime state, controlled resets, shutdown, and command scheduling. No runtime behavior implementation has started.
- Initial deployments permit anonymous control from a trusted network. Keep origin, connection, rate, command-validation, and physical safety controls; do not add user authentication in this work.
- Production installation should ultimately use an unprivileged `remla` service account and a stable UV-managed runtime location. Provisioning remains a separate concern from runtime behavior.
- `UPDATE_PLAN.md` remains authoritative for the camera-cycle requirement. The camera work below must preserve: cycle only in `remla run`, exactly once per boot, and restart MediaMTX per channel.
- FIFO applies to waiting control users, not to every command. Commands in the same named lock group are serialized; commands without a lock group are permitted to run concurrently, subject to operation limits and hardware safety rules. There is no global command queue.
- After an owner disconnects, the next FIFO user may be promoted to a handoff-pending state only after outgoing work is terminal. They must choose reset or continue before normal command admission. An unanswered handoff request times out to reset.
- A timed-out operation must not trigger an automatic reset. It enters a faulted, operator-intervention state that admits no commands. A future local recovery command must invoke a device-specific safe-stop/recovery hook and may reopen admission only after the operation is terminal; its name and authorization are design work.

## Completed discovery
- [x] Built the repository knowledge graph in `graphify-out/`.
- [x] Completed a read-only architecture, packaging, protocol, and runtime-lifecycle assessment (2026-08-29).
- [x] Confirmed that current `clients` deque is an incomplete user-control queue and that configured `asyncio.Lock` instances provide per-lock-group command serialization.

## Current runtime defects to remove
- `Experiment.__init__` starts the IPC listener and owns an event loop, but does not initialize `jsonFile`, `socketPath`, `connection`, or `clientQueue` (`remla/labcontrol/Experiment.py`).
- `recallState()` and `getControllerStates()` dereference the missing `jsonFile`; state persistence is therefore non-functional.
- `handleConnection()` creates an unbounded task per active-client command. Its `finally` block promotes a waiting client and then synchronously resets every device, without queueing, locking, or reset completion before promotion.
- `onClientDisconnect()` is unused and references the missing `clientQueue`; it conflicts with the connection-finally implementation.
- `resetExperiment()` runs blocking hardware reset methods on the event-loop thread and can race a command already running in `ThreadPoolExecutor`.
- `runDeviceMethod()` rejects every device without a YAML lock mapping. Its lock groups retain useful command serialization, but they are not integrated with user ownership, operation tracking, disconnect cancellation, reset barriers, or lifecycle state.
- `main.run()` handles SIGINT/SIGTERM by deleting the PID file and calling `sys.exit`; it never asks `Experiment` to stop work, reset devices, close camera resources, close IPC, or shut down the executor.
- `Experiment` has a second, unused and broken signal/socket lifecycle: `setupSignalHandlers()` uses the wrong `signal` import; `setup()` uses `setTimeout`; the legacy AF_UNIX socket fields are unset.
- `stop()` stops the systemd service and may signal a foreground PID, but does not use one shared teardown contract.
- Controller imports create pigpio, GPIO, and VISA resources at module import time. Several controller `reset()` methods are no-ops, while `PiCamera2MultiCam.close()` has cleanup that runtime shutdown does not call.
- The IPC listener owns `/tmp/remla_cmd.sock` outside the main shutdown path and accepts only ad-hoc text notifications.
- `init()` can still duplicate the per-boot camera cycle; see `UPDATE_PLAN.md`.

## Target runtime contract

### Experiment lifecycle
- Valid lifecycle states: `starting`, `ready`, `resetting`, `stopping`, `stopped`, and `faulted`.
- Only the runtime coordinator changes lifecycle state. Devices, WebSocket handlers, IPC handlers, and signal handlers request transitions through it.
- Startup failure after any device is created enters `stopping`, executes the same teardown path, records a fault, and exits non-zero.
- Shutdown is idempotent. Concurrent triggers (`SIGINT`, `SIGTERM`, active-client disconnect, `remla stop`, startup failure) share one in-progress shutdown/reset operation and one final outcome.

### State model
- Track separately: experiment lifecycle, control ownership and waiting users, submitted/running operations, per-device observed state, per-device desired/safe state, and last error.
- Assign every accepted command an operation ID, submit timestamp, client/session ID, device, command, lock group, lifecycle timestamps, terminal status, and structured error when applicable.
- Publish a complete state snapshot to a newly connected client and publish deltas for ownership, waiting users, operation, device, reset, and fault changes.
- Persist a versioned snapshot containing lab-config identity, timestamp, device state, lifecycle/fault metadata, and unfinished-operation outcomes. Write atomically after terminal operations and after teardown.
- Do not automatically replay persisted hardware state at startup. Start in a safe state; expose persisted state for inspection/recovery only after an explicit recovery policy is designed.
- Treat absent, corrupt, old-schema, or lab-mismatched state files as recoverable diagnostic conditions, not startup crashes.

### Control ownership and command scheduling
- Keep a FIFO control-waiter list. Only one connected client owns command submission; waiting users receive ownership/status updates but cannot submit commands.
- Use a scheduler that serializes commands in each configured named lock group. Commands from the active user in different lock groups may run concurrently; the implementation may use explicit locks or FIFO group workers.
- Track every submitted operation and its optional lock group so an owner change, reset, timeout, or shutdown can identify both work waiting for a named group and work already running.
- Enforce a per-active-user outstanding-operation limit, per-command execution timeout, and one terminal response/event per operation ID. This is backpressure, not a global command queue.
- Reject commands when lifecycle is not `ready`, the sender is not the active owner, the sender exceeds its outstanding-operation limit, or required device metadata is invalid. A named lock group is optional; commands without one have no scheduler-imposed serialization.
- A client disconnect cancels that client's operations still waiting for a lock. A running command is handled by its device-specific stop/reset contract; cancelling an asyncio task alone is not considered a hardware stop.
- Reset is a lock barrier: stop accepting normal work, acquire all named lock groups in a deterministic order, cancel outgoing-client work that has not started, resolve or safely stop running work, reset devices, persist terminal state, then return to `ready` with no owner or a handoff-pending owner.
- On owner disconnect, do not admit a new owner's normal commands until all outgoing work is terminal and the promoted user chooses reset or continue. If they do not choose in time, reset. On reset failure, enter `faulted`; expose only status/diagnostic actions until an explicit recovery succeeds.
- On operation timeout, enter `faulted` and freeze all command admission without automatically resetting hardware. An operator-initiated, device-specific recovery must safely stop the operation and observe its terminal outcome before reopening admission.

### Reset and resource-release contract
- Support reset reasons: `owner_disconnect`, `operator_request`, `foreground_signal`, `service_stop`, `startup_failure`, and `fault_recovery`.
- Every controller must declare one of: safe reset implementation, close/release implementation, or an explicit no-hardware/no-reset classification. Eliminate silent `pass` resets for actuators and hardware clients.
- Build reset order from the configured device dependency graph: dependent devices stop/reset before their providers. Preserve this order for close/release.
- Ensure camera reset releases camera, encoder, output, allocator, and MediaMTX-related resources through the camera controller’s explicit cleanup path.
- Run blocking device operations only through the runtime executor; run reset operations under the same scheduler/barrier rules as commands.
- Define reset timeouts and failure collection per device. Continue remaining independent safety resets after one failure, then report a composite reset failure and enter `faulted`.

### Signal, service, and IPC behavior
- `remla run -f`: SIGINT and SIGTERM request coordinator shutdown; PID removal is the final step, not the signal action.
- systemd stop: SIGTERM follows the same shutdown path and gets a `TimeoutStopSec` larger than the bounded teardown duration.
- `remla stop`: requests systemd stop for service mode; foreground mode signals the tracked process and relies on its coordinator. Do not duplicate reset logic in the CLI.
- IPC listener lifecycle belongs to the coordinator. Create it after runtime initialization, close/unlink it during teardown, define permissions/owner, and make all IPC payloads versioned JSON when the control protocol migrates.
- Remove the unused legacy `Experiment.setup()`, `closeHandler()`, `exitHandler()`, and `setupSignalHandlers()` path unless a supported client still requires it; do not partially repair two competing lifecycle systems.

## Implementation sequence

### 1. Establish regression harness and lifecycle seams
- [ ] Add hardware-free fakes for controllers, executor-facing blocking operations, WebSocket clients, MediaMTX checks, IPC, and signals.
- [ ] Add focused standard-library tests before each behavior change; no GPIO, pigpio, camera, VISA, systemd, or network access is allowed in this suite.
- [ ] Move hardware resource acquisition out of `Controllers.py` import scope and inject/create resources only during runtime construction.
- [ ] Make `main.run()` own runtime construction and final shutdown; `Experiment` must not create global loops, sockets, threads, or signal handlers in its constructor.

**Exit criteria:** importing runtime modules on a non-Pi host succeeds; a fake runtime can start and stop without files, threads, sockets, tasks, or executor workers left behind.

### 2. Replace broken state persistence with the target state model
- [ ] Define the versioned persisted-state location through centralized settings, with a service-account-compatible ownership model.
- [ ] Replace `allStates`, `initializedStates`, `recallState()`, and `getControllerStates()` with explicit snapshot/load operations implementing the target schema and atomic writes.
- [ ] Add state publication to the transport boundary; retain a legacy text adapter until the JSON protocol migration is complete.
- [ ] Record command and reset failures without overwriting the last known device state.

**Tests:** clean start; valid round trip; corrupt file; schema mismatch; changed lab configuration; command success/failure state transitions; write failure.

### 3. Implement the user queue, tracked lock-group operations, and reset barrier
- [ ] Replace `handleConnection()` task creation, its `finally` reset, and `onClientDisconnect()` with one FIFO ownership manager. Preserve the existing per-lock-group command concurrency.
- [ ] Register/unregister every active-user operation and its lock group; make client promotion, waiting-user status, operation cancellation, reset start/completion, and owner loss observable state transitions.
- [ ] Convert the existing lock mapping into startup validation. Fail before serving if any command-capable device lacks explicit scheduling metadata, including an intentional no-lock-group declaration.
- [ ] Route camera-switch progress through operation IDs and state events rather than separate uncorrelated command strings.
- [ ] Add outstanding-operation limits, timeout, cancellation, and terminal-result handling without introducing a global command queue.
- [ ] Design the scheduler boundary: compare explicit lock ownership with FIFO workers per named lock group, while preserving concurrent execution for ungrouped commands.

**Tests:** FIFO user promotion into handoff-pending state; inactive-user rejection; same-lock serialization; independent-lock and ungrouped-command concurrency; outstanding-operation limit; active-user disconnect before lock acquisition; disconnect during execution; handoff continue/reset and automatic reset timeout; reset failure; command timeout freezes admission without automatic reset; camera progress correlation.

### 4. Implement unified shutdown and controller safety audit
- [ ] Introduce one coordinator teardown sequence: enter `stopping`; stop admission; cancel operations waiting for lock acquisition; resolve active work; reset/close in dependency order; persist state; close WebSocket server, IPC, sockets, executor, and hardware resources; remove PID; enter `stopped`.
- [ ] Route foreground signals, systemd termination, CLI stop, startup failure, and explicit reset through this sequence with their stated reset reason.
- [ ] Audit every controller reset at the locations reported above. Replace no-op actuator resets with safe outputs; classify sensor-only controllers explicitly; add close/release where reset is not sufficient.
- [ ] Integrate `PiCamera2MultiCam.close()` and any equivalent ArduCam cleanup into the controller contract.
- [ ] Remove direct `exit()`, `os._exit()`, and independent cleanup paths that bypass the coordinator.

**Tests:** Ctrl+C while idle; Ctrl+C during a blocking command; SIGTERM during reset; repeated signals; startup failure after partial device creation; reset exception aggregation; exactly-once PID/socket cleanup; executor shutdown.

### 5. Migrate control and IPC messages to JSON
- [ ] Specify and document versioned JSON messages for `state.snapshot`, `state.changed`, `operation.queued`, `operation.started`, `operation.completed`, `operation.failed`, `reset.started`, `reset.completed`, and `fault`.
- [ ] Include operation ID and lifecycle state in every result, error, and camera event.
- [ ] Support legacy slash-delimited requests/responses per connection during the agreed compatibility window; never mix legacy and JSON frames on one connection.
- [ ] Update the maintained browser WebSocket client to render control-owner/waiting-user status, current operations, reset/fault status, and reconnect state. Remove duplicate/stale socket client assets, including the tracked conflict-marker file.

**Tests:** JSON schema/contract fixtures; legacy adapter fixtures; malformed input; client reconnect snapshot; operation/event correlation; browser-client unit coverage where practical.

### 6. Apply camera-cycle plan and deployment boundaries
- [ ] Complete `UPDATE_PLAN.md`: remove cycling from `init()`, keep the boot guard only in `run()`, and update stale comments/documentation.
- [ ] Verify that cycle/reset/shutdown ordering does not restart or interrupt MediaMTX unexpectedly.
- [ ] Define runtime service permissions so normal users operate the website without `sudo`; retain privileged actions only in installation/provisioning.
- [ ] After runtime behavior is covered, migrate packaging from Poetry to PEP 621 + UV and define the installer/service layout separately from application code.

**Hardware verification:** reboot and confirm one camera cycle; disconnect an active browser during motor/camera use; Ctrl+C from `remla run -f`; `systemctl stop remla`; camera cleanup/restart; physical actuator safe state; reconnect after reset; service restart after fault.

## Deferred work
- [ ] Add deterministic multi-lock acquisition only if a future command must reserve more than one lock group; preserve lock ordering and dedicated concurrency tests.
- [ ] Add explicit operator-requested persisted-state recovery only after controllers declare which state fields are safe to restore.
- [ ] Add authentication only if deployment boundaries change from the current trusted-network model.
