import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

import typer
from .systemHelpers import getSettings, clearDirectory, promptForNumericFile, updateRemlaNginxConf
from rich import print as rprint
from rich.prompt import Prompt, Confirm
from remla.settings import *
from remla.typerHelpers import *
from remla.web_deployment import set_website_permissions
import validators
from remla.customvalidators import domainOrHostnameValidtor, portValidator
from remla.systemHelpers import *
from typing_extensions import Annotated
from remla.yaml import yaml
from typing import Optional

app = typer.Typer(no_args_is_help=False)

@app.command(name="int")
def interactive():
    """
    Runs an interactive setup that searches files and prompts users which one they want to use.
    """
    numNetworkSettings = 3
    numWebsiteSettings = 3 # Change these if more settings are required.
    remlaSettings = getSettings()
    rprint(f"Searching {remoteLabsDirectory} for files.")
    labSelection = promptForNumericFile("Which lab file do you want to use:",
                                        remoteLabsDirectory,
                                 "*.yml",
                                 f"You don't have any labs setup. Please run `remla new` or put lab yml in the {remoteLabsDirectory} directory.")

    rprint(f"Setting up {labSelection.name}")
    labSettings = yaml.load(labSelection)
    remlaSettings["currentLab"] = labSelection.relative_to(remoteLabsDirectory)
    #TODO: Add Validation Function to check it labSettings make sense.
    networkSettings = labSettings.get("network", {})
    websiteSettings = labSettings.get("website", {})
    networkUpdate = False
    if None in networkSettings.values() or len(networkSettings) < 3:
        rprint("It looks like your network isn't fully configured. Let me help.")
        networkUpdate = True
    else:
        networkUpdate = Confirm.ask("Do you want to change your network settings?")

    if networkUpdate:
        validPort = False
        while not validPort:
            port = IntPrompt.ask("Which http port do you want your website to be accessible on?", default=8080)
            validPort = portValidator(port)
        validwsPort = False
        while not validwsPort:
            wsPort = IntPrompt.ask("Which websocket port do you want to communicate on?", default=8675)
            validwsPort = portValidator(wsPort)
            if validwsPort and port == wsPort:
                validwsPort = False
                warning("You can't use the same port as the HTTP port.")
        validDomain = False
        while not validDomain:
            domain = Prompt.ask("What domain name do you want to use? e.g. example.com, 127.0.0.1, hostname")
            validDomain = domainOrHostnameValidtor(domain)

        networkSettings["port"] = port
        networkSettings["domain"] = domain
        networkSettings["wsPort"] = wsPort


    websiteUpdate = False
    if websiteSettings.get("index") is None:
        rprint("It looks like your website isn't fully configured. Let me help.")
        websiteUpdate = True
    else:
        websiteUpdate = Confirm.ask("Do you want to change your website settings?")
    if websiteUpdate:
        question = "Which file is should act as your index.html page? (The labs main webpage)"
        indexSelection = promptForNumericFile(question,
                                              remoteLabsDirectory,
                                              "*.html",
                                              f"There are no HTML files in your {remoteLabsDirectory} directory."
                                              )
        rprint(f"You have selected {indexSelection.relative_to(remoteLabsDirectory)}")
        websiteSettings["index"] = indexSelection.relative_to(remoteLabsDirectory)


    commonStaticFolderDesire = Confirm.ask("Do you have a common static folder for all your websites?", default=False)
    commonStaticUpdate = False
    if commonStaticFolderDesire:
        staticExist =  (remoteLabsDirectory/"static").exists()
        if not staticExist:
            alert(f"You don't currently have a static folder in {remoteLabsDirectory} to copy. Will not update.")
            websiteSettings["commonStaticFolder"] =  False
        else:
            websiteSettings["commonStaticFolder"] = True
            #TODO: There may be some text substitution that we need to do here, depending on lab choice.
    else:
        websiteSettings["commonStaticFolder"] = False

    staticUpdate = Confirm.ask("Do you have a specific static folder for your labs website?", default=True)
    if staticUpdate:
        question = "Which static folder is the one for the lab you want to setup?"
        staticSelection = promptForNumericFile(question,
                                              remoteLabsDirectory,
                                              "static",
                                              f"There are no static Directories in your {remoteLabsDirectory} directory."
                                              )
        rprint(f"You have selected {staticSelection.relative_to(remoteLabsDirectory)}")
        websiteSettings["staticFolder"] = staticSelection.relative_to(remoteLabsDirectory)
    elif  websiteSettings["staticFolder"] is not None and not websiteSettings["staticFolder"].exists():
        alert(f"Your provided static folder {websiteSettings['staticFolder']} doesn't exist")
        raise typer.Abort()

    labSettings["network"] = networkSettings
    labSettings["website"] = websiteSettings
    yaml.dump(remlaSettings, settingsDirectory/"settings.yml")
    yaml.dump(labSettings, remoteLabsDirectory/remlaSettings["currentLab"])

