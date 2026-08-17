import asyncio
import datetime
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import typer
import websockets
from rich import print as rprint
from rich.markdown import Markdown
from rich.prompt import IntPrompt
from rich.text import Text
from typing_extensions import Annotated

from remla import i2ccmd, setupcmd
from remla.labcontrol.Controllers import *
from remla.labcontrol.Experiment import Experiment
from remla.mediamtx import MediaMTXInstallError, install_latest
from remla.settings import *
from remla.systemHelpers import *
from remla.typerHelpers import *
from remla.yaml import createDevicesFromYml, yaml

from .customvalidators import *

__version__ = "0.3.3.dev24"


def version_callback(value: bool):
    if value:
        print(f"Remla Version: {__version__}")
        raise typer.Exit()


app = typer.Typer(pretty_exceptions_show_locals=False)
camera_app = typer.Typer(no_args_is_help=True)
mediamtx_app = typer.Typer(no_args_is_help=True)
app.add_typer(setupcmd.app, name="setup")
app.add_typer(i2ccmd.app, name="i2c")
app.add_typer(camera_app, name="camera")
app.add_typer(mediamtx_app, name="mediamtx")


@app.callback()
def version(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Print the version and exit",
    ),
):
    pass


@app.command()
def showconfig():
    typer.echo(settingsDirectory)


def _install_remla_overlays() -> None:
    for overlay_path in remlaOverlayPaths:
        if not overlay_path.exists():
            alert(
                f"Missing packaged overlay: {overlay_path}\n"
                "Build the REMLA camera mux overlays from the Raspberry Pi kernel overlay source "
                "and place them in remla/overlays before installing alternate-bus camera mux support."
            )
            raise typer.Abort()

    if not bootOverlayDirectory.exists():
        alert(f"Could not find Raspberry Pi overlay directory at {bootOverlayDirectory}")
        raise typer.Abort()

    for overlay_path in remlaOverlayPaths:
        target = bootOverlayDirectory / overlay_path.name
        shutil.copy2(overlay_path, target)
        success(f"Installed {target}")


@app.command(
    "install-overlays",
    help="Install REMLA Device Tree overlays into /boot/firmware/overlays.",
)
def install_overlays():
    if os.geteuid() != 0:
        alert("This command must be run as root.")
        typer.echo("Try running:")
        typer.echo("sudo remla install-overlays")
        raise typer.Abort()

    _install_remla_overlays()


