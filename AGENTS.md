# AGENTS

## Purpose
- This file gives automation-friendly guidance for working in this repo.
- Prefer existing conventions; do not invent new tooling without updating this doc.

## Repository context
- Python 3.11 CLI app for controlling remote lab hardware (Raspberry Pi).
- Entry point: Typer app in remla/main.py.
- Hardware controllers live in remla/labcontrol/Controllers.py.
- Runtime hardware resources are created in remla/labcontrol/hardware.py.
- Camera cycling runs only from `remla run` once per boot through `get_boot_status()`; `remla init` never cycles cameras.
- Full-resolution still capture is installed on photo1 only as a **test runtime**, not a stable release; see `roadmap.md` §5a. Photo1 is a Pi 4 with MediaMTX-native `cam` at 1920×1080 and no camera controller in its selected YAML. `remla camera check` imports Picamera2/libcamera without opening hardware; `remla camera modes` warns and opens the sensor only when ReMLA and MediaMTX are fully stopped. No extra flag is used; the operator must ensure other camera users are stopped. The first slice produces native 2592×1944 Picamera2 **processed 8-bit RGB PNG** (not 10-bit sensor precision), verified as `remla` on photo1. Do not open the sensor concurrently with MediaMTX. Real Pi 4 16-bit colour requires separately validated high-precision raw demosaicing; JPEG, raw DNG and Pi 5 ISP 16-bit RGB remain future options.
- Photo1's `/opt/remla/current` points to `/opt/remla/releases/0.4.6-cyclic-camera-snapshot-10s-100h-794ef0bf5f43/venv` (test wheel SHA-256 `794ef0bf…`); `/opt/remla/previous` retains the compatible no-snapshot camera+cyclic runtime. The selected `photo1.yml` opt-in has SHA-256 `81fedeb9…`; original YAML, prior runtime links, exact website JS and ledger are protected as described in `docs/snapshots.md`. ReMLA and MediaMTX were active with zero automatic restarts after the supervised policy switch; recheck before acting. A live owner previously received a private 2592×1944 PNG via JSON + nginx HTTP; queued visitor and wrong/reused tickets failed. Normal restore, unsupported-mode rejection and broker-kill recovery restored `cam` under the prior runtime; no live new-policy capture, reboot, MediaMTX failure or two-browser acceptance has passed. Restart/rollback can reset or move devices; retain root broker/recovery units while any transaction is pending.
- Snapshot API: `remla/snapshot_config.py` preflights selected-lab `stillCapture` (omission/false disables; explicit `enabled: true`, `streamPath: cam`, `sensorMode` width/height, `format: png` opts in). `Experiment/capture_still` is owner-only JSON; `snapshot_service.py` and `snapshot_budget.py` handle single-flight and a durable 10-second/100-charged-attempts-per-hour limit, `snapshot_worker.py` captures Picamera2 PNG, and `snapshot_tickets.py` serves private one-use downloads via `/ws/snapshot` (response gives page-relative `ws/snapshot` for public `/photo1/` proxy). Root-owned broker/recovery units live under `packaging/remla-snapshot-*`; optional provisioning is `scripts/install-snapshot.sh` (not part of stable installer). The separate Photoelectric worktree contains the deployed snapshot alert/button and translucent, pointer-transparent video-pause warning overlay (`static/js/components/video.js`); pending shows the overlay and button, failures stay in the alert dialog. Exact pre-overlay JS is protected at `/var/www/.remla-photo1-snapshot-overlay-before-5a7793d5/video.js`. No browser was refreshed for this frontend-only deployment; a later owner refresh may disconnect and reset/move devices. The old three-attempt snapshot runtime cannot read a >3-entry ledger: use the protected no-snapshot runtime **with pre-snapshot YAML and website restored first** for rollback, preserving the ledger and broker units. User chose no separate time gate, only owner admission/budget. Read `docs/snapshots.md` and `docs/protocol.md`; targeted tests: `tests/test_snapshot_*.py`, `tests/test_mediamtx.py`. See `roadmap.md` §5a for rollback.
- The source now suppresses outbound frame contents on closed WebSocket sends (private snapshot tokens must never enter logs), and optional `scripts/install-snapshot.sh` holds the broker transaction lock during provisioning. These **source-only hardenings are not installed on photo1**; any runtime switch requires a separately approved supervised restart with the existing marker/budget/rollback precautions.
- Stable installer and upgrade venv policy lives in `scripts/install.sh` and `remla/release.py`: OS Picamera2/libcamera is exposed via system site-packages and imported before activating a new runtime. The installer grants `remla` the narrow `video` device group; `packaging/remla.service` includes it in supplementary groups. The source updater rejects already-installed isolated releases lacking Picamera2; photo1's new test wheel includes this fix, but neither the current source nor a stable release has been published. Check these paths together when changing camera dependencies.
- Versioned persisted-state storage lives in remla/runtime_state.py.
- FIFO control ownership and operation lifecycle models live in remla/runtime_operations.py.
- Named lock-group scheduling lives in remla/command_scheduler.py. Every device must belong to exactly one named lock group; `Experiment.runDeviceMethod()` registers each command and delegates serialization to this scheduler. `Experiment.handleConnection()` dispatches bounded JSON device-command tasks, allowing separate groups to run concurrently while preserving same-group serialization; correlated replies may arrive out of order. JSON handoff choices run inline. Queued commands cancelled by a lifecycle transition schedule a correlated result without delaying fault safe-stop. Photo1's current test runtime and its compatible cyclic rollback are identified above; older motor-limit, 0.4.6, 0.4.5, and UI-state runtimes remain retained. Rollback/restart interrupts control and can reset or move devices; the immediate `/opt/remla/previous` cyclic runtime accepts current YAML, but restore the exact protected original YAML in `roadmap.md` **before** starting the older UI-state runtime, which cannot load `cyclic`. Timed-out grouped commands retain their scheduler lock until their command coroutine finishes; timeout faults block admission and send a legacy fault event. An active-owner disconnect removes ownership before draining its work; a waiting user receives the existing reset-or-continue handoff, while an empty ownership queue triggers a full reset. Connections arriving during draining wait for the reset-or-handoff transition. A pending handoff has a 60-second timer; handoff reset and `Experiment.shutdown()` cancel queued operations, drain scheduler work, and acquire a reset barrier. Every controller must implement abstract `safe_stop()`; graceful shutdown resets then safe-stops, while fault shutdown only safe-stops. Prefer `request_shutdown()` for signal-driven teardown; foreground startup failure uses coordinator teardown, while service-mode teardown and hardware validation remain unfinished.
- Configured consumer power routes use `BaseController.power_on`, `power_off`, and `power_toggle`; their provider and consumer must share a lock group.
- `docs/power-routing.md` documents generic `PowerConsumer` devices and provider-backed power routes. `PowerConsumer` has no hardware driver; its provider owns physical reset and safe-stop actions.
- `docs/secrets.md` documents `${secret:name}` YAML references and root-owned `/etc/remla/secrets/` files managed by `sudo remla secrets`; never commit or print resolved secret values.
- Persisted state is diagnostic only at startup; a lab name/hash mismatch is preserved and requires explicit operator archive/discard or configuration restoration.
- WebSocket server logic lives in remla/labcontrol/Experiment.py.
- `docs/protocol.md` defines negotiated JSON protocol version 1 alongside legacy WebSocket framing. JSON clients receive recipient-specific `ownership.control` and timed `ownership.handoff` events; preserve legacy frames for clients that do not complete JSON `hello` negotiation. In `Experiment.runDeviceMethod()`, a controller's exact `<device>/position/limit` alert becomes a titled JSON warning via `sendAlert()`; legacy clients still receive the original `ALERT:` frame. This warning is installed on photo1 for testing; real limit hardware validation remains pending.
- `remla/ui_state.py` holds bounded, non-persisted, public presentation state independent of device state. JSON owners may replace a namespaced map through `Experiment/set_ui_state`; JSON clients receive `ui.state.snapshot` on connect and full-map `ui.state.changed` updates. Owner disconnect/fault clears it without blocking safety teardown; see `docs/protocol.md` and `tests/test_ui_state.py`. Photo1's cyclic test runtime retains UI-state behavior; the older standalone UI-state runtime remains at its named release path (not `/opt/remla/previous`). Restarting or rolling back can reset/move devices; coordinate a clear window first.
- `remla/setup/remlaJsonSocket.js` and `docs/json-websocket-client.md` provide a framework-free copyable JSON client for custom lab websites; it is separate from legacy `remlaSocket.js`.
- `docs/reset-baseline.md` records current controller reset behavior and the owner-disconnect policy; motor position is process-tracked from YAML `initialPosition` until homing is configured.
- `remla/cyclic_motion.py` plans stepwise shortest-route travel for per-device YAML `cyclic: {stepsPerCycle: N}`; `remla/yaml.py` preflights opt-ins before constructing hardware and the stepper `goto` methods use the shared planner. Opted-in reset returns by the shortest safe path to the starting phase while reporting accumulated position; unconfigured reset stays absolute. See `docs/cyclic-motors.md` for bounds and supported families. A failed/stopped cyclic move invalidates phase; a restart alone cannot verify physical phase. Photo1 tests only the two opted-in filter wheels; this is not hardware-validated. Throttle-only DC motors reject cyclic opt-in; servos remain out of scope.
- Photo1's selected `photo1.yml` has both `FilterStepperI2C` wheels opted into a candidate 1,620-step cycle: six reference points 270 commanded steps apart with `delay: 0.02`, or 32.4 seconds of configured sleeps per revolution, **not** verified physical period or elapsed travel time. The color-wheel UI exposes only four references. The operator confirmed full rotation clearance and starting phase before installation; no wheel commands were sent by automation. The operator clarified that the apparent first/sixth density-wheel asymmetry was a misunderstanding of the physical arrangement; read-only logs showed one-slot `-270`/`+270` commands in both directions. Physical calibration and fault recovery remain unverified. The YAML change triggers a diagnostic persisted-state hash mismatch: leave the old state untouched until the operator explicitly archives/discards it or restores the old YAML.
- Paths and system locations are centralized in remla/settings.py.
- Optional local OpenCode sandboxing uses the user-owned `~/.config/srt/remla.json` profile; see README. Plain SSH to photo1 works with strict host-key checking outside that profile. Only inside `srt`, use the protected `~/.local/lib/srt/direct-ssh.py` helper to reuse its Git SSH proxy; it requires an existing known-host entry and does not expose SSH keys or agent sockets.

