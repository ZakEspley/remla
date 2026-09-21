import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.request import urlopen


REPOSITORY = "ZakEspley/remla"
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class ReleaseError(RuntimeError):
    pass


class ReleaseInstaller:
    def __init__(self, root: Path | None = None, repository: str = REPOSITORY):
        self.root = root or Path(os.environ.get("REMLA_INSTALL_ROOT", "/opt/remla"))
        self.repository = repository

    def latest_version(self) -> str:
        url = f"https://api.github.com/repos/{self.repository}/releases/latest"
        try:
            with urlopen(url, timeout=30) as response:
                version = json.load(response)["tag_name"].removeprefix("v")
        except Exception as error:
            raise ReleaseError(f"could not identify the latest ReMLA release: {error}") from error
        return self.validate_version(version)

    def validate_version(self, version: str) -> str:
        if not VERSION_PATTERN.fullmatch(version):
            raise ReleaseError(f"invalid stable ReMLA release version: {version}")
        return version

    def verify_assets(self, checksums_path: Path, assets: list[Path]) -> None:
        try:
            checksums = {}
            for line in checksums_path.read_text().splitlines():
                digest, filename = line.split(maxsplit=1)
                checksums[filename.lstrip(" *")] = digest
        except (OSError, ValueError) as error:
            raise ReleaseError(f"could not read release checksums: {error}") from error

        for asset in assets:
            expected = checksums.get(asset.name)
            if expected is None:
                raise ReleaseError(f"release checksums do not include {asset.name}")
            actual = hashlib.sha256(asset.read_bytes()).hexdigest()
            if actual != expected:
                raise ReleaseError(f"checksum verification failed for {asset.name}")

    def download_release(self, version: str, destination: Path) -> tuple[Path, Path]:
        version = self.validate_version(version)
        base_url = f"https://github.com/{self.repository}/releases/download/v{version}"
        wheel = destination / f"remla-{version}-py3-none-any.whl"
        requirements = destination / "requirements.txt"
        checksums = destination / "SHA256SUMS"
        try:
            for filename, target in (
                (wheel.name, wheel),
                (requirements.name, requirements),
                (checksums.name, checksums),
            ):
                with urlopen(f"{base_url}/{filename}", timeout=60) as response:
                    target.write_bytes(response.read())
        except Exception as error:
            raise ReleaseError(f"could not download ReMLA {version}: {error}") from error
        self.verify_assets(checksums, [wheel, requirements])
        return wheel, requirements

    def install(self, version: str | None = None) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "releases").mkdir(exist_ok=True)
        version = self.latest_version() if version is None else self.validate_version(version)
        release_directory = self.root / "releases" / version
        if release_directory.exists():
            self.activate(version)
            return version

        with tempfile.TemporaryDirectory(dir=self.root, prefix="download-") as download_directory:
            wheel, requirements = self.download_release(version, Path(download_directory))
            temporary_release = self.root / "releases" / f".{version}-{uuid.uuid4().hex}"
            try:
                subprocess.run([sys.executable, "-m", "venv", temporary_release / "venv"], check=True)
                pip = temporary_release / "venv" / "bin" / "pip"
                subprocess.run(
                    [pip, "install", "--require-hashes", "--no-deps", "-r", requirements],
                    check=True,
                )
                subprocess.run([pip, "install", "--no-deps", wheel], check=True)
                os.replace(temporary_release, release_directory)
            except (OSError, subprocess.CalledProcessError) as error:
                shutil.rmtree(temporary_release, ignore_errors=True)
                raise ReleaseError(f"could not install ReMLA {version}: {error}") from error
        self.activate(version)
        return version

    def activate(self, version: str) -> None:
        version = self.validate_version(version)
        target = self.root / "releases" / version / "venv"
        if not target.is_dir():
            raise ReleaseError(f"release {version} is not installed")
        current = self.root / "current"
        old_target = current.resolve() if current.is_symlink() else None
        if old_target is not None and old_target != target:
            self._replace_link("previous", old_target)
        self._replace_link("current", target)

    def rollback(self) -> str:
        current = self.root / "current"
        previous = self.root / "previous"
        if not current.is_symlink() or not previous.is_symlink():
            raise ReleaseError("no previous ReMLA release is available for rollback")
        current_target = current.resolve()
        previous_target = previous.resolve()
        if not current_target.is_dir() or not previous_target.is_dir():
            raise ReleaseError("installed release links are invalid")
        self._replace_link("current", previous_target)
        self._replace_link("previous", current_target)
        return previous_target.parent.name

    def _replace_link(self, name: str, target: Path) -> None:
        temporary_link = self.root / f".{name}-{uuid.uuid4().hex}"
        temporary_link.symlink_to(target)
        os.replace(temporary_link, self.root / name)
