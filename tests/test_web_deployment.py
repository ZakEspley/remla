import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from remla.web_deployment import set_website_permissions


class WebsiteDeploymentTests(unittest.TestCase):
    def test_web_root_is_readable_by_nginx_after_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            website = Path(directory) / "website"
            nested = website / "static" / "css"
            nested.mkdir(parents=True)
            index = website / "index.html"
            stylesheet = nested / "site.css"
            index.write_text("index")
            stylesheet.write_text("css")
            website.chmod(0o700)
            nested.chmod(0o700)
            index.chmod(0o600)
            stylesheet.chmod(0o600)

            with mock.patch("remla.web_deployment.os.fchown") as chown:
                set_website_permissions(website)

            for path in (website, website / "static", nested):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)
            for path in (index, stylesheet):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
            self.assertEqual(chown.call_count, 5)

    def test_permission_normalization_skips_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            website = root / "website"
            website.mkdir()
            target = root / "outside.txt"
            target.write_text("outside")
            target.chmod(0o600)
            (website / "outside.txt").symlink_to(target)
            outside_directory = root / "outside"
            outside_directory.mkdir()
            nested_target = outside_directory / "nested.txt"
            nested_target.write_text("outside")
            nested_target.chmod(0o600)
            (website / "static").symlink_to(outside_directory, target_is_directory=True)

            with mock.patch("remla.web_deployment.os.fchown") as chown:
                set_website_permissions(website)

            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(nested_target.stat().st_mode), 0o600)
            self.assertEqual(chown.call_count, 1)

    def test_initial_nginx_setup_normalizes_the_deployed_tree(self):
        from remla import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup = root / "setup"
            setup.mkdir()
            for filename in ("reader.js", "mediaMTXGetFeed.js"):
                (setup / filename).write_text(filename)
            website = root / "website"
            website_js = website / "js"
            website_js.mkdir(parents=True)
            nginx_website = root / "nginx-website"

            with (
                mock.patch.object(main, "setupDirectory", setup),
                mock.patch.object(main, "websiteDirectory", website),
                mock.patch.object(main, "websiteJSDirectory", website_js),
                mock.patch.object(main, "nginxWebsitePath", nginx_website),
                mock.patch.object(main, "logsDirectory", root / "logs"),
                mock.patch.object(main, "updateRemlaNginxConf"),
                mock.patch.object(main, "updateFinalInfo", return_value="index"),
                mock.patch.object(main, "enable_service", return_value=True),
                mock.patch.object(main, "echoResult"),
                mock.patch.object(main.subprocess, "run"),
                mock.patch.object(main, "success"),
                mock.patch.object(main, "set_website_permissions") as normalize,
            ):
                main._nginx()

            normalize.assert_called_once_with(nginx_website)


if __name__ == "__main__":
    unittest.main()