## Agent rules from editors
- No Cursor rules found (.cursor/rules/ or .cursorrules).
- No Copilot instructions found (.github/copilot-instructions.md).

## Build / install (UV)
- Python: 3.11 (see pyproject.toml).
- Sync dependencies: `uv sync`
- Build package: `uv build`
- Run CLI: `uv run remla --help`
- Stable Pi releases are published to GitHub Releases. `scripts/install.sh` installs a release into `/opt/remla`; `packaging/remla.service` runs its stable `/opt/remla/current` symlink as the `remla` service account. Source version is `0.4.6`; `0.4.5` remains the last published stable release until a separate release is approved. Do not run this installer on a development workstation except with `--dry-run`.

## Lint / format
- No lint or formatter configuration is present in this repo.
- Keep formatting consistent with existing files (see style section).

## Tests
- Tests use the standard-library `unittest` runner.
- Run the hardware-free suite: `uv run python -m unittest tests.test_cyclic_motion tests.test_ui_state tests.test_runtime_imports tests.test_experiment_lifecycle tests.test_json_command_dispatch tests.test_boot_status tests.test_camera_cycle tests.test_camera_modes tests.test_runtime_state tests.test_runtime_operations tests.test_command_scheduler tests.test_mediamtx tests.test_mediamtx_camera tests.test_device_config tests.test_controller_safety tests.test_installation tests.test_release tests.test_workspace tests.test_setup_commands tests.test_web_deployment tests.test_snapshot_api tests.test_snapshot_broker tests.test_snapshot_budget tests.test_snapshot_config tests.test_snapshot_http tests.test_snapshot_installation tests.test_snapshot_service tests.test_snapshot_tickets tests.test_snapshot_worker`
- `tests.test_boot_status` covers the camera-cycle boot marker using temporary files and a mocked boot timestamp.
- Run one unit test: `uv run python -m unittest tests.test_runtime_imports` (no pytest suite configured).
- If you add a real test framework, update this section with exact commands.

