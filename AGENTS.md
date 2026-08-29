# AGENTS

## Purpose
- This file gives automation-friendly guidance for working in this repo.
- Prefer existing conventions; do not invent new tooling without updating this doc.

## Repository context
- Python 3.11 CLI app for controlling remote lab hardware (Raspberry Pi).
- Entry point: Typer app in remla/main.py.
- Hardware controllers live in remla/labcontrol/Controllers.py.
- WebSocket server logic lives in remla/labcontrol/Experiment.py.
- Paths and system locations are centralized in remla/settings.py.

## Agent rules from editors
- No Cursor rules found (.cursor/rules/ or .cursorrules).
- No Copilot instructions found (.github/copilot-instructions.md).

## Build / install (Poetry)
- Python: 3.11 (see pyproject.toml).
- Install deps: `poetry install --sync --no-interaction`
- Build package: `poetry build`
- Run CLI: `poetry run remla --help`

## Lint / format
- No lint or formatter configuration is present in this repo.
- Keep formatting consistent with existing files (see style section).

## Tests
- There is an ad-hoc boot-time test script and standard-library unit tests.
- Run all tests: `poetry run python tests/test.py && poetry run python -m unittest tests/test_mediamtx.py tests/test_mediamtx_camera.py tests/test_device_config.py`
- Run a single test: `poetry run python tests/test.py` (no pytest suite configured).
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
- Command parsing uses `<cmd>_parser` methods; keep them in sync.
- `deviceType` should be set for each controller.
- Respect lock groups in Experiment when adding new device types.

## WebSocket server
- The server runs in `Experiment.startServer()` with asyncio and websockets.
- Use `ThreadPoolExecutor` for hardware calls to avoid blocking the loop.
- Messages use prefixes: `MESSAGE:`, `ALERT:`, `COMMAND:`.
- Keep IPC socket path `/tmp/remla_cmd.sock` consistent.

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
- Test script: `tests/test.py`

## Common tasks
- Show config path: `poetry run remla showconfig`
- Start service foreground: `poetry run remla run -f`
- Start background service: `poetry run remla run`
- Stop service: `poetry run remla stop`
- Service status: `poetry run remla status`

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