@camera_app.command("init", help="Initialize the configured multi-camera mux by setting its GPIO and I2C channel.")
def camera_init(
    slot: Annotated[
        Optional[str],
        typer.Option(
            "--slot",
            "-s",
            help="Camera slot or camera name to select. Defaults to the configured initialCamera.",
        ),
    ] = None,
):
    if os.geteuid() != 0:
        alert("This command must be run as root.")
        typer.echo("Try running:")
        typer.echo("sudo remla camera init")
        raise typer.Abort()

    remla_settings_path = settingsDirectory / "settings.yml"
    if not remla_settings_path.exists():
        alert(f"Could not find settings file at {remla_settings_path}")
        raise typer.Abort()

    remla_settings = yaml.load(remla_settings_path)
    current_lab = remla_settings.get("currentLab")
    if not current_lab:
        alert("No current lab is configured in settings.yml")
        raise typer.Abort()

    current_lab_settings_path = remoteLabsDirectory / current_lab
    if not current_lab_settings_path.exists():
        alert(f"Lab settings file does not exist at {current_lab_settings_path}")
        raise typer.Abort()

    lab_settings = yaml.load(current_lab_settings_path)
    devices = lab_settings.get("devices", {})

    camera_name = None
    camera_details = None
    for name, details in devices.items():
        if details.get("type") in {"PiCamera2MultiCam", "ArduCamMultiCamera"}:
            camera_name = name
            camera_details = details
            break

    if camera_details is None:
        alert("No multi-camera device is configured for the current lab.")
        raise typer.Abort()

    configured_i2cbus = camera_details.get("i2cbus", 11)
    try:
        i2cbus = resolve_i2c_bus(configured_i2cbus)
    except RuntimeError as exc:
        alert(str(exc))
        raise typer.Abort()
    control_pins = camera_details.get("controlPins", [4, 17, 18])
    camera_names = camera_details.get("cameraNamesDict") or {}
    initial_camera = str(camera_details.get("initialCamera", "a")).lower()
    slot_order = ["a", "b", "c", "d"]

    requested = str(slot or initial_camera).lower()
    if requested in camera_names:
        resolved_slot = str(camera_names[requested]).lower()
    else:
        resolved_slot = requested

    if resolved_slot not in slot_order:
        alert(
            f"Invalid camera selection '{requested}'. Use one of {slot_order} or a configured camera name."
        )
        raise typer.Abort()

    ok = select_arducam_channel_index(
        slot_order.index(resolved_slot),
        bus=i2cbus,
        control_pins=list(control_pins),
    )
    if not ok:
        alert(
            f"Failed to initialize camera mux for device '{camera_name}' on slot '{resolved_slot}'."
        )
        raise typer.Abort()

    success(
        f"Initialized multi-camera mux for '{camera_name}' to slot '{resolved_slot}' "
        f"(requested '{requested}') on I2C bus {i2cbus}."
    )

    video_nodes = sorted(Path("/dev").glob("video*"))
    if video_nodes:
        typer.echo("Detected V4L2 video device nodes:")
        for node in video_nodes:
            typer.echo(f"  - {node}")
    else:
        warning(
            "No /dev/video* nodes are present. On Raspberry Pi OS Bookworm this can still be normal "
            "when using the libcamera/Picamera2 stack."
        )

    probe_commands = [
        ["rpicam-hello", "--list-cameras"],
        ["libcamera-hello", "--list-cameras"],
    ]
    for probe_cmd in probe_commands:
        if shutil.which(probe_cmd[0]) is None:
            continue
        typer.echo(f"Probing camera stack with: {' '.join(probe_cmd)}")
        result = subprocess.run(probe_cmd, capture_output=True, text=True)
        output = (result.stdout or "").strip()
        errors = (result.stderr or "").strip()
        if output:
            typer.echo(output)
        if errors:
            typer.echo(errors)
        if result.returncode == 0:
            success(
                "The libcamera stack can see at least one camera. "
                "If you still expected /dev/video0, that is a separate V4L2 compatibility issue."
            )
        else:
            warning(
                "The camera mux was selected, but the Raspberry Pi camera stack still did not detect a camera. "
                "This usually means the active mux channel, sensor overlay, or hardware path still needs attention."
            )
        break
    else:
        warning(
            "Neither rpicam-hello nor libcamera-hello is installed, so remla could not verify camera detection "
            "after selecting the mux channel."
        )


@app.command(
    help="Run this to initilize your remla setup. It will make sure you have "
    "the correct dependencies installed, as well as the install mediamtx for "
    "you. It will then then take you through setting up your hardware. Just "
    "answer the questions and it will setup everything for you"
)
def init():
    ####### Verify that we are running as sudo ######
    if os.geteuid() != 0:
        alert("This script must be run as root.")
        typer.echo("Try running:")
        typer.echo("sudo remla init")
        raise typer.Abort()

    ####### Make config directory and others #########
    settingsDirectory.mkdir(parents=True, exist_ok=True)
    logsDirectory.mkdir(parents=True, exist_ok=True)
    websiteDirectory.mkdir(parents=True, exist_ok=True)
    websiteStaticDirectory.mkdir(parents=True, exist_ok=True)
    websiteJSDirectory.mkdir(parents=True, exist_ok=True)
    websiteCSSDirectory.mkdir(parents=True, exist_ok=True)
    websiteImgsDirectory.mkdir(parents=True, exist_ok=True)
    remoteLabsDirectory.mkdir(parents=True, exist_ok=True)

    ####### Enable I2C #######
    remlaPanel("Turning on I2C on your raspberry pi.")
    try:
        subprocess.run(
            ["sudo", "raspi-config", "nonint", "do_i2c", "0"], check=True
        )  # 0 mean true in bash I guess
        success("Turned on I2C")
    except subprocess.CalledProcessError as e:
        alert(f"Failed to turn on I2C with error {e}")
        raise typer.Abort()

    ####### Check to see if apt required packages are installed.  ###########
    remlaPanel("Verifying required apt packages are installed.")
    packagesToCheck = ["nginx", "python3-pip", "i2c-tools", "pigpio", "python3-pigpio"]
    packagesNeeded = []
    for package in packagesToCheck:
        if not is_package_installed(package):
            packagesNeeded.append(package)
    if len(packagesNeeded) != 0:
        alert("You have missing required packages!")
        typer.echo("Please run the following command:")
        typer.echo(f"sudo apt install {' '.join(packagesNeeded)}")
        raise typer.Abort()
    success("All required packages are installed!")

    ###### Turn on PIGPIOD to run at start
    typer.echo("Turning on pigpiod to start at boot.")
    echoResult(
        enable_service("pigpiod"),
        "pigiod will start at boot",
    )

    ####### Installing mediamtx for the user by downloading it from github, unpacking it, and moving files.
    _mediamtx()

    ####### Seting up NGINX for the user now ############
    _nginx()

    ####### Create an initial settings file #############
    _createSettingsFile()
    ####### Create a remla.service daemon   #############
    createServiceFile(echo=True)
    createRemlaPolicy()

    interactivesetup()
    typer.echo("Wrapping up install...")
    # perform initial camera cycling once per boot (if configured)
    try:
        if not runMarker.exists():
            rprint("Performing initial camera cycle (first-time this boot)...")
            cycle_initialize_cameras(timeout_per_camera=4)
    except Exception as e:
        warning(f"Initial camera cycling failed or skipped: {e}")
    subprocess.run(["sudo", "systemctl", "daemon-reload"])
    subprocess.run(["sudo", "systemctl", "restart", "remla.service"])
    enable_service("remla")
    # alert("Running test websocket server. Press Ctrl-C when you are done testing.")
    # run(wstest=True)


