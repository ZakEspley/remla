"""Camera diagnostics; importing this module never opens a camera."""

import importlib
import json
import subprocess
import sys


def check_picamera2_runtime() -> str:
    """Verify imports from this ReMLA interpreter, without creating a camera."""
    try:
        importlib.import_module("libcamera")
        picamera2 = importlib.import_module("picamera2")
        getattr(picamera2, "Picamera2")
    except (ImportError, OSError, AttributeError) as error:
        raise RuntimeError(
            "Picamera2/libcamera is unavailable in this ReMLA Python runtime. "
            "Check the installed release environment, not just system Python."
        ) from error
    return str(getattr(picamera2, "__version__", "version unavailable"))


def require_idle_services() -> None:
    """Fail closed if the installed camera-owning services are active or unknown."""
    for service in ("mediamtx.service", "remla.service"):
        try:
            result = subprocess.run(
                ["systemctl", "show", "--property=LoadState,ActiveState,SubState", service],
                capture_output=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f"Cannot verify that {service} is idle: {error}") from error
        if result.returncode != 0:
            raise RuntimeError(
                f"Cannot verify that {service} is idle (systemctl exit {result.returncode})."
            )
        try:
            properties = dict(line.split("=", 1) for line in result.stdout.decode().splitlines())
        except (UnicodeError, ValueError) as error:
            raise RuntimeError(f"Cannot verify that {service} is idle.") from error
        if properties.get("LoadState") != "loaded":
            raise RuntimeError(f"Cannot verify that {service} is idle (service not loaded).")
        if properties.get("ActiveState") == "active":
            raise RuntimeError(f"{service} is active; camera modes require an idle camera.")
        if (properties.get("ActiveState"), properties.get("SubState")) != ("inactive", "dead"):
            raise RuntimeError(
                f"Cannot verify that {service} is idle (service is transitioning or failed)."
            )


def _probe_modes(camera_index: int) -> dict:
    """Executed in a bounded child process, only after the CLI's idle checks."""
    require_idle_services()
    from picamera2 import Picamera2

    cameras = Picamera2.global_camera_info()
    if camera_index >= len(cameras):
        raise RuntimeError(f"Camera index {camera_index} is not available ({len(cameras)} detected).")
    camera = Picamera2(camera_index)
    try:
        modes = []
        for mode in camera.sensor_modes:
            item = {
                "size": [int(value) for value in mode["size"]],
                "bit_depth": int(mode["bit_depth"]),
                "format": str(mode["format"]),
            }
            for key in ("fps", "crop_limits"):
                if key in mode:
                    value = mode[key]
                    item[key] = list(value) if key == "crop_limits" else float(value)
            modes.append(item)
        return {"sensor": str(cameras[camera_index].get("Model", "unknown")), "modes": modes}
    finally:
        camera.close()


def list_camera_modes(camera_index: int) -> dict:
    """Bound enumeration; child termination also releases its camera descriptors."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "remla.camera_diagnostics", "--probe", str(camera_index)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Camera enumeration did not complete: {error}") from error
    if result.returncode != 0:
        raise RuntimeError("Camera enumeration failed; check the installed runtime and camera access.")
    try:
        data = json.loads(result.stdout)
        if not isinstance(data["modes"], list) or not isinstance(data["sensor"], str):
            raise ValueError("Invalid mode response")
        return data
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError("Camera enumeration returned an invalid response.") from error


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--probe" or not sys.argv[2].isdigit():
        sys.exit(2)
    try:
        print(json.dumps(_probe_modes(int(sys.argv[2]))))
    except Exception as error:
        print(f"Camera enumeration failed: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
