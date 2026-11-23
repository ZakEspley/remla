import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib


SOURCE = Path(__file__).resolve().parents[1] / "packaging/remla-snapshot-helper"


def load_broker():
    loader = importlib.machinery.SourceFileLoader("snapshot_broker", str(SOURCE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def png(width=8, height=6):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + b"\0" * width * 3) * height))
            + chunk(b"IEND", b""))


class SnapshotBrokerTests(unittest.TestCase):
    def setUp(self):
        self.broker = load_broker()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state = self.root / "state"
        self.work = self.root / "work"
        self.state.mkdir(mode=0o700)
        self.work.mkdir(mode=0o700)
        self.service_active = True
        self.capture_active = False
        self.capture_result = "success"
        self.calls = []
        self.fail_start = False
        self.path_ready = True
        self.bad_image = None
        self.marker_at_stop = False
        self.runner = self.broker.Broker(
            self.state, self.work, os.getuid(), os.getgid(),
            root_uid=os.getuid(), command=self.command, ready=lambda: self.path_ready,
        )
        (self.state / "operator-stop-v1").write_text("coordinated\n")
        self.request = io.BytesIO(b'{"width":8,"height":6}')

    def command(self, *args):
        self.calls.append(args)
        verb, unit = args[:2]
        if verb == "show":
            if unit == self.broker.STREAM:
                return {"LoadState": "loaded", "ActiveState": "active" if self.service_active else "inactive",
                        "SubState": "running" if self.service_active else "dead"}
            if unit == self.broker.CAPTURE:
                return {"LoadState": "loaded", "ActiveState": "active" if self.capture_active else "inactive",
                        "SubState": "running" if self.capture_active else "dead", "Result": self.capture_result,
                        "ExecMainStatus": "0", "ControlGroup": ""}
            return {"LoadState": "loaded", "ActiveState": "active", "SubState": "waiting", "UnitFileState": "enabled"}
        if verb == "stop" and unit == self.broker.STREAM:
            self.marker_at_stop = (self.state / "transaction.json").exists()
            self.service_active = False
        elif verb == "start" and unit == self.broker.STREAM:
            if self.fail_start:
                raise self.broker.BrokerError("failed")
            self.service_active = True
        elif verb == "start" and unit == self.broker.CAPTURE:
            (self.work / "capture.png").write_bytes(self.bad_image or png())
        elif verb == "stop" and unit == self.broker.CAPTURE:
            self.capture_active = False
        return {}

    def test_valid_capture_restores_then_returns_png(self):
        result = self.runner.capture(self.request)
        self.assertEqual(result, png())
        self.assertTrue(self.marker_at_stop)
        self.assertTrue(self.service_active)
        self.assertFalse((self.state / "transaction.json").exists())
        self.assertFalse((self.work / "capture.png").exists())
        self.assertLess(self.calls.index(("stop", self.broker.CAPTURE)), self.calls.index(("start", self.broker.STREAM)))

    def test_initially_inactive_is_never_started(self):
        self.service_active = False
        self.runner.capture(self.request)
        self.assertNotIn(("start", self.broker.STREAM), self.calls)

    def test_invalid_input_does_not_touch_services(self):
        for value in (b'{}', b'{"width":true,"height":6}', b'{"width":8,"height":6,"x":1}',
                      b'{"width":8,"width":9,"height":6}', b'{"width":10000,"height":6}', b'x' * 257):
            with self.subTest(value=value), self.assertRaises(self.broker.BrokerError):
                self.runner.capture(io.BytesIO(value))
        self.assertEqual(self.calls, [])

    def test_coordination_gate_refuses_before_service_changes(self):
        (self.state / "operator-stop-v1").unlink()
        with self.assertRaises(self.broker.BrokerError):
            self.runner.capture(self.request)
        self.assertEqual(self.calls, [])

    def test_recovery_is_armed_before_stopping_stream(self):
        self.runner.capture(self.request)
        self.assertLess(self.calls.index(("start", self.broker.TIMER)), self.calls.index(("stop", self.broker.STREAM)))

    def test_bad_png_restores_without_returning_data(self):
        self.bad_image = b"not a PNG"
        with self.assertRaises(self.broker.BrokerError):
            self.runner.capture(self.request)
        self.assertTrue(self.service_active)
        self.assertFalse((self.work / "capture.png").exists())

    def test_restore_failure_retains_marker_and_blocks_new_capture(self):
        self.fail_start = True
        with self.assertRaises(self.broker.BrokerError):
            self.runner.capture(self.request)
        self.assertTrue((self.state / "transaction.json").exists())
        before = list(self.calls)
        with self.assertRaises(self.broker.BrokerError):
            self.runner.capture(io.BytesIO(b'{"width":8,"height":6}'))
        self.assertEqual(before, self.calls)

    def test_running_service_without_ready_camera_keeps_recovery_pending(self):
        self.path_ready = False
        self.runner.write_marker(True)
        self.service_active = False
        with self.assertRaises(self.broker.BrokerError):
            self.runner.recover()
        self.assertTrue((self.state / "transaction.json").exists())
        self.path_ready = True
        self.runner.recover()
        self.assertFalse((self.state / "transaction.json").exists())

    def test_readiness_checks_cam_source_not_only_http_200(self):
        for payload, expected in (({"ready": True, "online": True,
                                    "source": {"type": "rpiCameraSource", "id": ""}}, True),
                                  ({"ready": True, "online": False,
                                    "source": {"type": "rpiCameraSource", "id": ""}}, False),
                                  ({"ready": True, "online": True,
                                    "source": {"type": "alwaysAvailableSource", "id": ""}}, False),
                                  ({"ready": True, "source": {}}, False)):
            with self.subTest(payload=payload):
                response = io.BytesIO(json.dumps(payload).encode())
                response.status = 200
                with (mock.patch.object(self.broker, "urlopen", return_value=response),
                      mock.patch.object(self.broker.time, "monotonic", side_effect=[0, 0, 26]),
                      mock.patch.object(self.broker.time, "sleep")):
                    # A failed attempt expires the fake deadline on the next iteration.
                    self.assertEqual(self.broker.wait_for_cam_ready(), expected)

    def test_photo1_legacy_path_requires_incoming_camera_bytes(self):
        def reply(received):
            response = io.BytesIO(json.dumps({
                "name": "cam", "source": {"type": "rpiCameraSource", "id": ""},
                "ready": True, "readyTime": "2026-11-22T10:28:31-08:00",
                "tracks": ["H264"], "bytesReceived": received,
            }).encode())
            response.status = 200
            return response

        for samples, expected in (((100, 200), True), ((100, 100), False), ((0, 0), False)):
            with self.subTest(samples=samples):
                with (mock.patch.object(self.broker, "urlopen", side_effect=[reply(value) for value in samples]),
                      mock.patch.object(self.broker.time, "monotonic", side_effect=[0, 0, 0, 26]),
                      mock.patch.object(self.broker.time, "sleep")):
                    self.assertEqual(self.broker.wait_for_cam_ready(), expected)

    def test_recovery_stops_capture_before_restoring_stream(self):
        self.runner.write_marker(True)
        self.capture_active = True
        self.service_active = False
        self.runner.recover()
        self.assertTrue(self.service_active)
        self.assertFalse(self.capture_active)
        self.assertFalse((self.state / "transaction.json").exists())
        self.assertLess(self.calls.index(("stop", self.broker.CAPTURE)), self.calls.index(("start", self.broker.STREAM)))

    def test_recovery_does_not_start_initially_inactive_stream(self):
        self.runner.write_marker(False)
        self.service_active = False
        self.runner.recover()
        self.assertFalse(self.service_active)

    def test_operator_stop_cancels_restoration_durably(self):
        self.runner.write_marker(True)
        self.runner.stop_stream()
        self.runner.recover()
        self.assertFalse(self.service_active)
        self.assertNotIn(("start", self.broker.STREAM), self.calls)

    def test_recovery_finishes_operator_stop_after_process_death(self):
        self.runner.write_marker(False, stop=True)
        self.runner.recover()
        self.assertFalse(self.service_active)
        self.assertIn(("stop", self.broker.STREAM), self.calls)
        self.assertFalse((self.state / "transaction.json").exists())

    def test_unconfirmed_capture_stop_never_restarts_stream(self):
        self.runner.write_marker(True)
        original = self.runner.command
        def command(*args):
            result = original(*args)
            if args == ("show", self.broker.CAPTURE):
                result["ControlGroup"] = "/still-populated"
            return result
        self.runner.command = command
        with self.assertRaises(self.broker.BrokerError):
            self.runner.recover()
        self.assertNotIn(("start", self.broker.STREAM), self.calls)
        self.assertTrue((self.state / "transaction.json").exists())

    def test_image_symlink_is_rejected(self):
        target = self.root / "secret"
        target.write_bytes(png())
        (self.work / "capture.png").symlink_to(target)
        with self.assertRaises(self.broker.BrokerError):
            self.runner.read_image(8, 6)

    def test_image_hardlink_and_wrong_owner_are_rejected(self):
        image = self.work / "capture.png"
        image.write_bytes(png())
        os.link(image, self.work / "other")
        with self.assertRaises(self.broker.BrokerError):
            self.runner.read_image(8, 6)
        (self.work / "other").unlink()
        self.runner.uid = os.getuid() + 1
        with self.assertRaises(self.broker.BrokerError):
            self.runner.read_image(8, 6)

    def test_png_crc_dimensions_and_decompressed_size_are_validated(self):
        for data in (png(9, 6), png()[:-1], png().replace(b"IDAT", b"IDaT"), png() + b"secret"):
            (self.work / "capture.png").write_bytes(data)
            with self.assertRaises(self.broker.BrokerError):
                self.runner.read_image(8, 6)

    def test_real_systemctl_adapter_uses_fixed_absolute_binary_and_timeout(self):
        with mock.patch.object(self.broker.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=b"LoadState=loaded\n", stderr=b"")
            self.broker.systemctl("show", self.broker.STREAM)
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "/usr/bin/systemctl")
        self.assertEqual(kwargs["timeout"], 50)
        self.assertNotIn("shell", kwargs)


if __name__ == "__main__":
    unittest.main()