def _write_mediamtx_settings():
    mediamtx_settings = yaml.load(setupDirectory / "mediamtx.yml")
    mediamtx_settings["logFile"] = str(logsDirectory / "mediamtx.log")
    mediamtxSettingsLocation.mkdir(parents=True, exist_ok=True)
    target = mediamtxSettingsLocation / "mediamtx.yml"
    if target.exists():
        shutil.copy2(target, target.with_suffix(".yml.previous"))

    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=mediamtxSettingsLocation,
        prefix="mediamtx-",
        suffix=".yml",
        delete=False,
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
        yaml.dump(mediamtx_settings, temporary_file)
    os.replace(temporary_path, target)


def _restore_file(target: Path, backup: Path, existed: bool):
    if existed:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.name}-restore-",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        try:
            shutil.copy2(backup, temporary_path)
            os.replace(temporary_path, target)
        finally:
            temporary_path.unlink(missing_ok=True)
    else:
        target.unlink(missing_ok=True)


def _restore_mediamtx_installation(
    backup_directory: Path,
    had_binary: bool,
    had_settings: bool,
    had_service: bool,
    service_was_active: bool,
    service_was_enabled: bool,
    remla_was_active: bool,
):
    binary = mediamtxBinaryLocation / "mediamtx"
    settings = mediamtxSettingsLocation / "mediamtx.yml"
    service = Path("/etc/systemd/system/mediamtx.service")
    if not had_service:
        subprocess.run(["systemctl", "disable", "--now", "mediamtx"], check=False)
    _restore_file(binary, backup_directory / "mediamtx", had_binary)
    _restore_file(settings, backup_directory / "mediamtx.yml", had_settings)
    _restore_file(service, backup_directory / "mediamtx.service", had_service)

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    if service_was_enabled:
        subprocess.run(["systemctl", "enable", "mediamtx"], check=True)
    elif had_service:
        subprocess.run(["systemctl", "disable", "mediamtx"], check=True)
    if service_was_active:
        subprocess.run(["systemctl", "restart", "mediamtx"], check=True)
    elif had_service:
        subprocess.run(["systemctl", "stop", "mediamtx"], check=True)
    if remla_was_active:
        subprocess.run(["systemctl", "restart", "remla.service"], check=True)


