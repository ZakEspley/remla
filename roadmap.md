# Roadmap

## Scope and confirmed decisions
- This is the implementation plan for reliable runtime state, controlled resets, shutdown, and command scheduling. Versioned state diagnostics, operation models, scheduler fencing, FIFO handoff, and initial coordinator teardown are implemented; controller audit, state publication, recovery, and full shutdown coverage remain.
- Initial deployments permit anonymous control from a trusted network. Keep origin, connection, rate, command-validation, and physical safety controls; do not add user authentication in this work.
- Production installation uses an unprivileged `remla` service account and versioned `/opt/remla/releases` runtimes. `scripts/install.sh` is the Pi-only provisioning boundary; it installs verified GitHub-release assets, initializes the lab as part of the one privileged run, and exposes normal operator commands without `sudo`.
- `UPDATE_PLAN.md` remains authoritative for the camera-cycle requirement. The camera work below must preserve: cycle only in `remla run`, exactly once per boot, and restart MediaMTX per channel.
- FIFO applies to waiting control users, not to every command. Every device belongs to exactly one named lock group; commands in the same group are serialized and commands in different groups may run concurrently. There is no global command queue.
- After an owner disconnects, the next FIFO user may be promoted to a handoff-pending state only after outgoing work is terminal. They must choose reset or continue before normal command admission. An unanswered handoff request times out to reset.
- A timed-out operation must not trigger an automatic reset. It enters a faulted, operator-intervention state that admits no commands. A future local recovery command must invoke a device-specific safe-stop/recovery hook and may reopen admission only after the operation is terminal; its name and authorization are design work.
- `reset()` returns a device to its configured baseline and may move it. `safe_stop()` must be idempotent and must not initiate baseline movement; it is required for every controller, including an explicit no-op for sensor-only controllers. Graceful shutdown drains work, then resets and safe-stops; fault shutdown safe-stops without reset.

## Completed discovery
- [x] Built the repository knowledge graph in `graphify-out/`.
- [x] Completed a read-only architecture, packaging, protocol, and runtime-lifecycle assessment (2026-08-29).
- [x] Defined JSON protocol version 1 with opt-in WebSocket subprotocol negotiation, correlated command results, and named events in `docs/protocol.md`.
- [x] Added opt-in `remla-json-v1` WebSocket subprotocol framing while preserving legacy WebSocket clients.
- [x] Added loopback WebSocket compatibility coverage for legacy, JSON, and unsupported subprotocol clients.
- [x] Added provider-routed binary power commands for configured controllers; configure consumers with YAML `power.provider` and `power.outlet`.
- [x] Added `PowerConsumer` for standalone provider-backed targets such as diffrac2's Laser and Screen.
- [x] Switched diffrac2 temporarily to the pinned development source at `/opt/remla/dev/remla-80b49b1`; startup recognized Laser and Screen and local HTTP returned 200. Roll back by removing `/etc/systemd/system/remla.service.d/dev-source.conf`, reloading systemd, and restarting `remla.service`.
- [x] Operator validated diffrac2 Laser and Screen routed `power_on` and `power_off` commands against the live development service.
- [x] Publish opt-in JSON `state.snapshot` to every connection and authoritative `state.changed` events after successful state-changing commands, reset, fault recovery, and ownership handoff. Include a monotonic state revision so clients can detect gaps and resynchronize without relying on optimistic UI state.
- [x] Publish anonymous JSON ownership/queue presence events on connect, disconnect, queue changes, and promotion. Expose queue counts and the recipient's own position, never client identities.

### Current implementation order