## Runtime and system notes
- Many commands assume Raspberry Pi OS and hardware access.
- Some commands must run as root; follow existing checks (os.geteuid()).
- System services (nginx, mediamtx, pigpiod) are managed via systemctl.
- The release installer adds the `remla` service account to `gpio`, `i2c`, and `dialout`; USB VISA instruments require the `dialout` membership.
- Avoid destructive changes to `/boot/firmware/config.txt` unless explicitly required.

## Code style (Python)
- Indentation: 4 spaces; keep existing line wrapping and spacing.
- Prefer explicit names and simple control flow; avoid clever metaprogramming.
- Use `pathlib.Path` for filesystem paths (consistent with remla/settings.py).
- Avoid introducing new global state unless required for hardware drivers.
- Do not add comments unless a block is non-obvious or safety-critical.

## Imports
- Order imports: stdlib, third-party, then local (`remla.*`).
- Many files use wildcard imports from `remla.settings` and helpers; follow local style when editing those files.
- In new modules, prefer explicit imports to improve readability.
- Keep top-level imports minimal in hardware-facing modules to reduce side effects.

## Typing
- Type hints are used lightly; add them for new public functions and helpers.
- Keep types simple (Optional, list, dict, Path) unless complexity demands more.
- Use `typing_extensions.Annotated` only when needed for Typer option metadata.