def _mediamtx():
    remlaPanel("Installing the latest MediaMTX release")
    binary = mediamtxBinaryLocation / "mediamtx"
    settings = mediamtxSettingsLocation / "mediamtx.yml"
    service = Path("/etc/systemd/system/mediamtx.service")
    had_binary = binary.exists()
    had_settings = settings.exists()
    had_service = service.exists()
    service_was_active = (
        subprocess.run(["systemctl", "is-active", "--quiet", "mediamtx"]).returncode == 0
    )
    service_was_enabled = (
        subprocess.run(["systemctl", "is-enabled", "--quiet", "mediamtx"]).returncode == 0
    )
    remla_was_active = (
        subprocess.run(["systemctl", "is-active", "--quiet", "remla.service"]).returncode
        == 0
    )

    with tempfile.TemporaryDirectory(prefix="remla-mediamtx-backup-") as backup_name:
        backup_directory = Path(backup_name)
        if had_binary:
            shutil.copy2(binary, backup_directory / "mediamtx")
        if had_settings:
            shutil.copy2(settings, backup_directory / "mediamtx.yml")
        if had_service:
            shutil.copy2(service, backup_directory / "mediamtx.service")

        try:
            release = install_latest(mediamtxBinaryLocation)
            success(f"Installed MediaMTX {release.version}")
            typer.echo("Writing REMLA MediaMTX settings")
            _write_mediamtx_settings()
            shutil.copy(setupDirectory / "mediamtx.service", service)
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "enable", "mediamtx"], check=True)
            subprocess.run(["systemctl", "restart", "mediamtx"], check=True)
            time.sleep(1)
            subprocess.run(["systemctl", "is-active", "--quiet", "mediamtx"], check=True)
            if remla_was_active:
                subprocess.run(["systemctl", "restart", "remla.service"], check=True)
        except (MediaMTXInstallError, OSError, subprocess.CalledProcessError) as exc:
            try:
                _restore_mediamtx_installation(
                    backup_directory,
                    had_binary,
                    had_settings,
                    had_service,
                    service_was_active,
                    service_was_enabled,
                    remla_was_active,
                )
            except (OSError, subprocess.CalledProcessError) as rollback_exc:
                alert(f"MediaMTX update failed and rollback also failed: {exc}; {rollback_exc}")
            else:
                alert(f"MediaMTX update failed and the previous installation was restored: {exc}")
            raise typer.Abort() from exc

    success(f"MediaMTX {release.version} is installed and running")
    if remla_was_active:
        success("Restarted the REMLA service")
    return release


@mediamtx_app.command(
    "update", help="Install the latest MediaMTX release and REMLA configuration."
)
def mediamtx_update():
    if os.geteuid() != 0:
        alert("This command must be run as root.")
        typer.echo("Try running:")
        typer.echo("sudo remla mediamtx update")
        raise typer.Abort()

    logsDirectory.mkdir(parents=True, exist_ok=True)
    _mediamtx()


def _nginx():
    logsDirectory.mkdir(parents=True, exist_ok=True)
    typer.echo("Setting up NGINX")
    # Make directory for the running website.
    # nginxWebsitePath.mkdir(parents=True, exist_ok=True)

    shutil.copy(setupDirectory / "reader.js", websiteJSDirectory)
    shutil.copy(setupDirectory / "mediaMTXGetFeed.js", websiteJSDirectory)

    updateRemlaNginxConf(8080, hostname, 8675)

    updatedHtml = updateFinalInfo(setupDirectory / "index.html")
    # Write the processed HTML to a new file or use as needed
    with open(websiteDirectory / "index.html", "w") as file:
        file.write(updatedHtml)

    shutil.copytree(websiteDirectory, nginxWebsitePath, dirs_exist_ok=True)

    typer.echo("Making NGINX run at boot")
    echoResult(
        enable_service("nginx"),
        "NGINX can now run at boot.",
        "Failed to allow NGINX to start at boot.",
    )
    subprocess.run(["sudo", "systemctl", "reload", "nginx"])
    success("NGINX setup complete.")
    # Change Permission so NGINX can access files
    # homeDirectory.chmod(0o755)