1. [x] Restore the in-progress JSON state-event branch to a fully tested baseline before layering further behavior.
2. [x] Make `PDUOutlet` refresh outlet state from the provider for `get_power_state()` and `power_toggle`; return a safe command error when state cannot be read.
3. [x] Replace PDU credentials in lab YAML with `${secret:name}` references backed by root-owned `/etc/remla/secrets/` files; validate missing-secret failures and provide root-only `remla secrets` management commands. diffrac2 migrated `asdipdu-password`; credential rotation follows separately.
4. [x] Implement JSON state revisions, initial snapshots, post-success state changes, and snapshot publication after reset, recovery, and handoff. Do not expose secrets, raw configuration, operation owners, or internal paths.
5. [x] Implement anonymous JSON queue-presence broadcasts with recipient-specific position, queue count, and active-owner presence on connect, disconnect, promotion, and handoff changes.
6. [x] Run hardware-free regression tests, perform loopback and Pi development-service smoke tests without unsolicited hardware commands, and document deployment/rollback. Frontend adoption and release packaging remain separate follow-up work.
- [x] Verified diffrac2's development service loads the named secret store and `sudo python -m remla.main secrets list` reveals only `asdipdu-password`, never its value.
- [x] Bound PDU outlet commands to one request without inherited status follow-ups and removed duplicate `PowerConsumer` provider resets; await lockout expiry before live deployment validation.
- [x] Operator validated explicit Laser and Screen on/off commands against diffrac2's reduced-request development service after the PDU lockout cleared.
- [x] Operator validated one page refresh restores control without PDU lockout, and legacy Laser/Screen UI controls continue to work on diffrac2's reduced-request development service.
- [x] Removed departed owners from ownership before draining their work; drain failures now fault without leaving a ghost active owner and notify any pending handoff user.
- [x] Queue connections arriving during departed-work draining and promote them only after reset/handoff readiness, preventing new active ownership during unsafe teardown.
- [ ] Replace legacy `dlipower` HTML/CGI control with an internal DLI REST client using HTTP Digest authentication. Read `physical_state` for toggle, use zero-based REST outlet indexes, and reset all outlets through one REST all-off request. Mocked HTTP tests cover the client; confirm the PDU REST setting before enabling it on diffrac2. Later use a scoped non-admin PDU API account for outlets 5 and 6.
- [x] Ran the diffrac2 development checkout's loopback protocol tests with the installed release Python environment; no hardware commands ran and the production service remained active.
- [x] Confirmed that current `clients` deque is an incomplete user-control queue and that configured `asyncio.Lock` instances provide per-lock-group command serialization.

## Current runtime defects to remove
- `handleConnection()` tracks each active-client command task. On owner loss it removes ownership before draining scheduler-tracked work, queues arrivals during draining, and promotes the next FIFO user into the timed handoff state; JSON lifecycle and ownership events are published, while legacy clients retain text framing.
- `resetExperiment()` remains a blocking legacy helper; use `Experiment.shutdown()` or handoff reset so scheduler fencing applies.
- `runDeviceMethod()` tracks every device command and applies required lock-group serialization. Handoff resets and shutdown cancel queued operations, drain scheduler work, and acquire every configured scheduler lock; timeout/reset faults block admission and publish JSON state changes for negotiated clients.
- After runtime initialization, foreground SIGINT/SIGTERM request coordinator shutdown. Foreground startup failure invokes coordinator teardown before PID removal; service/CLI stop still use separate paths.
- `stop()` stops the systemd service and may signal a foreground PID, but does not use one shared teardown contract.
- Every controller now explicitly implements abstract `safe_stop()`. DC/stepper/continuous motors, servos, GPIO outputs, PWM, multiplexers, plugs/PDUs, and cameras have output-specific behavior; measurement and switch-only controllers explicitly declare no physical stop. Hardware validation of the resulting safe states remains required.
- The IPC listener is closed and unlinked by coordinator shutdown but still accepts only ad-hoc text notifications.
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
- Track every submitted operation and its required lock group so an owner change, reset, timeout, or shutdown can identify both work waiting for a named group and work already running.
- Enforce a per-active-user outstanding-operation limit, per-command execution timeout, and one terminal response/event per operation ID. This is backpressure, not a global command queue.
- Reject commands when lifecycle is not `ready`, the sender is not the active owner, the sender exceeds its outstanding-operation limit, or device lock-group metadata is invalid.
- [x] An active-owner disconnect cancels that client's operations still waiting for a lock and drains running work. A waiting user receives the reset-or-continue handoff without hardware changes; an empty ownership queue, including after a pending handoff disconnects, triggers a full reset. A running command is handled by its device-specific stop/reset contract; cancelling an asyncio task alone is not considered a hardware stop.
- Reset is a lock barrier: stop accepting normal work, acquire all named lock groups in a deterministic order, cancel outgoing-client work that has not started, resolve or safely stop running work, reset devices, persist terminal state, then return to `ready` with no owner or a handoff-pending owner.
- On owner disconnect, do not admit a new owner's normal commands until all outgoing work is terminal and the promoted user chooses reset or continue. If they do not choose in time, reset. On reset failure, enter `faulted`; expose only status/diagnostic actions until an explicit recovery succeeds.
- On operation timeout, enter `faulted` and freeze all command admission without automatically resetting hardware. An operator-initiated, device-specific recovery must safely stop the operation and observe its terminal outcome before reopening admission.

