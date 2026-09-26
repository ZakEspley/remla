import tempfile
import unittest
from pathlib import Path

from remla.workspace import WorkspaceLinkError, create_workspace_link


class WorkspaceLinkTests(unittest.TestCase):
    def test_creates_and_reuses_workspace_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lab_root = root / "var" / "lib" / "remla" / "labs"
            workspace = root / "home" / "pi" / "remla"

            self.assertTrue(create_workspace_link(workspace, lab_root))
            self.assertTrue(workspace.is_symlink())
            self.assertEqual(workspace.resolve(), lab_root)
            self.assertFalse(create_workspace_link(workspace, lab_root))

    def test_does_not_link_a_lab_root_to_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            lab_root = Path(directory) / "home" / "pi" / "remla"

            self.assertFalse(create_workspace_link(lab_root, lab_root))
            self.assertTrue(lab_root.is_dir())
            self.assertFalse(lab_root.is_symlink())

    def test_refuses_existing_directory_or_different_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lab_root = root / "var" / "lib" / "remla" / "labs"
            workspace = root / "home" / "pi" / "remla"
            workspace.mkdir(parents=True)

            with self.assertRaises(WorkspaceLinkError):
                create_workspace_link(workspace, lab_root)

            workspace.rmdir()
            other_root = root / "other"
            other_root.mkdir()
            workspace.symlink_to(other_root, target_is_directory=True)

            with self.assertRaises(WorkspaceLinkError):
                create_workspace_link(workspace, lab_root)

    def test_refuses_symlink_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lab_root = root / "var" / "lib" / "remla" / "labs"
            workspace = root / "home" / "pi" / "remla"
            workspace.parent.mkdir(parents=True)
            workspace.symlink_to(workspace.name)

            with self.assertRaises(WorkspaceLinkError):
                create_workspace_link(workspace, lab_root)


if __name__ == "__main__":
    unittest.main()
