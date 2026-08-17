import unittest

from remla.device_config import validate_device_arguments


class DeviceConfigTests(unittest.TestCase):
    def test_reports_all_unsupported_options(self):
        class Camera:
            def __init__(self, name, numCameras, streamPath="cam"):
                pass

        with self.assertRaisesRegex(
            TypeError,
            "unsupported configuration options: cameraSwitchMode, persistentPublisher",
        ):
            validate_device_arguments(
                "Camera",
                Camera,
                {
                    "numCameras": 4,
                    "streamPath": "cam",
                    "cameraSwitchMode": "restart",
                    "persistentPublisher": True,
                },
            )

    def test_allows_declared_options(self):
        class Camera:
            def __init__(self, name, numCameras, streamPath="cam"):
                pass

        validate_device_arguments(
            "Camera",
            Camera,
            {"numCameras": 4, "streamPath": "cam"},
        )

    def test_allows_classes_with_keyword_arguments(self):
        class Camera:
            def __init__(self, name, **options):
                pass

        validate_device_arguments("Camera", Camera, {"customOption": True})


if __name__ == "__main__":
    unittest.main()
