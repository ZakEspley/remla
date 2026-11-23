import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from remla.snapshot_worker import capture_png, inspect_png


def png(width, height, depth=8, colour=2):
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))
    rows = b"".join(b"\x00" + b"\x00" * width * 3 for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class Camera:
    def __init__(self, index):
        assert index == 0
        class SensorFormat:
            def __str__(self):
                return "SGBRG10_CSI2P"

        self.sensor_modes = [{"size": (16, 12), "bit_depth": 10, "format": SensorFormat()}]
        self.closed = False
        self.stopped = False

    def create_still_configuration(self, **kwargs):
        self.requested = kwargs
        return {"main": kwargs["main"], "sensor": kwargs["sensor"],
                "raw": {"size": (16, 12), "format": "SGBRG10_CSI2P"}}

    def configure(self, configuration):
        self.configuration = configuration

    def camera_configuration(self):
        return self.configuration

    def start(self):
        self.started = True

    def capture_file(self, path, format=None):
        Path(path).write_bytes(png(16, 12))

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class SnapshotWorkerTests(unittest.TestCase):
    def test_capture_requests_native_sensor_and_rgb_png_then_releases_camera(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "still.png"
            instances = []

            def camera_class(index):
                camera = Camera(index)
                instances.append(camera)
                return camera

            capture_png(16, 12, path, camera_class=camera_class)
            self.assertEqual(inspect_png(path), (16, 12))
            camera = instances[0]
            self.assertEqual(camera.requested["main"], {"size": (16, 12), "format": "RGB888"})
            self.assertEqual(camera.requested["sensor"], {"output_size": (16, 12), "bit_depth": 10})
            self.assertTrue(camera.closed)
            self.assertTrue(camera.stopped)

    def test_rejects_unsupported_mode_without_starting_camera(self):
        with tempfile.TemporaryDirectory() as directory:
            camera = Camera(0)
            with self.assertRaisesRegex(ValueError, "native sensor mode"):
                capture_png(17, 12, Path(directory) / "still.png", camera_class=lambda _: camera)
            self.assertFalse(getattr(camera, "started", False))
            self.assertTrue(camera.closed)

    def test_rejects_truncated_or_wrong_depth_png(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "still.png"
            for invalid in (b"not png", png(16, 12, depth=16), png(16, 12, colour=0), png(16, 12)[:34]):
                with self.subTest(invalid=invalid[:10]):
                    path.write_bytes(invalid)
                    with self.assertRaises(ValueError):
                        inspect_png(path)

    def test_close_is_attempted_even_when_stop_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            camera = Camera(0)
            def fail_stop():
                raise RuntimeError("stop failed")
            camera.stop = fail_stop
            with self.assertRaisesRegex(RuntimeError, "stop failed"):
                capture_png(16, 12, Path(directory) / "still.png", camera_class=lambda _: camera)
            self.assertTrue(camera.closed)


if __name__ == "__main__":
    unittest.main()
