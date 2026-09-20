import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from remla import main


class CameraCycleCommandTests(unittest.TestCase):
    def test_init_never_cycles_cameras(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(main.os, "geteuid", return_value=0))
                stack.enter_context(mock.patch.object(main, "settingsDirectory", root / "settings"))
                stack.enter_context(mock.patch.object(main, "logsDirectory", root / "logs"))
                stack.enter_context(mock.patch.object(main, "websiteDirectory", root / "website"))
                stack.enter_context(mock.patch.object(main, "websiteStaticDirectory", root / "website" / "static"))
                stack.enter_context(mock.patch.object(main, "websiteJSDirectory", root / "website" / "js"))
                stack.enter_context(mock.patch.object(main, "websiteCSSDirectory", root / "website" / "css"))
                stack.enter_context(mock.patch.object(main, "websiteImgsDirectory", root / "website" / "images"))
                stack.enter_context(mock.patch.object(main, "remoteLabsDirectory", root / "labs"))
                stack.enter_context(mock.patch.object(main, "runMarker", root / "boot.marker"))
                stack.enter_context(mock.patch.object(main, "is_package_installed", return_value=True))
                stack.enter_context(mock.patch.object(main, "enable_service", return_value=True))
                stack.enter_context(mock.patch.object(main, "echoResult"))
                stack.enter_context(mock.patch.object(main, "_mediamtx"))
                stack.enter_context(mock.patch.object(main, "_nginx"))
                stack.enter_context(mock.patch.object(main, "_createSettingsFile"))
                stack.enter_context(mock.patch.object(main, "createServiceFile"))
                stack.enter_context(mock.patch.object(main, "createRemlaPolicy"))
                stack.enter_context(mock.patch.object(main, "interactivesetup"))
                stack.enter_context(mock.patch.object(main.subprocess, "run"))
                cycle_cameras = stack.enter_context(
                    mock.patch.object(main, "cycle_initialize_cameras")
                )
                main.init()

        cycle_cameras.assert_not_called()


if __name__ == "__main__":
    unittest.main()
