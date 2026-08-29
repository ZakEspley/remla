import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def _nonnegative_float(value):
    value = float(value)
    if value < 0:
        raise ValueError("must be greater than or equal to 0")
    return value


def _unsigned_int(value):
    value = int(value)
    if value < 0:
        raise ValueError("must be greater than or equal to 0")
    return value


def _bounded_float(minimum, maximum):
    def parse(value):
        value = float(value)
        if not minimum <= value <= maximum:
            raise ValueError(f"must be between {minimum} and {maximum}")
        return value

    return parse


def _enum_value(*allowed):
    def parse(value):
        value = str(value).lower()
        if value not in allowed:
            raise ValueError("must be one of: " + ", ".join(allowed))
        return value

    return parse


def _awb_gains(value):
    if isinstance(value, str):
        values = value.replace("[", "").replace("]", "").split(",")
    else:
        values = value
    if len(values) != 2:
        raise ValueError("must contain red and blue gains")
    return [float(item) for item in values]


CONTROL_MAPPINGS = {
    "brightness": ("rpiCameraBrightness", _bounded_float(-1, 1)),
    "contrast": ("rpiCameraContrast", _bounded_float(0, 16)),
    "saturation": ("rpiCameraSaturation", _bounded_float(0, 16)),
    "sharpness": ("rpiCameraSharpness", _bounded_float(0, 16)),
    "exposure": (
        "rpiCameraExposure",
        _enum_value("normal", "short", "long", "custom"),
    ),
    "exposuremode": (
        "rpiCameraExposure",
        _enum_value("normal", "short", "long", "custom"),
    ),
    "exposuretime": ("rpiCameraShutter", _unsigned_int),
    "exposuretimeabsolute": ("rpiCameraShutter", _unsigned_int),
    "shutter": ("rpiCameraShutter", _unsigned_int),
    "gain": ("rpiCameraGain", _nonnegative_float),
    "analoguegain": ("rpiCameraGain", _nonnegative_float),
    "ev": ("rpiCameraEV", _bounded_float(-10, 10)),
    "exposurecompensation": ("rpiCameraEV", _bounded_float(-10, 10)),
    "awb": (
        "rpiCameraAWB",
        _enum_value(
            "auto",
            "incandescent",
            "tungsten",
            "fluorescent",
            "indoor",
            "daylight",
            "cloudy",
            "custom",
        ),
    ),
    "whitebalancemode": (
        "rpiCameraAWB",
        _enum_value(
            "auto",
            "incandescent",
            "tungsten",
            "fluorescent",
            "indoor",
            "daylight",
            "cloudy",
            "custom",
        ),
    ),
    "awbgains": ("rpiCameraAWBGains", _awb_gains),
    "colourgains": ("rpiCameraAWBGains", _awb_gains),
    "denoise": (
        "rpiCameraDenoise",
        _enum_value("off", "cdn_off", "cdn_fast", "cdn_hq"),
    ),
    "metering": (
        "rpiCameraMetering",
        _enum_value("centre", "spot", "matrix", "custom"),
    ),
    "flickerperiod": ("rpiCameraFlickerPeriod", _unsigned_int),
}


def camera_control_payload(control_name: str, value) -> dict:
    normalized_name = str(control_name).lower().replace("_", "").replace("-", "")
    mapping = CONTROL_MAPPINGS.get(normalized_name)
    if mapping is None:
        raise ValueError(f"unsupported MediaMTX camera control: {control_name}")

    field, parser = mapping
    return {field: parser(value)}


def patch_camera_control(
    control_name: str,
    value,
    path: str = "cam",
    api_url: str = "http://127.0.0.1:9997",
    timeout: float = 2,
) -> dict:
    payload = camera_control_payload(control_name, value)
    path = str(path).strip("/")
    if not path:
        raise ValueError("MediaMTX path cannot be empty")

    request = Request(
        f"{api_url.rstrip('/')}/v3/config/paths/patch/{quote(path, safe='/')}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"MediaMTX rejected camera control ({exc.code}): {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to reach the MediaMTX API: {exc.reason}") from exc

    return payload
