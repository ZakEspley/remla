import grp
import os
import re
import tempfile
from pathlib import Path

from remla.settings import secretsDirectory


SECRET_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


def secret_path(name: str, directory: Path = secretsDirectory) -> Path:
    if not SECRET_NAME.fullmatch(name):
        raise ValueError("Secret names use lowercase letters, digits, and hyphens")
    return directory / name


def set_secret(name: str, value: str, directory: Path = secretsDirectory) -> None:
    if not value:
        raise ValueError("Secret value cannot be empty")
    directory.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chown(directory, 0, grp.getgrnam("remla").gr_gid)
    os.chmod(directory, 0o750)
    path = secret_path(name, directory)
    descriptor, temporary_name = tempfile.mkstemp(dir=directory)
    try:
        os.write(descriptor, value.encode())
        os.fchmod(descriptor, 0o640)
    finally:
        os.close(descriptor)
    os.chown(temporary_name, 0, grp.getgrnam("remla").gr_gid)
    Path(temporary_name).replace(path)


def list_secrets(directory: Path = secretsDirectory) -> list[str]:
    if not directory.exists():
        return []
    return sorted(path.name for path in directory.iterdir() if path.is_file() and SECRET_NAME.fullmatch(path.name))


def remove_secret(name: str, directory: Path = secretsDirectory) -> None:
    secret_path(name, directory).unlink()
