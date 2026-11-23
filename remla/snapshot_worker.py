"""Single Picamera2 capture worker; run only with exclusive camera access."""

import struct
import sys
import zlib
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PNG_BYTES = 25_000_000


def inspect_png(path: Path) -> tuple[int, int]:
    size = path.stat().st_size
    if not 57 <= size <= MAX_PNG_BYTES:
        raise ValueError("Snapshot PNG size is invalid")
    with path.open("rb") as image:
        header = image.read(33)
        if (header[:8] != PNG_SIGNATURE or header[8:16] != b"\x00\x00\x00\rIHDR"
                or len(header) != 33):
            raise ValueError("Snapshot is not a PNG")
        if zlib.crc32(header[12:29]) != struct.unpack(">I", header[29:33])[0]:
            raise ValueError("Snapshot PNG header is corrupt")
        width, height, depth, colour, compression, filtering, interlace = struct.unpack(">IIBBBBB", header[16:29])
        if depth != 8 or colour != 2 or compression or filtering or interlace:
            raise ValueError("Snapshot must be processed 8-bit RGB PNG")
        image.seek(-12, 2)
        if image.read(12) != b"\x00\x00\x00\x00IEND\xaeB`\x82":
            raise ValueError("Snapshot PNG is incomplete")
    return width, height


def capture_png(width: int, height: int, output: Path, camera_class=None) -> None:
    if camera_class is None:
        from picamera2 import Picamera2
        camera_class = Picamera2
    camera = camera_class(0)
    started = False
    try:
        matching = [mode for mode in camera.sensor_modes if tuple(mode["size"]) == (width, height)]
        if len(matching) != 1:
            raise ValueError("Exactly one native sensor mode is required for this snapshot")
        mode = matching[0]
        configuration = camera.create_still_configuration(
            main={"size": (width, height), "format": "RGB888"},
            sensor={"output_size": (width, height), "bit_depth": mode["bit_depth"]},
        )
        camera.configure(configuration)
        actual = camera.camera_configuration()
        if (tuple(actual["main"]["size"]) != (width, height)
                or actual["main"]["format"] != "RGB888"
                or tuple(actual["sensor"]["output_size"]) != (width, height)
                or actual["sensor"]["bit_depth"] != mode["bit_depth"]
                or tuple(actual["raw"]["size"]) != (width, height)
                or str(actual["raw"]["format"]) != str(mode["format"])):
            raise ValueError("Picamera2 adjusted the requested native snapshot mode")
        camera.start()
        started = True
        camera.capture_file(str(output), format="png")
        if inspect_png(output) != (width, height):
            raise ValueError("Snapshot dimensions do not match the selected sensor mode")
    finally:
        try:
            if started:
                camera.stop()
        finally:
            camera.close()


if __name__ == "__main__":
    if len(sys.argv) != 4 or not sys.argv[1].isdigit() or not sys.argv[2].isdigit():
        sys.exit(2)
    try:
        capture_png(int(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3]))
    except Exception as error:
        print(f"Snapshot failed: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