def _setup(labSettings:dict)->None:
    networkSettings = labSettings["network"]
    websiteSettings = labSettings["website"]
    if not portValidator(networkSettings.get("port"), alertUser=False):
        raise ValueError("The website port is invalid.")
    if not portValidator(networkSettings.get("wsPort"), alertUser=False):
        raise ValueError("The WebSocket port is invalid.")
    if networkSettings["port"] == networkSettings["wsPort"]:
        raise ValueError("The website and WebSocket ports must differ.")
    if not domainOrHostnameValidtor(networkSettings.get("domain"), alertUser=False):
        raise ValueError("The website domain is invalid.")

    staging_path = Path(tempfile.mkdtemp(prefix=".remla-website-", dir=nginxWebsitePath.parent))
    try:
        copy_lab_asset(websiteSettings["index"], staging_path / "index.html")
        if websiteSettings["commonStaticFolder"]:
            copy_lab_asset(Path("static"), staging_path / "static", directory=True)
        if websiteSettings["staticFolder"] is not None:
            copy_lab_asset(websiteSettings["staticFolder"], staging_path / "static", directory=True)
        setup_js_directory = staging_path / "static" / "js"
        setup_js_directory.mkdir(parents=True, exist_ok=True)
        for filename in ("reader.js", "mediaMTXGetFeed.js", "remlaSocket.js"):
            shutil.copy(setupDirectory / filename, setup_js_directory)
        set_website_permissions(staging_path)
    except BaseException:
        shutil.rmtree(staging_path, ignore_errors=True)
        raise

    previous_config = snapshot_nginx_config()
    try:
        updateRemlaNginxConf(networkSettings["port"], networkSettings["domain"], networkSettings["wsPort"])
        subprocess.run(["nginx", "-t"], check=True)
    except BaseException:
        restore_nginx_config(previous_config)
        shutil.rmtree(staging_path, ignore_errors=True)
        raise
    try:
        return replace_website(staging_path), previous_config
    except BaseException:
        restore_nginx_config(previous_config)
        shutil.rmtree(staging_path, ignore_errors=True)
        raise


def copy_lab_asset(asset: Path | str, destination: Path, directory: bool = False) -> None:
    descriptor = open_lab_asset(asset, directory)
    try:
        if directory:
            copy_directory_descriptor(descriptor, destination)
        else:
            copy_file_descriptor(descriptor, destination)
    finally:
        os.close(descriptor)


def open_lab_asset(asset: Path | str, directory: bool = False) -> int:
    asset_path = Path(asset)
    if asset_path.is_absolute() or ".." in asset_path.parts:
        raise ValueError("Website assets must be inside the lab directory.")
    directory_descriptor = os.open(remoteLabsDirectory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in asset_path.parts[:-1]:
            next_descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_descriptor)
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if directory:
            flags |= os.O_DIRECTORY
        asset_descriptor = os.open(asset_path.name, flags, dir_fd=directory_descriptor)
    finally:
        os.close(directory_descriptor)
    asset_stat = os.fstat(asset_descriptor)
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(asset_stat.st_mode):
        os.close(asset_descriptor)
        kind = "directory" if directory else "file"
        raise ValueError(f"Website asset is not a {kind}: {asset_path}")
    return asset_descriptor


def copy_file_descriptor(source_descriptor: int, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.dup(source_descriptor), "rb") as source_file, open(destination, "wb") as destination_file:
        shutil.copyfileobj(source_file, destination_file)


def copy_directory_descriptor(source_descriptor: int, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in os.listdir(source_descriptor):
        entry = os.stat(name, dir_fd=source_descriptor, follow_symlinks=False)
        if stat.S_ISDIR(entry.st_mode):
            child_descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_descriptor)
            try:
                copy_directory_descriptor(child_descriptor, destination / name)
            finally:
                os.close(child_descriptor)
        elif stat.S_ISREG(entry.st_mode):
            child_descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_descriptor)
            try:
                if not stat.S_ISREG(os.fstat(child_descriptor).st_mode):
                    raise ValueError("Website assets cannot contain symbolic links or special files.")
                copy_file_descriptor(child_descriptor, destination / name)
            finally:
                os.close(child_descriptor)
        else:
            raise ValueError("Website assets cannot contain symbolic links or special files.")


def replace_website(staging_path: Path) -> Path | None:
    backup_path = None
    if nginxWebsitePath.exists() or nginxWebsitePath.is_symlink():
        backup_path = nginxWebsitePath.with_name(f".remla-website-previous-{staging_path.name.rsplit('-', 1)[-1]}")
        os.replace(nginxWebsitePath, backup_path)
    try:
        os.replace(staging_path, nginxWebsitePath)
    except BaseException:
        if backup_path is not None:
            os.replace(backup_path, nginxWebsitePath)
        raise
    return backup_path


def restore_nginx_config(previous_config: bytes | None) -> None:
    if previous_config is None:
        nginxConfPath.unlink(missing_ok=True)
        return
    if nginxConfPath.is_symlink():
        nginxConfPath.unlink()
    nginxConfPath.write_bytes(previous_config)


