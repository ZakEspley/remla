import hashlib
import json
import os
import platform
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LATEST_RELEASE_URL = "https://api.github.com/repos/bluenviron/mediamtx/releases/latest"
USER_AGENT = "remla-mediamtx-installer"


class MediaMTXInstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaMTXRelease:
    version: str
    archive_name: str
    archive_url: str
    checksums_url: str


def archive_platform(machine: str | None = None) -> str:
    normalized = (machine or platform.machine()).lower()
    platforms = {
        "aarch64": "linux_arm64",
        "arm64": "linux_arm64",
        "armv7": "linux_armv7",
        "armv7l": "linux_armv7",
        "armv6": "linux_armv6",
        "armv6l": "linux_armv6",
        "amd64": "linux_amd64",
        "x86_64": "linux_amd64",
    }
    try:
        return platforms[normalized]
    except KeyError as exc:
        raise MediaMTXInstallError(
            f"MediaMTX does not publish a supported Linux build for architecture '{normalized}'"
        ) from exc


def _download(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=60) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise MediaMTXInstallError(f"Could not download {url}: {exc}") from exc


def latest_release(machine: str | None = None) -> MediaMTXRelease:
    request = Request(LATEST_RELEASE_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            release_data = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise MediaMTXInstallError(f"Could not query the latest MediaMTX release: {exc}") from exc

    platform_name = archive_platform(machine)
    archive_suffix = f"_{platform_name}.tar.gz"
    archive = None
    checksums = None
    for asset in release_data.get("assets", []):
        name = asset.get("name", "")
        if name.startswith("mediamtx_") and name.endswith(archive_suffix):
            archive = asset
        elif name == "checksums.sha256":
            checksums = asset

    if archive is None or checksums is None:
        raise MediaMTXInstallError(
            f"Latest MediaMTX release does not contain {platform_name} and checksum assets"
        )

    version = str(release_data.get("tag_name", "")).lstrip("v")
    if not version:
        raise MediaMTXInstallError("Latest MediaMTX release did not provide a version tag")
    if version.split(".", 1)[0] != "1":
        raise MediaMTXInstallError(
            f"MediaMTX {version} requires a configuration compatibility review before installation"
        )

    return MediaMTXRelease(
        version=version,
        archive_name=archive["name"],
        archive_url=archive["browser_download_url"],
        checksums_url=checksums["browser_download_url"],
    )


def _verify_checksum(archive: Path, checksums: Path, archive_name: str) -> None:
    expected = None
    for line in checksums.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == archive_name:
            expected = parts[0].lower()
            break

    if expected is None:
        raise MediaMTXInstallError(f"No checksum was published for {archive_name}")

    digest = hashlib.sha256()
    with archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)

    if digest.hexdigest() != expected:
        raise MediaMTXInstallError(f"Checksum verification failed for {archive_name}")


def install_latest(binary_directory: Path) -> MediaMTXRelease:
    release = latest_release()
    binary_directory.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="remla-mediamtx-") as temp_name:
        temp_directory = Path(temp_name)
        archive = temp_directory / release.archive_name
        checksums = temp_directory / "checksums.sha256"
        _download(release.archive_url, archive)
        _download(release.checksums_url, checksums)
        _verify_checksum(archive, checksums, release.archive_name)

        with tarfile.open(archive, "r:gz") as package:
            members = [
                member
                for member in package.getmembers()
                if member.name == "mediamtx" and member.isfile()
            ]
            if len(members) != 1:
                raise MediaMTXInstallError("MediaMTX archive does not contain the expected binary")
            source = package.extractfile(members[0])
            if source is None:
                raise MediaMTXInstallError("Could not read the MediaMTX binary from its archive")

            temporary_binary = binary_directory / ".mediamtx.remla-update"
            try:
                with temporary_binary.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                temporary_binary.chmod(0o755)
                os.replace(temporary_binary, binary_directory / "mediamtx")
            finally:
                temporary_binary.unlink(missing_ok=True)

    return release