## Naming conventions
- Modules: snake_case.
- Classes: CamelCase.
- Functions/variables: snake_case.
- Typer commands: short verbs (`init`, `run`, `stop`, `status`, `enable`).
- Constants: ALL_CAPS (see remla/settings.py).

## Error handling and user feedback
- CLI errors typically use `typer.Abort()` after `alert()` or `warning()`.
- For validation, reuse helpers in `remla/customvalidators.py`.
- Prefer returning booleans for simple checks (e.g., is_package_installed).
- Log unexpected exceptions in long-running services (see Experiment.logException).
- Foreground runs fall back to the calling user's state log directory if the configured service log directory is not writable.
- `remla run -f` writes service and camera logging to the invoking terminal; service mode retains journal/file logging.

## Logging
- Use `logging` for service-level events and file logs.
- `rich` output is used for user-facing CLI messages.
- For camera cycling, use `get_camera_logger()` and avoid duplicate handlers.
- Do not log full device configuration; startup reports device names/types only. Reset reasons and accepted ArduCam selections print to the service journal for hardware diagnosis.

## Subprocess and system commands
- Use `subprocess.run([...], check=True)` for commands that must succeed.
- Avoid `shell=True` unless necessary; prefer explicit args list.
- Capture stdout/stderr only when needed; otherwise allow default for visibility.
- When writing service files or configs, keep permissions and paths consistent.