def snapshot_nginx_config() -> bytes | None:
    if not nginxConfPath.exists() and not nginxConfPath.is_symlink():
        return None
    flags = os.O_RDONLY | os.O_NONBLOCK
    if not nginxConfPath.is_symlink():
        flags |= os.O_NOFOLLOW
    descriptor = os.open(nginxConfPath, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Existing nginx configuration is not a regular file.")
        chunks = []
        while chunk := os.read(descriptor, 65536):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


@app.command("deploy-website", help="Deploy the selected lab website to nginx.")
def deploy_website():
    if os.geteuid() != 0:
        alert("Website deployment must be run as root.")
        typer.echo("Try running:")
        typer.echo("sudo remla setup deploy-website")
        raise typer.Abort()

    remlaSettings = getSettings()
    current_lab = remlaSettings.get("currentLab")
    if current_lab is None:
        alert("Select a lab before deploying its website.")
        raise typer.Abort()

    lab_path = remoteLabsDirectory / current_lab
    if not lab_path.is_file():
        alert(f"The selected lab file does not exist: {lab_path}")
        raise typer.Abort()

    backup_path, previous_config = _setup(yaml.load(lab_path))
    try:
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
    except BaseException:
        restore_nginx_config(previous_config)
        if backup_path is not None:
            failed_path = backup_path.with_name(f".remla-website-failed-{backup_path.name.rsplit('-', 1)[-1]}")
            os.replace(nginxWebsitePath, failed_path)
            os.replace(backup_path, nginxWebsitePath)
            shutil.rmtree(failed_path, ignore_errors=True)
        raise
    if backup_path is not None:
        shutil.rmtree(backup_path)
    success("Deployed the selected lab website.")

@app.command()
def lab(labfile: Annotated[str, typer.Argument()],
        port: Annotated[int, typer.Option()]=None,
        wsport: Annotated[int,typer.Option()]=None,
        domain: Annotated[str, typer.Option()]=None,
        cstaticon: Annotated[bool, typer.Option()]=False,
        cstaticoff: Annotated[bool,typer.Option()]=False,
        staticfolder: Annotated[str, typer.Option()]=None,
        ):
    labFileSuffix = Path(labfile).suffix

    if not labFileSuffix == ".yml":
        alert("The lab file you provided is not a yml file.")
        raise typer.Abort()
    labfile = labfile.strip("/")


    alertMsg = f"No files with name {labfile} exist in {remoteLabsDirectory}"
    potentialLabs = searchForFilePattern(remoteLabsDirectory, labfile, (alertMsg, alert))
    warnMsg = f"You have duplicate files with name {labfile} within {remoteLabsDirectory}."
    if not uniqueValidator(potentialLabs, (warnMsg,warning), processMethod=lambda x: x.name, abort=False):
        labFilePath = promptForNumericFile("Select which version you want.", remoteLabsDirectory, labfile)
    else:
        labFilePath = remoteLabsDirectory / potentialLabs[0]

    remlaSettings = getSettings()
    remlaSettings["currentLab"] = labFilePath.relative_to(remoteLabsDirectory)
    labSettings = yaml.load(labFilePath)

    # If the user doesn't provide changes to the settings when setting up the lab
    # then load them in from the settings file.
    if port is None:
        port = labSettings["network"]["port"]
    if wsport is None:
        wsPort = labSettings["network"]["wsPort"]
    else:
        wsPort = wsport
    if domain is None:
        domain = labSettings["network"]["domain"]
    if not cstaticon and not cstaticoff:
        commonStaticFolder = labSettings["website"]["commonStaticFolder"]
    elif cstaticon:
        commonStaticFolder = True
    else:
        commonStaticFolder = False
    if staticfolder is None:
        staticFolder = labSettings["website"]["staticFolder"]
    else:
        staticFolder = staticfolder

    if not portValidator(port):
        raise typer.Abort()
    if not portValidator(wsPort):
        raise typer.Abort()
    elif wsPort == port:
        alert("The http port and the websocket port can't be the same!")
        raise typer.Abort()
    if not domainOrHostnameValidtor(domain):
        raise typer.Abort()

    if labSettings["website"]["index"] is None:
        alert("You haven't send an index.html file in your settings file. Please update before continuing or run `remla setup int` for guidance through a set up.")
        raise typer.Abort()
    elif not (remoteLabsDirectory/labSettings["website"]["index"]).exists():
        alert(f"Your index file in your settings doesn't exist at {labSettings['website']['index']}. Please update before continuing or run `remla setup int` for guidance through a set up.")
        raise typer.Abort()

    labSettings["network"]["port"] = port
    labSettings["network"]["wsPort"] = wsPort
    labSettings["network"]["domain"] = domain
    labSettings["website"]["commonStaticFolder"] = commonStaticFolder
    labSettings["website"]["staticFolder"] = staticFolder

    yaml.dump(labSettings, labFilePath)
    yaml.dump(remlaSettings, settingsDirectory/"settings.yml")





if __name__=="__main__":
    app()
