import subprocess
import requests
import tarfile
import os
import functools
import typer
import sys
import time
import psutil

from remla.typerHelpers import *
from pathlib import Path
import logging
import pigpio
try:
    import RPi.GPIO as rpi_gpio
except Exception:
    rpi_gpio = None
from rich.progress import track
from rich.prompt import IntPrompt
import shutil
from remla.settings import *
import re
from contextlib import contextmanager
from typing import Callable
from remla.customvalidators import *
from remla.yaml import yaml

ARDUCAM_I2C_ADDR = "0x70"
ARDUCAM_CHANNEL_BYTES = [0x04, 0x05, 0x06, 0x07]  # index 0->a,1->b,2->c,3->d


def get_camera_logger() -> logging.Logger:
    """Return a configured logger that writes to `logsDirectory / 'camera_cycle.log'`.
    Creates the logs directory if needed and ensures the handler isn't duplicated.
    """
    logger = logging.getLogger("remla.camera_cycle")
    if not logger.handlers:
        logsDirectory.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(logsDirectory / "camera_cycle.log")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger

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
    modifiedConf = re.sub(r'\{\{\s*mockStatePort\s*\}\}', str(mockStatePort), modifiedConf)

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
EnvironmentFile=-{serviceEnvironmentPath}
Environment="PATH={binPath}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
StandardOutput=append:/var/log/remla.log
StandardError=append:/var/log/remla.log
RuntimeDirectory=remla
RuntimeDirectoryMode=0755

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