### Reset and resource-release contract
- Support reset reasons: `owner_disconnect`, `operator_request`, `foreground_signal`, `service_stop`, `startup_failure`, and `fault_recovery`.
- Every controller must declare one of: safe reset implementation, close/release implementation, or an explicit no-hardware/no-reset classification. Eliminate silent `pass` resets for actuators and hardware clients.
- Define a per-lab baseline schema for homing and device-specific reset targets; `docs/reset-baseline.md` records the current controller-defined defaults, while motor position remains process-tracked from YAML `initialPosition`.
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
- [x] Move pigpio, GPIO, and VISA resource acquisition out of `Controllers.py` import scope. `main.run()` initializes them explicitly before foreground device construction, and `tests.test_runtime_imports` covers non-Pi imports and fake resource creation.
- [x] Replace the root `boottime` smoke script with `tests.test_boot_status`, which verifies the camera-cycle boot marker using temporary files and a mocked boot timestamp.
- [x] Make `main.run()` explicitly initialize `Experiment` runtime resources. `Experiment.__init__` creates no executor, event loop, IPC socket, thread, logging file, or signal handler; initialization is idempotent, serializes competing calls, and rolls back failed IPC startup.
- [ ] `Experiment.shutdown()` now drains work, resets devices, closes WebSocket/IPC resources, and shuts down the executor idempotently. Foreground startup failure and final event-loop closure use this contract; route CLI stop and service-mode shutdown through it.

**Exit criteria:** importing runtime modules on a non-Pi host succeeds; a fake runtime can start and stop without files, threads, sockets, tasks, or executor workers left behind.

### 2. Replace broken state persistence with the target state model
- [x] Define `runtimeStatePath` in centralized settings and add the versioned, atomic `RuntimeStateStore`. Snapshots identify the lab by name and configuration hash; mismatch diagnostics explain that state is preserved and requires explicit configuration restoration or archive/discard before it can be replaced.
- [x] Load persisted state for diagnostics during foreground startup and record an initial observed device snapshot when it is safe to write. No persisted state is replayed to hardware.
- [ ] Replace `allStates`, `initializedStates`, `recallState()`, and `getControllerStates()` with explicit snapshot/load operations implementing the target schema and atomic writes.
- [ ] Add state publication to the transport boundary; retain a legacy text adapter until the JSON protocol migration is complete.
- [ ] Record command and reset failures without overwriting the last known device state.

**Tests:** clean start; valid round trip; corrupt file; schema mismatch; changed lab configuration; command success/failure state transitions; write failure.

### 3. Implement the user queue, tracked lock-group operations, and reset barrier
- [x] Add hardware-free FIFO ownership and operation lifecycle models. They track handoff-pending/resetting ownership, operation IDs, lock groups, outstanding limits, and terminal outcomes.
- [x] Add a hardware-free scheduler that serializes async commands by named lock group while allowing commands in different groups to run concurrently. `Experiment.runDeviceMethod()` now submits each accepted device command to this scheduler and records its terminal outcome.
- [ ] Replace `handleConnection()` task creation and `onClientDisconnect()` with one FIFO ownership manager. Legacy disconnect handling is removed; handoff choices validate the pending user; owner loss cancels queued work and drains scheduler-tracked work before promotion; an unanswered 60-second handoff requests reset. Publish transition events.
- [ ] Command execution registers operations with lock groups, reports outstanding-limit/time-out rejection, retains named locks until timed-out command work ends, and cancels queued operations before handoff reset. Timeout faults fence admission and emit a legacy event. Local CLI recovery now offers reset, resume, or fault shutdown through Unix IPC; publish structured ownership/operation/reset transitions.
- [x] Convert the existing lock mapping into startup validation. Fail before serving if any device lacks exactly one explicit lock-group assignment or appears in more than one group.
- [ ] Route camera-switch progress through operation IDs and state events rather than separate uncorrelated command strings.
- [ ] Add outstanding-operation limits, timeout, cancellation, and terminal-result handling without introducing a global command queue.
- [ ] Design the scheduler boundary: compare explicit lock ownership with FIFO workers per named lock group, while preserving concurrent execution across independent groups.

**Tests:** FIFO user promotion into handoff-pending state; inactive-user rejection; same-lock serialization; independent-lock concurrency; outstanding-operation limit; active-user disconnect before lock acquisition; disconnect during execution; handoff continue/reset and automatic reset timeout; reset failure; timeout followed by a same-lock command while executor work remains active; command timeout freezes admission without automatic reset; camera progress correlation.

### 4. Implement unified shutdown and controller safety audit
- [ ] Coordinator teardown enters `stopping`, cancels queued operations, drains active scheduler work, resets devices behind a barrier, closes WebSocket/IPC resources, and shuts down the executor. It safe-stops all devices even if reset fails and reports combined reset/stop failures. Add dependency ordering, persistence, hardware-resource release, and PID cleanup.
- [ ] Route foreground signals and startup failure through coordinator shutdown. Route systemd termination, CLI stop, and explicit reset through the same sequence with their stated reset reason.
- [ ] `safe_stop()` is abstract and explicitly implemented by every controller. Graceful coordinator shutdown resets then safe-stops; fault shutdown safe-stops without reset. Hardware-validate each declared safe state and add controller-specific recovery where a stop does not establish a known state.
- [ ] Remove direct `exit()`, `os._exit()`, and independent cleanup paths that bypass the coordinator.

