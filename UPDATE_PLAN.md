# UPDATE_PLAN

## Goal
Align camera cycling with intended behavior: run **once per boot**, triggered only from `remla run`, while keeping `init()` idempotent and non-destructive on re-runs.

## Current behavior
- Camera cycling is triggered only by `remla/main.py:run()` after `get_boot_status()` reports a new boot.
- `init()` never cycles cameras.
- `runMarker` is a per-boot guard: `get_boot_status()` writes current boot time to `runMarker` and returns True only on a new boot.

## Target Behavior (Agreed)
- **Cycle only in `run()`**, never in `init()`.
- **Cycle exactly once per boot** using `get_boot_status()`.
- Cycling should only switch ArduCam channels and **restart `mediamtx`** per channel (no `remla.service` restart inside the cycle).
- Re-running `init()` should only create missing files/directories and not overwrite existing ones.
- If camera config changes, simplest policy is to require a reboot (no auto-recycle unless explicitly requested later).

## Completed code changes

### 1) Move camera cycling out of `init()`
- [x] Removed the `runMarker.exists()` / `cycle_initialize_cameras()` block from `remla/main.py:init()`.
- [x] `init()` creates setup resources but does not perform boot-guarded runtime actions.

### 2) Keep boot-guarded cycling only in `run()`
- [x] `run()` uses `get_boot_status()` and cycles only when it returns True.
- [x] Camera-cycle logging remains in `camera_cycle.log` through `get_camera_logger()`.

### 3) Align documentation and behavior
- [x] `cycle_initialize_cameras()` documents mux selection, MediaMTX restart, and per-camera wait time only.

### 4) Optional safety guard (deferred)
- Consider restoring the guard that skips cycling when `remla.service` is already active.
- If you want this behavior, re-enable the block currently commented out in `cycle_initialize_cameras()`.
- If not, leave it as-is and rely solely on the per-boot guard.

## Testing / Verification
- Manual: reboot, then run `remla run -f` once and confirm cameras cycle only once (check `logsDirectory/camera_cycle.log`).
- Manual: run `remla run -f` again same boot and confirm no cycle (log shows skip).
- Manual: call `remla init` multiple times; confirm no camera cycle and existing files are not overwritten.
