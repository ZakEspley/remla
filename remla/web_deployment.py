import os
from pathlib import Path
import stat


def set_website_permissions(website_root: Path) -> None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        root_descriptor = os.open(website_root, flags)
    except OSError as error:
        raise RuntimeError(f"could not safely open website root {website_root}: {error}") from error
    try:
        _set_directory_permissions(root_descriptor)
    finally:
        os.close(root_descriptor)


def _set_directory_permissions(directory_descriptor: int) -> None:
    directory = os.fstat(directory_descriptor)
    if not stat.S_ISDIR(directory.st_mode):
        raise RuntimeError("website root is not a directory")
    os.fchown(directory_descriptor, 0, 0)
    os.fchmod(directory_descriptor, 0o755)

    for name in os.listdir(directory_descriptor):
        try:
            entry = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(entry.st_mode):
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        elif stat.S_ISREG(entry.st_mode):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        else:
            continue
        try:
            file_descriptor = os.open(name, flags, dir_fd=directory_descriptor)
        except (FileNotFoundError, OSError):
            continue
        try:
            entry = os.fstat(file_descriptor)
            if stat.S_ISDIR(entry.st_mode):
                _set_directory_permissions(file_descriptor)
            elif stat.S_ISREG(entry.st_mode):
                os.fchown(file_descriptor, 0, 0)
                os.fchmod(file_descriptor, 0o644)
        finally:
            os.close(file_descriptor)