Current coverage verifies repeated shutdown requests share one future, foreground signal helper behavior, startup-failure teardown, idempotent cleanup, reset failure, and graceful/fault shutdown mode selection.

**Tests:** Ctrl+C while idle; Ctrl+C during a blocking command; SIGTERM during reset; repeated signals; startup failure after partial device creation; reset exception aggregation; exactly-once PID/socket cleanup; executor shutdown.

### 5. Migrate control and IPC messages to JSON
- [x] Specify and implement negotiated version 1 JSON envelopes in `docs/protocol.md`, including `state.snapshot`, `state.changed`, queue, reset, and fault events. Legacy clients retain their existing framing.
- [ ] Include operation ID and lifecycle state in every result, error, and camera event.
- [ ] Support legacy slash-delimited requests/responses per connection during the agreed compatibility window; never mix legacy and JSON frames on one connection.
- [ ] Update the maintained browser WebSocket client to render control-owner/waiting-user status, current operations, reset/fault status, and reconnect state. Remove duplicate/stale socket client assets, including the tracked conflict-marker file.

**Tests:** JSON schema/contract fixtures; legacy adapter fixtures; malformed input; client reconnect snapshot; operation/event correlation; browser-client unit coverage where practical.

### 6. Apply camera-cycle plan and deployment boundaries
- [x] Complete `UPDATE_PLAN.md`: cycling is removed from `init()`, the boot guard remains only in `run()`, and camera-cycle documentation reflects MediaMTX-only restarts.
- [x] Extract camera sensor/mux configuration from installation into `sudo remla camera setup`; it stops ReMLA, backs up and updates boot configuration, and requires an operator reboot without reinstalling packages or redeploying the lab website.
- [ ] Verify that cycle/reset/shutdown ordering does not restart or interrupt MediaMTX unexpectedly.
- [x] Define a dedicated `remla` systemd service account, versioned `/opt/remla` runtime, shared configuration/lab locations, operator group, group-writable IPC socket, and narrow Polkit rule for `remla.service`. Validate the rule and service ownership on Raspberry Pi OS before treating it as an access-control boundary.
- [x] Add `remla link [PATH]` to create a safe personal symlink to the canonical lab root without overwriting existing workspace paths. Git remains responsible for cloning, branches, and updates.
- [x] Migrate packaging from Poetry to PEP 621 + UV. GitHub tag releases build a wheel, hash-locked requirements, installer, service, and policy assets; the installer verifies release checksums and installs the wheel without requiring UV or pipx on the Pi.
- [x] Keep `remla setup int` and `remla setup lab` unprivileged for lab selection/configuration; `sudo remla setup deploy-website` now performs nginx configuration and website deployment to `/var/www/remla`.
- [ ] Rotate the diffrac2 PDU credential after its named secret-store migration; do not commit or print the value.
- [ ] Publish the first stable `v0.4.0` GitHub Release and validate its installer from a clean Raspberry Pi OS image. Add signed release provenance; until then the convenience installer explicitly relies on GitHub Release integrity and its checksums only detect transfer or asset corruption.

**Current Pi validation:** diffrac2 completed interactive setup, selected `remoteLabs/diffrac2.yml`, initialized the configured controllers, and reached a stable active systemd service with a group-restricted IPC socket. The deployed `sudo remla camera setup` workflow completed successfully, including its required reboot and post-boot operation. Unprivileged `remla status` and `remla stop`, followed by permitted `systemctl start remla.service`, recovered the service, IPC socket, and local nginx `200 OK`. A direct systemd stop/start completed coordinator teardown and recovery; shutdown with a deliberately active or queued hardware operation remains unverified. Clean-image and remaining hardware behavior remain unverified.

**Current camera diagnosis:** reset reasons, configured ArduCam reset slots, and accepted camera selections are journaled to distinguish reset behavior from a later camera override. diffrac now resets its backend camera baseline to `initialCamera: b` (overview); the website independently selects `b` when an active page loads.

**Hardware verification:** clean-image installer; interactive camera setup; reboot and confirm one camera cycle; unprivileged `remla status/start/stop/recover/upgrade`; disconnect an active browser during motor/camera use; Ctrl+C from `remla run -f`; `systemctl stop remla`; camera cleanup/restart; physical actuator safe state; reconnect after reset; service restart after fault.

## Deferred work
- [ ] Add deterministic multi-lock acquisition only if a future command must reserve more than one lock group; preserve lock ordering and dedicated concurrency tests.
- [ ] Add explicit operator-requested persisted-state recovery only after controllers declare which state fields are safe to restore.
- [ ] Add authentication only if deployment boundaries change from the current trusted-network model.
