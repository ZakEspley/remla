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
- Versioned persisted-state storage lives in remla/runtime_state.py.
- FIFO control ownership and operation lifecycle models live in remla/runtime_operations.py.
- Named lock-group scheduling lives in remla/command_scheduler.py. Every device must belong to exactly one named lock group; `Experiment.runDeviceMethod()` registers each command and delegates serialization to this scheduler, while devices in different groups run concurrently. Timed-out grouped commands retain their scheduler lock until their command coroutine finishes; timeout faults block admission and send a legacy fault event. An active-owner disconnect drains its work; a waiting user receives the existing reset-or-continue handoff, while an empty ownership queue triggers a full reset. A pending handoff has a 60-second timer; handoff reset and `Experiment.shutdown()` cancel queued operations, drain scheduler work, and acquire a reset barrier. Every controller must explicitly implement abstract `safe_stop()`: `reset()` may return to baseline, while `safe_stop()` must not initiate baseline movement. Graceful shutdown resets then safe-stops; fault shutdown only safe-stops. Prefer `request_shutdown()` for signal-driven teardown; foreground startup failure uses coordinator teardown, while service-mode teardown and hardware validation remain unfinished.
- Configured consumer power routes use `BaseController.power_on`, `power_off`, and `power_toggle`; their provider and consumer must share a lock group.
- `docs/power-routing.md` documents generic `PowerConsumer` devices and provider-backed power routes. `PowerConsumer` has no hardware driver; its provider owns physical reset and safe-stop actions.
- `docs/secrets.md` documents `${secret:name}` YAML references and root-owned `/etc/remla/secrets/` files managed by `sudo remla secrets`; never commit or print resolved secret values.
- Persisted state is diagnostic only at startup; a lab name/hash mismatch is preserved and requires explicit operator archive/discard or configuration restoration.
- WebSocket server logic lives in remla/labcontrol/Experiment.py.
- `docs/protocol.md` defines negotiated JSON protocol version 1 alongside legacy WebSocket framing; preserve legacy frames for clients that do not complete JSON `hello` negotiation.
- `docs/reset-baseline.md` records current controller reset behavior and the owner-disconnect policy; motor position is process-tracked from YAML `initialPosition` until homing is configured.
- Paths and system locations are centralized in remla/settings.py.

## Agent rules from editors
- No Cursor rules found (.cursor/rules/ or .cursorrules).
- No Copilot instructions found (.github/copilot-instructions.md).

## Build / install (UV)
- Python: 3.11 (see pyproject.toml).
- Sync dependencies: `uv sync`
- Build package: `uv build`
- Run CLI: `uv run remla --help`
- Stable Pi releases are published to GitHub Releases. `scripts/install.sh` installs a release into `/opt/remla`; `packaging/remla.service` runs its stable `/opt/remla/current` symlink as the `remla` service account. Do not run this installer on a development workstation except with `--dry-run`.

## Lint / format
- No lint or formatter configuration is present in this repo.
- Keep formatting consistent with existing files (see style section).

## Tests
- Tests use the standard-library `unittest` runner.
- Run the hardware-free suite: `uv run python -m unittest tests.test_runtime_imports tests.test_experiment_lifecycle tests.test_boot_status tests.test_camera_cycle tests.test_runtime_state tests.test_runtime_operations tests.test_command_scheduler tests.test_mediamtx tests.test_mediamtx_camera tests.test_device_config tests.test_controller_safety tests.test_installation tests.test_release tests.test_workspace tests.test_setup_commands tests.test_web_deployment`
- `tests.test_boot_status` covers the camera-cycle boot marker using temporary files and a mocked boot timestamp.
- Run one unit test: `uv run python -m unittest tests.test_runtime_imports` (no pytest suite configured).
- If you add a real test framework, update this section with exact commands.

## Runtime and system notes
- Many commands assume Raspberry Pi OS and hardware access.
- Some commands must run as root; follow existing checks (os.geteuid()).
- System services (nginx, mediamtx, pigpiod) are managed via systemctl.
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