@app.command()
def interactivesetup():
    user = homeDirectory.owner()
    message = "Note that remla currently only works with Raspberry Pi 4! If you are using a newer model, you will need do this manually."
    remlaPanel(message)
    (cont_int,) = (
        typer.confirm("Do you want to continue with interactive install?", default="y"),
    )
    if not cont_int:
        return
    allowedSensors = ["ov5647", "imx219", "imx477", "imx708", "imx519", "other"]
    sensorQuestionString = "Select which type of sensor you will be using [1-5]:\n"
    for i, sensor in enumerate(allowedSensors):
        sensorQuestionString += f"  {i+1}. {sensor} \n"
    sensorIdx = (
        IntPrompt.ask(sensorQuestionString, choices=["1", "2", "3", "4", "5", "6"]) - 1
    )
    customSensor = False
    if sensorIdx == 5:
        customSensor = True
        sensor = typer.prompt(
            "Please provide the name of your sensor as required by raspberry pi or arducam (make sure you know what you are doing)",
            confirmation_prompt=True,
        )
    else:
        sensor = allowedSensors[sensorIdx]

    while True:
        numCameras = IntPrompt.ask(
            "How many cameras will you be using?", choices=["1", "2", "3", "4"]
        )
        cameraChoices = {
            2: {"1": "A", "2": "B"},
            3: {"1": "A", "2": "B", "3": "C", "4": "D"},
        }
        cameraPorts = []
        newline_space = "\n "
        multiplexerQuestion = "Which type of multiplexer are you using:\n  1. None\n  2. Arducam 2 Camera Multiplexer\n  3. Arducam 4 Camera Mutiplexer\n"
        multiplexer = IntPrompt.ask(multiplexerQuestion, choices=["1", "2", "3"])
        if multiplexer == 3 or numCameras <= multiplexer:
            if multiplexer in [2, 3]:
                for i in range(numCameras):
                    prompt = f"Which port is camera {i+1} connected to:\n {newline_space.join(f'{num}. {port}' for num, port in cameraChoices[multiplexer].items())}\n"
                    port = IntPrompt.ask(
                        prompt, choices=list(cameraChoices[multiplexer].keys())
                    )
                    cameraChoices[multiplexer].pop(str(port))
                    cameraPorts.append(int(port) - 1)
            break

        else:
            warning(
                "There is a discrepancy between your multiplexer choice and the number of cameras you have.\n"
                " You can't have more cameras than slots for cameras.\n Starting again."
            )

    remlaPanel("Now updating /boot/firmware/config.txt")
    arducamMultiplexers = {2: "camera-mux-2port", 3: "camera-mux-4port"}
    use_alternate_mux_bus = False
    alternate_mux_bus = None
    if multiplexer == 3:
        use_alternate_mux_bus = typer.confirm(
            "Do you want the 4-port camera mux to use an alternate I2C bus?",
            default=False,
        )
        if use_alternate_mux_bus:
            alternate_mux_bus = IntPrompt.ask(
                "Which I2C bus should the camera mux use?",
                choices=[str(i) for i in range(0, 12)],
                default=3,
            )

    dtOverlayString = "dtoverlay="

    if multiplexer == 1:
        dtOverlayString += sensor
    else:
        cams = ["cam" + str(i) + "-" + sensor for i in cameraPorts]
        arducamString = ",".join(cams)
        overlay_name = arducamMultiplexers[multiplexer]
        if use_alternate_mux_bus:
            overlay_name = remlaCameraMux4PortOverlayName
        dtOverlayString += f"{overlay_name},{arducamString}"
        if alternate_mux_bus is not None:
            dtOverlayString += f",i2c{alternate_mux_bus}"

    if use_alternate_mux_bus:
        _install_remla_overlays()
        warning(
            "Make sure the selected I2C bus is also configured, for example with "
            f"dtoverlay=i2c-gpio,bus={alternate_mux_bus},i2c_gpio_sda=23,i2c_gpio_scl=24"
        )

    if customSensor:
        warning("Issue with custom sensor!")
        rprint(
            f"Because you provided the custom sensor, [green]{sensor}[/green], it is not guaranteed this installer"
            f" can successfully make the changes to /boot/firmware/config.txt"
        )
        rprint(
            f"Therefore you will need to manually add the line \n[i green]{dtOverlayString}[/i green] \nto your "
            f"config.txt. Just make sure that you don't have two camera related dtoverlays."
        )
        rprint(
            "To make the change, copy the dtoverlay string above, run the command \n[i green]sudo nano "
            "/boot/firmware/config.txt[/i green] \nand paste over your previous dtoverlay or right "
            "below the camera_auto_detect line."
        )

    else:
        with open(bootConfigPath, "r") as file:
            config = file.readlines()

        # Additional setup for camera_auto_detect replacement
        cameraAutoDetectSearch = "camera_auto_detect=1"
        cameraAutoDetectReplace = "camera_auto_detect=0"

        # Prepare the regex pattern
        # Combine allowed sensors and arducam multiplexer values into one list for the regex pattern
        combinedOptions = (
            allowedSensors
            + list(arducamMultiplexers.values())
            + [remlaCameraMux4PortOverlayName]
        )
        pattern = re.compile(
            r"dtoverlay=("
            + "|".join(re.escape(option) for option in combinedOptions)
            + ")"
        )

        # Search and replace the line, or prepare to append
        dtOverlayFound = False
        for i, line in enumerate(config):
            # Replace camera_auto_detect line if found
            if cameraAutoDetectSearch in line:
                config[i] = cameraAutoDetectReplace + "\n"
                rprint(
                    f"Switching [red]{cameraAutoDetectSearch}[/red] --> [green]{cameraAutoDetectReplace}[/green]"
                )
            if pattern.search(line):
                rprint(
                    f"Switching [red]{config[i]}[/red] --> [green]{dtOverlayString}[/green]"
                )
                config[i] = dtOverlayString + "\n"  # Replace the line
                dtOverlayFound = True
                break

        # If the pattern wasn't found, append the dtOverlayString
        if not dtOverlayFound:
            config.append(dtOverlayString + "\n")
            rprint(
                f"Did not find any camera related dtoverlays in /boot/firmware/config.txt. Appending {dtOverlayString} to end of file."
            )

        # Write the modified content back to the config file
        with open(bootConfigPath, "w") as file:
            file.writelines(config)

        localip = _localip()

        finalInfo = updateFinalInfo(setupDirectory / "finalInfoTemplate.md")
        with open(settingsDirectory / "finalInfo.md", "w") as file:
            file.write(finalInfo)

        subprocess.run(
            ["sudo", "chown", "-R", f"{user}:{user}", f"{remoteLabsDirectory}"]
        )
        subprocess.run(
            ["sudo", "chown", "-R", f"{user}:{user}", f"{settingsDirectory}"]
        )

        message = Text(
            f"You have finished installing remla, the remoteLabs control center.\n"
            f"The next is for you to go one of:\n"
            f"http://{hostname}.local:8080\n"
            f"http://{localip}:8080\n"
            f"Follow the instructions there."
            f"If that doesn't work then run `remla finalinfo` to see it in the command line.",
            justify="center",
        )

        panelDisplay(
            message, title="🎉🎉🎉 Congratulations! 🎉🎉🎉", border_style="green"
        )


