import json
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from remla.mediamtx_camera import camera_control_payload, patch_camera_control


class MediaMTXCameraControlTests(unittest.TestCase):
    def test_camera_control_payload_maps_existing_names(self):
        self.assertEqual(
            camera_control_payload("brightness", "0.25"),
            {"rpiCameraBrightness": 0.25},
        )
        self.assertEqual(
            camera_control_payload("exposure_time_absolute", "10000"),
            {"rpiCameraShutter": 10000},
        )
        self.assertEqual(
            camera_control_payload("awb_gains", "1.2,1.4"),
            {"rpiCameraAWBGains": [1.2, 1.4]},
        )

    def test_camera_control_payload_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "between -1 and 1"):
            camera_control_payload("brightness", "2")

        with self.assertRaisesRegex(ValueError, "unsupported"):
            camera_control_payload("horizontal_flip", "1")

    @patch("remla.mediamtx_camera.urlopen")
    def test_patch_uses_single_field_patch_request(self, mocked_urlopen):
        response = MagicMock()
        response.__enter__.return_value = response
        mocked_urlopen.return_value = response

        payload = patch_camera_control("gain", "2.5", path="camera/main")

        self.assertEqual(payload, {"rpiCameraGain": 2.5})
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.method, "PATCH")
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:9997/v3/config/paths/patch/camera/main",
        )
        self.assertEqual(json.loads(request.data), {"rpiCameraGain": 2.5})
        self.assertEqual(request.headers["Content-type"], "application/json")
        self.assertEqual(mocked_urlopen.call_args.kwargs["timeout"], 2)

    @patch("remla.mediamtx_camera.urlopen")
    def test_patch_reports_api_error_body(self, mocked_urlopen):
        mocked_urlopen.side_effect = HTTPError(
            "http://127.0.0.1:9997",
            400,
            "Bad Request",
            {},
            MagicMock(read=lambda: b'{"error":"invalid value"}'),
        )

        with self.assertRaisesRegex(RuntimeError, "400.*invalid value"):
            patch_camera_control("brightness", "0.5")

    @patch("remla.mediamtx_camera.urlopen")
    def test_patch_reports_connection_error(self, mocked_urlopen):
        mocked_urlopen.side_effect = URLError("connection refused")

        with self.assertRaisesRegex(RuntimeError, "connection refused"):
            patch_camera_control("brightness", "0.5")


if __name__ == "__main__":
    unittest.main()
