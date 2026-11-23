"""Opt-in still-capture settings from the selected lab YAML."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SnapshotConfig:
    stream_path: str
    width: int
    height: int
    format: str = "png"


def parse_still_capture(config):
    """Return a supported snapshot config, or None when explicitly disabled."""
    if config is False:
        return None
    if not isinstance(config, dict):
        raise ValueError("stillCapture must be false or a configuration mapping")
    if config.get("enabled") is False and set(config) == {"enabled"}:
        return None
    if set(config) != {"enabled", "streamPath", "sensorMode", "format"}:
        raise ValueError("stillCapture requires enabled, streamPath, sensorMode, and format only")
    if config["enabled"] is not True:
        raise ValueError("stillCapture enabled must be a boolean")
    if config["streamPath"] != "cam" or type(config["streamPath"]) is not str:
        raise ValueError("stillCapture supports only the cam streamPath")
    if config["format"] != "png" or type(config["format"]) is not str:
        raise ValueError("stillCapture supports only processed 8-bit png")
    mode = config["sensorMode"]
    if not isinstance(mode, dict) or set(mode) != {"width", "height"}:
        raise ValueError("stillCapture sensorMode requires width and height only")
    width, height = mode["width"], mode["height"]
    if (type(width) is not int or type(height) is not int or not 1 <= width <= 8192
            or not 1 <= height <= 8192 or width * height > 8_000_000):
        raise ValueError("stillCapture sensorMode dimensions must be positive integers within 8 MP")
    return SnapshotConfig("cam", width, height)