## YAML and configuration
- YAML parsing/dumping uses `remla/yaml.py` with ruamel YAML.
- Use `yaml.load(Path)` and `yaml.dump(data, Path)` for settings files.
- `settingsDirectory` contains user config files (`settings.yml`, `finalInfo.md`).
- Lab device definitions are in YAML and resolved via `createDevicesFromYml`.

## Devices and controllers
- Controllers subclass `BaseController` and expose command methods.
- `remla.labcontrol.hardware.initialize_hardware_resources()` creates pigpio, GPIO, and VISA resources during foreground runtime setup; imports must remain hardware-free.
- Constructing `Experiment` is side-effect free; call `initialize_runtime()` before adding lock groups or starting the server.
- Command parsing uses `<cmd>_parser` methods; keep them in sync.
- `deviceType` should be set for each controller.
- Respect lock groups in Experiment when adding new device types.

## WebSocket server
- The server runs in `Experiment.startServer()` with asyncio and websockets.
- Use `ThreadPoolExecutor` for hardware calls to avoid blocking the loop.
- Messages use prefixes: `MESSAGE:`, `ALERT:`, `COMMAND:`.
- IPC socket path is centralized as `ipcSocketPath`. Installed services use `/run/remla/remla_cmd.sock`, owned by the `remlausers` group; local development retains the `/tmp/remla_cmd.sock` default.

## Hardware and GPIO
- `pigpio` is primary for GPIO; `RPi.GPIO` is fallback in some helpers.
- Keep GPIO pin numbering in BCM mode (see existing controllers).
- When switching camera mux channels, use `select_arducam_channel_index`.
- Avoid changing timing constants without hardware validation.

## Files and directories of interest
- CLI entry: `remla/main.py`
- System helpers: `remla/systemHelpers.py`
- Settings/constants: `remla/settings.py`
- YAML utilities: `remla/yaml.py`
- Controllers: `remla/labcontrol/Controllers.py`
- Experiment server: `remla/labcontrol/Experiment.py`
- Boot-marker tests: `tests/test_boot_status.py`; init camera-cycle regression: `tests/test_camera_cycle.py`
- Runtime-state tests: `tests/test_runtime_state.py`
- Operation-model tests: `tests/test_runtime_operations.py`
- Scheduler tests: `tests/test_command_scheduler.py`

## Common tasks
- Show config path: `uv run remla showconfig`
- Start service foreground: `uv run remla run -f`
- Start background service: `uv run remla run`
- Start installed service: `uv run remla start`
- Restart installed service: `uv run remla restart`
- Stop service: `uv run remla stop`
- Service status: `uv run remla status`
- Recover a faulted running service: `uv run remla recover`
- Create a lab workspace link: `uv run remla link [PATH]`
- Select a lab without root: `uv run remla setup int`; deploy its website with `sudo uv run remla setup deploy-website`.
- Reconfigure camera boot hardware: `sudo uv run remla camera setup` (stops the service and requires a reboot).

## Safety checks for agents
- Do not modify `/etc`, `/boot`, or systemd files unless explicitly asked.
- Avoid changing network, device, or GPIO configuration without a clear request.
- If running on non-Pi hardware, skip hardware-specific commands.

## When adding new commands
- Register new Typer command in `remla/main.py` or sub-apps.
- Keep CLI help strings short and user-focused.
- Validate inputs with existing validators where possible.
- Use `typer.Abort()` on failures to exit gracefully.

## When adding new devices
- Add the class to `remla/labcontrol/Controllers.py`.
- Ensure it inherits `BaseController` and implements `reset`.
- Provide parsers for commands to validate params.
- Update YAML examples if device requires new fields.

## Repo hygiene
- Do not delete or rewrite existing user configs.
- Avoid reformatting unrelated files.
- Keep changes localized to the requested behavior.

## Updating this file
- If you add linting, formatting, or tests, update the commands above.
- If Cursor/Copilot rules are added, summarize them here.
- Keep this doc around 150 lines for easy scanning.
