from pathlib import Path


class WorkspaceLinkError(RuntimeError):
    pass


def create_workspace_link(workspace: Path, lab_root: Path) -> bool:
    workspace = workspace.expanduser()
    lab_root = lab_root.expanduser()
    is_lab_root = workspace.absolute() == lab_root.absolute()
    try:
        lab_root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise WorkspaceLinkError(f"could not create lab root {lab_root}: {error}") from error

    if is_lab_root:
        return False

    if workspace.is_symlink():
        try:
            workspace_target = workspace.resolve()
        except (OSError, RuntimeError) as error:
            raise WorkspaceLinkError(f"could not resolve workspace link {workspace}: {error}") from error
        if workspace_target == lab_root.resolve():
            return False
        raise WorkspaceLinkError(f"{workspace} already points to {workspace_target}")
    if workspace.exists():
        raise WorkspaceLinkError(f"{workspace} already exists and is not a workspace link")
    try:
        workspace.parent.mkdir(parents=True, exist_ok=True)
        workspace.symlink_to(lab_root, target_is_directory=True)
    except OSError as error:
        raise WorkspaceLinkError(f"could not create workspace link {workspace}: {error}") from error
    return True