def _createSettingsFile():
    """
    Creates the settings file living in the settings folder.
    """

    settings = {
        "paths": {
            "settingsDirectory": settingsDirectory,
            "remoteLabsDirectory": remoteLabsDirectory,
            "websiteDirectory": websiteDirectory,
            "logsDirectory": logsDirectory,
            "nginxTemplatePath": nginxTemplatePath,
            "mediamtxBinaryLocation": mediamtxBinaryLocation,
            "mediamtxSettingsLocation": mediamtxSettingsLocation,
        },
        "currentLab": None,
    }

    with open(settingsDirectory / "settings.yml", "w") as file:
        yaml.dump(settings, file)


@app.command(help="Display finall installation info in the terminal")
def finalinfo():
    with open(settingsDirectory / "finalInfo.md", "r") as file:
        markdown = file.read()
        md = Markdown(markdown)
    rprint(md)


def _ip():
    try:
        # Create a dummy socket to connect to an external site
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Use Google's Public DNS server to find the best local IP
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        rprint(local_ip)
    except Exception as e:
        print(f"Error obtaining local IP address: {e}")
        return None


@app.command()
def localip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(("10.254.254.254", 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = "127.0.0.1"
    finally:
        s.close()
    typer.echo(IP)


def _localip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(("10.254.254.254", 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = "127.0.0.1"
    finally:
        s.close()
    return IP


def updateFinalInfo(template: Path) -> str:
    """
    Taks in a file reads it as text. Makes the substitutions of placeholders and give the contents of the file back as a string.
    :param template: Path to file
    :return: string with updated text from file.
    """
    # Placeholder values
    placeholders = {
        "{{ remoteLabsDirectory }}": str(remoteLabsDirectory.name),
        "{{ settingsDirectory }}": str(settingsDirectory),
        "{{ packagesToCheck }}": ", ".join(packagesToCheck[1:]),
        "{{ mediamtxVersion }}": mediamtxVersion,
        "{{ mediamtxBinaryLocation }}": str(mediamtxBinaryLocation),
        "{{ mediamtxSettingsLocation }}": str(mediamtxSettingsLocation),
        "{{ nginxWebsitePath }}": str(nginxWebsitePath),
    }

    # Read the HTML template
    with open(template, "r") as file:
        content = file.read()

    # Replace each placeholder with its corresponding value
    for placeholder, replacement in placeholders.items():
        content = content.replace(placeholder, replacement)

    return content


@app.command("run")
@app.command("start")
def run(
    admin: Optional[bool] = typer.Option(False, "--admin", "-a", help="Run as admin."),
    foreground: Optional[bool] = typer.Option(
        False, "--foreground", "-f", help="Run in the foreground"
    ),
    wstest: Optional[bool] = typer.Option(
        False, "--wstest", "-w", help="Runs echo test server"
    ),
):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("#" * 80)
    print(f"########{now.center(64)}########")
    print("#" * 80)
    print()
    include_service = "INVOCATION_ID" not in os.environ
    if _is_remla_running(include_service=include_service):
        warning(
            "Remla is already running. If you want to restart run `remla restart` or stop before running with new options."
        )
        raise typer.Abort()
    if foreground or wstest:
        pidFilePath.parent.mkdir(parents=True, exist_ok=True)
        pidFilePath.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, lambda signum, frame: cleanupPID())
    signal.signal(signal.SIGINT, lambda signum, frame: cleanupPID())
    # perform initial camera cycling once per boot (if configured)
    cycle_camera = get_boot_status()
    logger = get_camera_logger()
    if cycle_camera:
        rprint("Performing initial camera cycle (per‑boot) before starting service...") 
        logger.info("""
        ##############################################################
        ####                Starting New Log                      ####
        ##############################################################    
        """)
        cycle_initialize_cameras(timeout_per_camera=4)
    else:
        rprint("Skipping initial camera cycle (already performed this boot).")
    if wstest:
        print("Starting Echo Server")

        async def echo(websocket, path):
            async for message in websocket:
                await websocket.send(f"Message received cap'n: {message}")

        start_server = websockets.serve(echo, "localhost", 8675)

        asyncio.get_event_loop().run_until_complete(start_server)
        asyncio.get_event_loop().run_forever()
    elif not foreground:
        try:
            subprocess.run(["systemctl", "start", "remla.service"], check=True)
            success("Running remla in background!")
            subprocess.run(["systemctl", "restart", "mediamtx.service"], check=True)
        except subprocess.CalledProcessError as e:
            alert(f"Failed to start remla due to {e}")
            raise typer.Abort()
    else:
        print("Starting remla websocket server")
        typer.echo("Echo above statment")
        remlaSettingsPath = settingsDirectory / "settings.yml"
        # Check if the settings file exists
        if not remlaSettingsPath.exists():
            alert(f"Settings file not found at {remlaSettingsPath}.")
            raise typer.Abort()

        remlaSettings = yaml.load(remlaSettingsPath)
        currentLabSettingsPath = remoteLabsDirectory / remlaSettings["currentLab"]

        if not currentLabSettingsPath or not currentLabSettingsPath.exists():
            alert(
                f"Lab settings file does not exist or no current lab configured at {currentLabSettingsPath}. Please check your settings.yml."
            )
            raise typer.Abort()

        labSettings = yaml.load(currentLabSettingsPath)
        if "devices" not in labSettings:
            alert(
                f"Device list not found in the lab settings file located at {currentLabSettingsPath}. Please update the file to include your list of devices."
            )
            raise typer.Abort()

        # Initialize devices from the lab settings
        devices = createDevicesFromYml(labSettings["devices"])
        print("Using devices:", labSettings["devices"])
        # Create and setup the experiment
        if admin:
            experiment = Experiment("RemoteLabs", admin=True)
        else:
            experiment = Experiment("RemoteLabs")

        for device in devices.values():
            experiment.addDevice(device)

        #### Now set up the locks.
        locksConfig = labSettings.get("locks", {})

        for lockGroup, deviceNames in locksConfig.items():
            try:
                # Convert device names to device objects
                deviceObjects = [
                    devices[name] for name in deviceNames if name in devices
                ]

                # In case some devices listed in YAML are not initialized or missing
                if len(deviceObjects) != len(deviceNames):
                    missingDevices = set(deviceNames) - set(devices.keys())
                    alert(
                        f"Lock group '{lockGroup}' refers to undefined devices: {missingDevices}"
                    )
                    raise typer.Abort()

                # Apply the lock to the group of device objects
                experiment.addLockGroup(lockGroup, deviceObjects)
            except KeyError as e:
                alert(f"Device name error in lock configuration: {str(e)}")
                raise typer.Abort()
        # Placeholder for further experiment execution logic
        success("Experiment setup complete.")
        get_boot_status()
        experiment.startServer()


@app.command()
def stop():
    try:
        typer.echo(
            "Stopping remla. This could take some time for the system to reset to its starting parameters. Please be patient."
        )
        subprocess.run(["systemctl", "stop", "remla.service"], check=True)
        pid = _read_remla_pid()
        if pid is not None and _pid_is_remla(pid):
            os.kill(pid, signal.SIGTERM)
        pidFilePath.unlink(missing_ok=True)
        success("Stopped running remla")
    except (OSError, subprocess.CalledProcessError) as exc:
        alert(f"Failed to stop remla: {exc}")


def _read_remla_pid() -> Optional[int]:
    try:
        return int(pidFilePath.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _pid_is_remla(pid: int) -> bool:
    try:
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return False
    return b"remla" in command and (b" run" in command or b" start" in command)


def _remla_service_is_active() -> bool:
    return (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", "remla.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def _is_remla_running(include_service: bool = True) -> bool:
    pid = _read_remla_pid()
    if pid is not None:
        if _pid_is_remla(pid):
            return True
        pidFilePath.unlink(missing_ok=True)
    return include_service and _remla_service_is_active()


@app.command()
def status():
    running = _is_remla_running()
    if running:
        typer.echo("Remla is running")
    else:
        typer.echo("Remla is not running")
    return running


@app.command()
def enable():
    try:
        subprocess.run(["systemctl", "enable", "remla.service"], check=True)
        success("Remla will now run on boot.")
    except subprocess.CalledProcessError:
        alert("Something went wrong.")


@app.command()
def disable():
    try:
        subprocess.run(["systemctl", "disable", "remla.service"], check=True)
        success("Remla will not run on boot.")
    except subprocess.CalledProcessError:
        alert("Something went wrong.")


def createRemlaPolicy():
    user = homeDirectory.owner()
    # Allows remla users to run
    policyKit = """[Allow Non-root Users to Manage Remla Service]
Identity=unix-group:remlausers
Action=org.freedesktop.systemd1.manage-units
ResultActive=yes
ResultInactive=yes
ResultAny=yes
"""
    groupName = "remlausers"
    with open(Path("/etc/polkit-1/localauthority/50-local.d/remla.pkla"), "w") as file:
        file.write(policyKit)
    try:
        subprocess.run(["sudo", "groupadd", groupName], check=True)
        success(f"Group '{groupName}' created successfully.")
    except subprocess.CalledProcessError:
        warning(f"Failed to create group '{groupName}'. It may already exist.")
    try:
        subprocess.run(["sudo", "usermod", "-a", "-G", groupName, user], check=True)
        success(f"User '{user}' added to group '{groupName}' successfully.")
    except subprocess.CalledProcessError:
        warning(f"Failed to add user '{user}' to group '{groupName}'.")


@app.command()
def upgrade(
    pipx_home: Annotated[str, typer.Argument()] = "/opt/pipx",
    pipx_bin: Annotated[str, typer.Argument()] = "/usr/local/bin",
):
    try:
        subprocess.run(
            [
                "sudo",
                f"PIPX_HOME={pipx_home}",
                f"PIPX_BIN={pipx_bin}",
                "pipx",
                "upgrade",
                "remla",
            ],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        alert(f"Unable to upgrade do to:\n{e}")


@app.command()
def git(giturl: Annotated[str, typer.Argument()]):
    if not urlValidator(giturl):
        raise typer.Abort()
    # Parse the URL to get the path component, specifically the last part
    repo_path = Path(giturl)
    base_name = repo_path.name

    # Remove the .git from the end if it exists
    if base_name.endswith(".git"):
        base_name = base_name[:-4]

    # Replace any characters not allowed in directory names, if necessary
    safe_name = re.sub(r"[^\w\-_\. ]", "_", base_name)
    cloneDirectory = remoteLabsDirectory / safe_name
    try:
        cloneDirectory.mkdir(exist_ok=False)
        subprocess.run(["git", "clone", giturl, cloneDirectory], check=True)
        success(f"Cloned directory to here to {cloneDirectory}")
    except FileExistsError:
        alert(
            f"That git repo already has a directory in {cloneDirectory}. Rename that folder before continuing"
        )
        raise typer.Abort()
    except subprocess.CalledProcessError as e:
        alert(f"There was an issue cloning the repo:\n{e}")
        raise typer.Abort()


@app.command()
def testws():
    async def echo(websocket, path):
        async for message in websocket:
            await websocket.send(message)

    start_server = websockets.serve(echo, "localhost", 8000)

    asyncio.get_event_loop().run_until_complete(start_server)
    asyncio.get_event_loop().run_forever()

@app.command()
def boot():
    """Send 'boot' command to the running remla server via IPC."""
    ipc_path = "/tmp/remla_cmd.sock"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(ipc_path)
            sock.sendall(b"boot")
        print("Boot command sent to server.")
    except Exception as e:
        print(f"Failed to send boot command: {e}")

@app.command()
def contact():
    """Send 'contact' command to the running remla server via IPC."""
    ipc_path = "/tmp/remla_cmd.sock"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(ipc_path)
            sock.sendall(b"contact")
        print("Contact command sent to server.")
    except Exception as e:
        print(f"Failed to send contact command: {e}")



if __name__ == "__main__":
    app()
# TODO: Create new command that builds a new lab.
# TODO: Create a setup command that shifts files around
# TODO: mediamtx just doesn't work right now for some reason.
