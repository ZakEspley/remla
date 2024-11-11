import subprocess
import requests
import tarfile
import os
import functools
import typer
import sys

from remla.typerHelpers import *
from pathlib import Path
from rich.progress import track
from rich.prompt import IntPrompt
import shutil
from remla.settings import *
import re
from contextlib import contextmanager
from typing import Callable
from remla.customvalidators import *
from remla.yaml import yaml

def is_package_installed(package_name):
    try:
        # Attempt to show the package information
        # This is for Debian based OS's like Raspberry Pi Os
        subprocess.run(["dpkg", "-s", package_name], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        # The command failed, which likely means the package is not installed
        return False


def enable_service(service_name:str):
    try:
        subprocess.run(["sudo", "systemctl", "enable", service_name], check=True)
        success(f"Service {service_name} enabled successfully.")
        return True
    except subprocess.CalledProcessError as e:
        alert(f"Failed to enable {service_name}: {e}")
        return False

def download_and_extract_tar(url:str, savePath:Path, folderName:str):
    # Download the file
    response = requests.get(url, stream=True)
    # Check if the request was successful
    if response.status_code == 200:
        # Open a file to write the content of the download
        fileName = url.split("/")[-1]
        totalSizeInBytes = int(response.headers.get("content-length",0))
        saveLocation = savePath / fileName
        with open(saveLocation, "xb") as file:
            # Iterate over the response data in chunks (e.g., 4KB chunks)
            for chunk in track(response.iter_content(chunk_size=4096), description="Downloading...", total=totalSizeInBytes//4096):
                file.write(chunk)
        typer.echo("Extracting file...")
        # Extract the tar file
        extractPath = savePath / folderName
        with tarfile.open(saveLocation, "r:gz") as tar:
            tar.extractall(path=extractPath)
        # Optionally, remove the tar file after extraction
        os.remove(saveLocation)
        return True
    else:
        return False


def checkFileFullName(folderPath: Path, filePattern: str):
    """
    Check if a file matching a certain pattern exists in a specified folder.

    :param folderPath: Path to the folder where to search for the file.
    :param filePattern: The pattern to match the file names against.
    :return: Return first found matching file name, False otherwise.
    """
    folder = Path(folderPath)
    # Use glob to find matching files. This returns a generator.
    matchingFiles = folder.glob(filePattern)

    # Attempt to get the first matching file. If none exist, None is returned.
    try:
        firstMatch = next(matchingFiles)
        # If we get here, a matching file exists
        return firstMatch
    except StopIteration:
        # If no matching file exists, a StopIteration exception is caught
        return False

def moveAndOverwrite(source:Path, dest:Path):
    if dest.is_dir():
        (dest / source.name).unlink(missing_ok=True)
    else:
        dest.unlink(missing_ok=True)
    shutil.move(source, dest)

def getSettings():
    dir = Path(typer.get_app_dir(APP_NAME))
    # with open(dir, "r") as file:
    #     settingsString = file.read()

    return yaml.load(dir/"settings.yml")

def clearDirectory(directory: Path) -> None:
    if directory.exists() and directory.is_dir():
        for item in directory.iterdir():
            if item.is_dir():
                shutil.rmtree(item)  # Recursively remove directories
            else:
                item.unlink()  # Remove files
        # print(f"All files and directories removed from {directory}")
    else:
        print(f"The specified path {directory} is not a valid directory")

def searchForFilePattern(directory:Path, pattern:str, invalidMsg:tuple[str,Callable[[str],None]]|None=None, abort:bool=True) -> list:
    files = list(directory.rglob(pattern))
    numOfFiles = len(files)

    if numOfFiles == 0:
        if invalidMsg is not None:
            msgType = invalidMsg[1]
            msg = invalidMsg[0]
            msgType(msg)
        if abort:
            raise typer.Abort()
    return files



def promptForNumericFile(prompt:str, directory:Path, pattern:str, warnMsg:str|None=None, abort:bool=True) -> Path:
    files = searchForFilePattern(directory,pattern, (warnMsg, warning), abort)
    # msg = f"Multiple files with the same name found in {remoteLabsDirectory}. Lab names must be unqiue."
    # uniqueValidator(files, (msg, alert))
    numOfFiles = len(files)
    if not prompt.endswith("\n"):
        prompt += "\n"
    for i, file in enumerate(files):
        prompt += f"{i + 1}. {file.relative_to(directory)}\n"
    choice = IntPrompt.ask(prompt, choices=[str(i + 1) for i in range(numOfFiles)]) - 1
    return files[choice]

def updateRemlaNginxConf(port: int, domain:str, wsPort:int) -> None:
    nginxInitialConfPath = setupDirectory / "localhost.conf"
    # Read in the file
    with open(nginxInitialConfPath, "r") as file:
        nginxInitialConf = file.read()
    # Use re.sub() to replace all instances of {{ settingsDirectory }} with the settingsDirectory
    modifiedConf = re.sub(r'\{\{\s*settingsDirectory\s*\}\}', str(settingsDirectory), nginxInitialConf)
    modifiedConf = re.sub(r'\{\{\s*nginxWebsitePath\s*\}\}', str(nginxWebsitePath), modifiedConf)
    modifiedConf = re.sub(r'\{\{\s*port\s*\}\}', str(port), modifiedConf)
    modifiedConf = re.sub(r'\{\{\s*hostname\s*\}\}', domain, modifiedConf)
    modifiedConf = re.sub(r'\{\{\s*wsPort\s*\}\}', str(wsPort), modifiedConf)

    modifiedConfPath = settingsDirectory / "remla.conf"
    # with normalUserPrivileges():
    with open(modifiedConfPath, "w") as file:
        file.write(modifiedConf)
    # writeFileAsUser(modifiedConfPath, modifiedConf)
    nginxAvailableSymPath = nginxAvailablePath / "remla.conf"
    if not nginxAvailableSymPath.exists():
        nginxAvailableSymPath.symlink_to(modifiedConfPath)
    nginxEnableSymPath = nginxEnabledPath / "remla.conf"
    if not nginxEnableSymPath.exists():
        nginxEnableSymPath.symlink_to(nginxAvailableSymPath)

def runAsUser(func:callable, *args, **kwargs):
    currentUid = os.geteuid()
    os.setuid(1000)
    result = func(*args, **kwargs)
    os.seteuid(currentUid)
    return result

def writeFileAsUser(file:Path, contents:str):
    currentUid = os.geteuid()
    os.setuid(1000)
    with open(file, "w") as f:
        f.write(contents)
    os.seteuid(currentUid)

@contextmanager
def normalUserPrivileges():
    original_euid = os.geteuid()
    original_egid = os.getegid()
    normal_uid = 1000
    normal_gid = 1000

    try:
        # Drop to normal user privileges
        os.setegid(normal_gid)
        os.seteuid(normal_uid)
        yield
    finally:
        # Restore to original user and group IDs
        os.seteuid(original_euid)
        os.setegid(original_egid)


def createServiceFile(echo=False):
    # Finding the path to the 'remla' executable
    executablePath = subprocess.check_output(['which', 'remla'], text=True).strip()
    executablePath = Path(executablePath)
    if not executablePath.exists():
        raise FileNotFoundError("The 'remla' executable was not found in the expected path.")

    # Setting the PATH environment variable
    binPath = executablePath.parent  # Assuming the 'remla' binary's directory includes the necessary Python environment
    user = homeDirectory.owner()
    # Service file content
    serviceContent = f"""
[Unit]
Description=Remla
After=network.target
        
[Service]
User={user}
Group={user}
WorkingDirectory={remoteLabsDirectory}
ExecStart={executablePath} run {"-w" if echo else ""} -f
ExecStartPre=/bin/sleep 5
Restart=always
Environment="PATH={binPath}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
StandardOutput=append:/var/log/remla.log
StandardError=append:/var/log/remla.log


[Install]
WantedBy=multi-user.target
"""

    # Writing the service file
    serviceFilePath = Path('/etc/systemd/system/remla.service')
    serviceFilePath.write_text(serviceContent)
    try:
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        success(f"Service file created at {serviceFilePath}")
    except subprocess.SubprocessError:
        alert("Could not restart remla daemon.")


def cleanupPID():
    typer.echo("Cleaning up...")
    if os.path.exists(pidFilePath):
        os.remove(pidFilePath)
    sys.exit(0)

def getCallingUserID():
    sudo_uid = os.environ.get("SUDO_UID")
    if sudo_uid:
        return int(sudo_uid)
    else:
        # If SUDO_UID is not set, fall back to the current user's ID
        return os.getuid()

def bothOrNoneAssigned(x, y):
    if x is None and y is None:
        return True
    elif x is not None and y is not None:
        return True
    else:
        return False

# def runAsUser(nonPrivilegedUid=1000):
#     def decoratorRunAsUser(func):
#         @functools.wraps(func)
#         def wrapperRunAsUser(*args, **kwargs):
#             currentUid = os.geteuid()
#             try:
#                 # Switch to non-privileged user
#                 os.seteuid(nonPrivilegedUid)
#                 result = func(*args, **kwargs)
#             finally:
#                 # Always switch back to the original user
#                 os.seteuid(currentUid)
#             return result
#         return wrapperRunAsUser
#     return decoratorRunAsUser