def select_arducam_channel_index(index: int, bus: int = 1, control_pins: list | None = None) -> bool:
    """
    Select channel by zero-based index (0=a,1=b,2=c,3=d) using the same i2c bytes
    used by ArduCamMultiCamera.camerai2c.
    Returns True on success.
    """
    logger = get_camera_logger()
    if index < 0 or index >= len(ARDUCAM_CHANNEL_BYTES):
        logger.error("select_arducam_channel_index: invalid index %s", index)
        return False

    val = ARDUCAM_CHANNEL_BYTES[index]

    # Map index -> gpio outputs (SEL, EN1, EN2) as ints (0/1)
    pin_map = {
        0: (0, 0, 1),
        1: (1, 0, 1),
        2: (0, 1, 0),
        3: (1, 1, 0),
    }
    sel_vals = pin_map.get(index)

    # Try pigpio first for GPIO writes (only if control_pins provided)
    wrote_gpio = False
    try:
        logger.info("Attempting to use pigpio for GPIO control")
        pi = pigpio.pi()
        pins = control_pins
        if pins and pi and getattr(pi, "connected", False):
            if len(pins) >= 3:
                for pin, out in zip(pins[:3], sel_vals):
                    try:
                        logger.info("Setting pigpio pin %s to %s", pin, out)
                        pi.set_mode(int(pin), pigpio.OUTPUT)
                        pi.write(int(pin), int(out))
                    except Exception:
                        logger.exception("pigpio write failed for pin %s", pin)
                wrote_gpio = True
        else:
            if not pi or not getattr(pi, 'connected', False):
                logger.debug("pigpio not connected; will try RPi.GPIO fallback if available")
    except Exception:
        logger.exception("pigpio attempt failed")

    # Fallback to RPi.GPIO if pigpio not available
    if not wrote_gpio and rpi_gpio is not None and control_pins:
        logger.info("Attempting to use RPi.GPIO for GPIO control")
        try:
            pins = control_pins
            if len(pins) >= 3:
                rpi_gpio.setmode(rpi_gpio.BCM)
                for pin, out in zip(pins[:3], sel_vals):
                    rpi_gpio.setup(int(pin), rpi_gpio.OUT)
                    rpi_gpio.output(int(pin), rpi_gpio.HIGH if out else rpi_gpio.LOW)
                wrote_gpio = True
                logger.info("Used RPi.GPIO fallback to set control pins %s", pins[:3])
        except Exception:
            logger.exception("RPi.GPIO fallback failed")

    # Perform I2C mux switch via i2cset (explicit external tool as requested)
    try:
        subprocess.run([
            "i2cset",
            "-y",
            str(bus),
            ARDUCAM_I2C_ADDR,
            "0x00",
            f"0x{val:02x}",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.1)
        logger.info("Selected ArduCam channel %s (i2c 0x%02x) wrote_gpio=%s", index, val, wrote_gpio)
        return True
    except FileNotFoundError:
        logger.error("i2cset not found; install i2c-tools")
        return False
    except subprocess.CalledProcessError as e:
        logger.exception("i2cset failed: %s", e)
        return False



def cycle_initialize_cameras(timeout_per_camera: int = 4) -> None:
    """
    Use the saved camera config (settings.yml -> 'camera') to cycle cameras.
    For each configured camera port:
      - select that mux channel
      - start remla.service
      - wait timeout_per_camera seconds
      - stop remla.service

    Guarding:
    - create runMarker immediately to avoid re-entry when systemctl starts the same binary
    - if remla.service is already active, skip cycling (avoid disrupting a live service)
    """
    logger = get_camera_logger()

    # # If remla.service is active, avoid cycling to not disrupt a running instance
    # try:
    #     remla_active = subprocess.run(["systemctl", "is-active", "--quiet", "remla.service"]).returncode == 0
    # except Exception:
    #     remla_active = False

    # if remla_active:
    #     logger.warning("remla.service is already active; skipping camera cycling to avoid disrupting service.")
    #     return

    # load top-level settings and find current lab
    try:
        settings_path = settingsDirectory / "settings.yml"
        settings = yaml.load(settings_path) or {}
    except Exception as e:
        logger.exception("Unable to load settings.yml: %s", e)
        return

    current_lab = settings.get("currentLab")
    if not current_lab:
        logger.info("No currentLab configured in settings.yml; skipping camera cycling.")
        return

    lab_path = remoteLabsDirectory / current_lab
    if not lab_path.exists():
        logger.warning("Lab settings file %s not found; skipping camera cycling.", lab_path)
        return

    try:
        lab_settings = yaml.load(lab_path)
    except Exception as e:
        logger.exception("Unable to load lab settings %s: %s", lab_path, e)
        return

    device_settings = lab_settings.get("devices", {})
    camera_cfg = None
    for device in device_settings.values():
        if device.get("type") == "ArduCamMultiCamera":
            camera_cfg = device
            break
    if camera_cfg is None:
        logger.info("No ArduCamMultiCamera device configured in lab settings; skipping camera cycling.")
        return

    numCameras = camera_cfg.get("numCameras", 0)
    bus = camera_cfg.get("i2cbus", 1)
    # accept multiple possible key names for control pins; keep backwards compat
    control_pins = camera_cfg.get("controlPins") or camera_cfg.get("control_pins")

    if not numCameras:
        logger.info("No cameras configured (numCameras==0); skipping camera cycling.")
        return

    logger.info("Cycling %s configured camera(s)...", numCameras)

    for ch in range(numCameras):
        logger.info("Initializing camera on channel %s...", ch)
        ok = select_arducam_channel_index(ch, bus=bus, control_pins=control_pins)
        if not ok:
            logger.warning("Skipping channel %s because selection failed.", ch)
            continue

        # hardware settle time (match original script)
        time.sleep(2)

        # restart mediamtx (matches working bash script provided)
        try:
            subprocess.run(["systemctl", "restart", "mediamtx"], check=True)
            logger.info("Restarted mediamtx for channel %s", ch)
        except subprocess.CalledProcessError as e:
            logger.exception("Failed to restart mediamtx for channel %s: %s", ch, e)
            continue

        time.sleep(timeout_per_camera)

    logger.info("Completed configured camera cycling.")

def get_boot_status() -> bool:
    """
    Check if the system has been rebooted since the last recorded boot time.
    Returns True if the system has rebooted, False otherwise.
    """
    current_boot = int(psutil.boot_time())
    # If we've already run this boot, skip
    logger = get_camera_logger()
    if runMarker.exists():
        boot_record = int(runMarker.read_text().strip())
        if boot_record != current_boot:
            logger.info("New boot detected (was %s, now %s)", boot_record, current_boot)
            runMarker.write_text(str(current_boot))
            return True
        else:
            logger.info("No new boot detected (still %s)", current_boot)
            return False
    else:
        runMarker.touch(exist_ok=True)
        runMarker.write_text(str(current_boot))
        logger.error("Boot record file missing; assuming reboot.")
        return True

