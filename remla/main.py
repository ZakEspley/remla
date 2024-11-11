#!/home/remoteLabs/.cache/pypoetry/virtualenvs/remla-BlFEVOYb-py3.11/bin/python

import subprocess
import socket
import click
from rich.prompt import Prompt, IntPrompt
from rich import print as rprint
from rich.text import Text
from rich.markdown import Markdown
from remla import settings
import typer
from typing_extensions import Annotated
from typing import Optional
import shutil
from pathlib import Path
from remla.typerHelpers import *
from remla.systemHelpers import *
import re
from pathvalidate import ValidationError, validate_filename
from .customvalidators import *
from remla import setupcmd
from remla import i2ccmd
import os
from remla.settings import *
from remla.yaml import yaml, createDevicesFromYml
from remla.labcontrol.Experiment import Experiment
from remla.labcontrol.Controllers import *
import asyncio
import websockets
import datetime
import signal


app = typer.Typer()
app.add_typer(setupcmd.app, name="setup")
app.add_typer(i2ccmd.app, name="i2c")


@app.command()
def hello():
    typer.secho("Hello world", color="green")

@app.command()
def echo(message: Annotated[str, typer.Argument()]):
    typer.echo(message)

@app.command()
def showconfig():
    app_dir = typer.get_app_dir(APP_NAME)
    typer.echo(app_dir)

@app.command()
def test():
    _createSettingsFile()

@app.command()
def fileaccesstest():
    with open("setup/hello.txt", "r") as file:
        contents = file.read()
    typer.echo(contents)



@app.command()
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
        subprocess.run(["sudo", "raspi-config", "nonint", "do_i2c", "0"], check=True) #0 mean true in bash I guess
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
        typer.echo(f"Please run the following command:")
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
    mediamtx()

    ####### Seting up NGINX for the user now ############
    nginx()

    ####### Create an initial settings file #############
    _createSettingsFile()
    ####### Create a remla.service daemon   #############
    createServiceFile(echo=True)
    createRemlaPolicy()

    interactivesetup()
    typer.echo("Wrapping up install...")
    subprocess.run(["sudo", "systemctl", "daemon-reload"])
    subprocess.run(["sudo", "systemctl", "restart", "remla.service"])
    enable_service("remla")
    # alert("Running test websocket server. Press Ctrl-C when you are done testing.")
    # run(wstest=True)



@app.command()
def mediamtx():
    remlaPanel("Installing MediaMTX")
    typer.echo("  Checking for prior installation")
    mediamtxInstalled = False
    if os.path.exists("/usr/local/bin/mediamtx"):
        typer.echo("  Already found Mediamtx Installation")
        mediamtxInstalled = True
    else:
        echoResult(
            download_and_extract_tar(mediaMTX_tar_file, settingsDirectory, "mediamtx"),
            "Downloaded and extracted MediaMTX",
            "Something went wrong in the downloading and extracting process. Check internet and try again."
        )
    typer.echo("  Creating MediaMTX Systemlinks to fix LibCameraBug")
    typer.echo("  Creating MediaMTX settings file")
    # Change log file location in mediamtx.yml settings file.
    # Then save the new mediamtx.yml file to /usr/local/etc where mediamtx says to locate
    # the file.
    mediamtxSettings = yaml.load(setupDirectory / "mediamtx.yml")
    mediamtxSettings["logFile"] = str(logsDirectory / "mediamtx.log")
    encryptionValue = mediamtxSettings["encryption"]
    rtmpEncryptionValue = mediamtxSettings["rtmpEncryption"]
    mediamtxSettings["encryption"] = "<replace1>"
    mediamtxSettings["rtmpEncryption"] = "<replace2>"
    mediamtxSettingsLocation = Path("/usr/local/etc")
    (mediamtxSettingsLocation / "mediamtx.yml").unlink(missing_ok=True)

    mediamtxSettingsLocation.mkdir(parents=True, exist_ok=True)
    yaml.dump(mediamtxSettings, mediamtxSettingsLocation/"mediamtx.yml")
    with open(mediamtxSettingsLocation/"mediamtx.yml", "r") as file:
        content = file.read()
    content = content.replace("<replace1>", f'"{encryptionValue}"')
    content = content.replace("<replace2>", f'"{rtmpEncryptionValue}"')
    with open(mediamtxSettingsLocation/"mediamtx.yml", "w") as file:
        file.write(content)

    # Now move mediamtx binary to /usr/local/bin where mediamtx says to move it
    if not mediamtxInstalled:
        moveAndOverwrite(settingsDirectory / "mediamtx/mediamtx", mediamtxBinaryLocation)
    # Move service file to systemd so that we can run it on boot.
    shutil.copy(setupDirectory / "mediamtx.service", "/etc/systemd/system")

    # Finally setup systemd to run this service on start.
    subprocess.run(["sudo", "systemctl", "daemon-reload"])
    subprocess.run(["sudo", "systemctl", "enable", "mediamtx"])
    subprocess.run(["sudo", "systemctl", "start", "mediamtx"])
    subprocess.run(["sudo", "systemctl", "restart", "mediamtx"])
    success("Successfully set up mediamtx")



@app.command()
def nginx():

    logsDirectory.mkdir(parents=True, exist_ok=True)
    typer.echo("Setting up NGINX")
    # Make directory for the running website.
    #nginxWebsitePath.mkdir(parents=True, exist_ok=True)
    
    shutil.copy(setupDirectory / "reader.js", websiteJSDirectory)
    shutil.copy(setupDirectory / "mediaMTXGetFeed.js", websiteJSDirectory)


    updateRemlaNginxConf(8080, hostname, 8675)

    updatedHtml = updateFinalInfo(setupDirectory / "index.html")
    # Write the processed HTML to a new file or use as needed
    with open(websiteDirectory/"index.html", 'w') as file:
        file.write(updatedHtml)

    shutil.copytree(websiteDirectory, nginxWebsitePath, dirs_exist_ok=True)

    typer.echo("Making NGINX run at boot")
    echoResult(
        enable_service("nginx"),
        "NGINX can now run at boot.",
        "Failed to allow NGINX to start at boot."
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
    cont_int, = typer.confirm("Do you want to continue with interactive install?", default="y"),
    if not cont_int:
        return
    allowedSensors = ["ov5647", "imx219", "imx477", "imx708", "imx519", "other"]
    sensorQuestionString = f"Select which type of sensor you will be using [1-5]:\n"
    for i, sensor in enumerate(allowedSensors):
        sensorQuestionString += f"  {i+1}. {sensor} \n"
    sensorIdx = IntPrompt.ask(sensorQuestionString, choices=["1","2","3","4","5","6"]) - 1
    customSensor = False
    if sensorIdx == 5:
        customSensor = True
        sensor= typer.prompt("Please provide the name of your sensor as required by raspberry pi or arducam (make sure you know what you are doing)", confirmation_prompt=True)
    else:
        sensor = allowedSensors[sensorIdx]


    while True:
        numCameras = IntPrompt.ask("How many cameras will you be using?", choices=["1","2","3","4"])
        cameraChoices = {2:{"1":"A", "2":"B"}, 3:{"1":"A", "2":"B", "3":"C", "4":"D"}}
        cameraPorts = []
        newline_space = "\n "    
        multiplexerQuestion = "Which type of multiplexer are you using:\n  1. None\n  2. Arducam 2 Camera Multiplexer\n  3. Arducam 4 Camera Mutiplexer\n"
        multiplexer = IntPrompt.ask(multiplexerQuestion, choices=["1","2","3"])
        if multiplexer==3 or numCameras <= multiplexer:
            if multiplexer in [2,3]:
                for i in range(numCameras):
                    prompt = f"Which port is camera {i+1} connected to:\n {newline_space.join(f'{num}. {port}' for num, port in cameraChoices[multiplexer].items())}\n"
                    port = IntPrompt.ask(prompt, choices=list(cameraChoices[multiplexer].keys()))
                    cameraChoices[multiplexer].pop(str(port))
                    cameraPorts.append(int(port)-1)
            break

        else:
            warning("There is a discrepancy between your multiplexer choice and the number of cameras you have.\n"
                  " You can't have more cameras than slots for cameras.\n Starting again.")

    remlaPanel("Now updating /boot/firmware/config.txt")
    arducamMultiplexers = {2:"camera-mux-2port", 3:"camera-mux-4port"}
    dtOverlayString = "dtoverlay="

    if multiplexer == 1:
        dtOverlayString += sensor
    else:
        cams = ['cam'+str(i)+'-'+sensor for i in cameraPorts]
        arducamString = ",".join(cams)
        dtOverlayString += f"{arducamMultiplexers[multiplexer]},{arducamString}"

    if customSensor:
        warning("Issue with custom sensor!")
        rprint(f"Because you provided the custom sensor, [green]{sensor}[/green], it is not guaranteed this installer"
                   f" can successfully make the changes to /boot/firmware/config.txt")
        rprint(f"Therefore you will need to manually add the line \n[i green]{dtOverlayString}[/i green] \nto your "
                   f"config.txt. Just make sure that you don't have two camera related dtoverlays.")
        rprint(f"To make the change, copy the dtoverlay string above, run the command \n[i green]sudo nano "
                   f"/boot/firmware/config.txt[/i green] \nand paste over your previous dtoverlay or right "
                   f"below the camera_auto_detect line.")

    else:
        with open(bootConfigPath, "r") as file:
            config = file.readlines()

        # Additional setup for camera_auto_detect replacement
        cameraAutoDetectSearch = "camera_auto_detect=1"
        cameraAutoDetectReplace = "camera_auto_detect=0"

        # Prepare the regex pattern
        # Combine allowed sensors and arducam multiplexer values into one list for the regex pattern
        combinedOptions = allowedSensors + list(arducamMultiplexers.values())
        pattern = re.compile(r'dtoverlay=(' + '|'.join(re.escape(option) for option in combinedOptions) + ')')

        # Search and replace the line, or prepare to append
        dtOverlayFound = False
        for i, line in enumerate(config):
            # Replace camera_auto_detect line if found
            if cameraAutoDetectSearch in line:
                config[i] = cameraAutoDetectReplace + '\n'
                rprint(f"Switching [red]{cameraAutoDetectSearch}[/red] --> [green]{cameraAutoDetectReplace}[/green]")
            if pattern.search(line):
                rprint(f"Switching [red]{config[i]}[/red] --> [green]{dtOverlayString}[/green]")
                config[i] = dtOverlayString + '\n'  # Replace the line
                dtOverlayFound = True
                break

        # If the pattern wasn't found, append the dtOverlayString
        if not dtOverlayFound:
            config.append(dtOverlayString + '\n')
            rprint(f"Did not find any camera related dtoverlays in /boot/firmware/config.txt. Appending {dtOverlayString} to end of file.")

        # Write the modified content back to the config file
        with open(bootConfigPath, 'w') as file:
            file.writelines(config)

        localip = _localip()

        finalInfo = updateFinalInfo(setupDirectory/"finalInfoTemplate.md")
        with open(settingsDirectory/ "finalInfo.md", "w") as file:
            file.write(finalInfo)

        subprocess.run(["sudo", "chown", "-R", f"{user}:{user}", f"{remoteLabsDirectory}"])
        subprocess.run(["sudo", "chown", "-R", f"{user}:{user}", f"{settingsDirectory}"])

        message = Text(f"You have finished installing remla, the remoteLabs control center.\n"
                       f"The next is for you to go one of:\n"
                       f"http://{hostname}.local:8080\n"
                       f"http://{localip}:8080\n"
                       f"Follow the instructions there."
                       f"If that doesn't work then run `remla finalinfo` to see it in the command line.",
                       justify="center")


        panelDisplay(message, title="🎉🎉🎉 Congratulations! 🎉🎉🎉", border_style="green")

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
            "mediamtxSettingsLocation": mediamtxSettingsLocation
        },
        "currentLab": None,
    }

    with open(settingsDirectory / "settings.yml", "w") as file:
        yaml.dump(settings, file)



@app.command()
def finalinfo():
    with open(settingsDirectory / "finalInfo.md", "r") as file:
        markdown = file.read()
        md = Markdown(markdown)
    rprint(md)

@app.command()
def ip():
    try:
        # Create a dummy socket to connect to an external site
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Use Google's Public DNS server to find the best local IP
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        rprint( local_ip )
    except Exception as e:
        print(f"Error obtaining local IP address: {e}")
        return None

@app.command()
def localip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    typer.echo(IP)

def _localip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def updateFinalInfo(template:Path) -> str:
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
        "{{ nginxWebsitePath }}": str(nginxWebsitePath)
    }

    # Read the HTML template
    with open(template, 'r') as file:
        content = file.read()

    # Replace each placeholder with its corresponding value
    for placeholder, replacement in placeholders.items():
        content = content.replace(placeholder, replacement)

    return content


@app.command("run")
@app.command("start")
def run(
    admin: Optional[bool] = typer.Option(False, "--admin", "-a", help="Run as admin."),
    foreground: Optional[bool] = typer.Option(False, "--foreground", "-f", help="Run in the foreground"),
    wstest: Optional[bool] = typer.Option(False, "--wstest", "-w", help="Runs echo test server")
):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("#"*80)
    print(f"########{now.center(64)}########")
    print("#"*80)
    print()
    if status():
        warning("Remla is already running. If you want to restart run `remla restart` or stop before running with new options.")
        raise typer.Abort()
    signal.signal(signal.SIGTERM, lambda signum, frame: cleanupPID())
    signal.signal(signal.SIGINT, lambda signum, frame: cleanupPID())

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
            alert(f"Lab settings file does not exist or no current lab configured at {currentLabSettingsPath}. Please check your settings.yml.")
            raise typer.Abort()

        labSettings = yaml.load(currentLabSettingsPath)
        if "devices" not in labSettings:
            alert(f"Device list not found in the lab settings file located at {currentLabSettingsPath}. Please update the file to include your list of devices.")
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
        locksConfig = labSettings.get('locks', {})
        
        for lockGroup, deviceNames in locksConfig.items():
            try:
                # Convert device names to device objects
                deviceObjects = [devices[name] for name in deviceNames if name in devices]

                # In case some devices listed in YAML are not initialized or missing
                if len(deviceObjects) != len(deviceNames):
                    missingDevices = set(deviceNames) - set(devices.keys())
                    alert(f"Lock group '{lockGroup}' refers to undefined devices: {missingDevices}")
                    raise typer.Abort()

                # Apply the lock to the group of device objects
                experiment.addLock(deviceObjects)
            except KeyError as e:
                alert(f"Device name error in lock configuration: {str(e)}")
                raise typer.Abort()
        # Placeholder for further experiment execution logic
        success("Experiment setup complete.")
        experiment.startServer()

@app.command()
def stop():
    try:
        typer.echo("Stopping remla. This could take some time for the system to reset to its starting parameters. Please be patient.")
        subprocess.run(['systemctl', 'stop', 'remla.service'], check=True)
        success("Stopped running remla")
    except subprocess.CalledProcessError:
        alert("Failed to stop remla")



@app.command()
def status():
    #pidFilePathFull = pidFilePath.replace("<uid>", str(getCallingUserID()))
    print(pidFilePath)
    if os.path.exists(pidFilePath):
        # Read exisitng pid file
        with open(pidFilePath, 'r') as file:
            try:
                pid = int(file.read().strip())
                os.kill(pid, 0)
                typer.echo("Remla is already running")
                return True
            except ValueError:
                typer.echo("PID File is corrupt. Starting a new instance.")
            except ProcessLookupError:
                typer.echo("Remla instance not found. Staring new isntance")
            except PermissionError:
                typer.echo("Permission denied when checking PID. Assuming its running.")
                return True
    else:
        typer.echo("No PID file found. Starting new instance of remla")

    with open(pidFilePath, "w+") as file:
        file.write(str(os.getpid()))
    return False

@app.command()
def enable():
    try:
        subprocess.run(['systemctl', 'enable', 'remla.service'], check=True)
        success("Remla will now run on boot.")
    except subprocess.CalledProcessError:
        alert("Something went wrong.")

@app.command()
def disable():
    try:
        subprocess.run(['systemctl', 'disable', 'remla.service'], check=True)
        success("Remla will not run on boot.")
    except subprocess.CalledProcessError:
        alert("Something went wrong.")

def createRemlaPolicy():
    user = homeDirectory.owner()
    #Allows remla users to run
    policyKit = f"""[Allow Non-root Users to Manage Remla Service]
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
        subprocess.run(['sudo', 'groupadd', groupName], check=True)
        success(f"Group '{groupName}' created successfully.")
    except subprocess.CalledProcessError:
        warning(f"Failed to create group '{groupName}'. It may already exist.")
    try:
        subprocess.run(['sudo', 'usermod', '-a', '-G', groupName, user], check=True)
        success(f"User '{user}' added to group '{groupName}' successfully.")
    except subprocess.CalledProcessError:
        warning(f"Failed to add user '{user}' to group '{groupName}'.")

@app.command()
def git(giturl: Annotated[str, typer.Argument()]):
    if not urlValidator(giturl):
        raise typer.Abort()
    # Parse the URL to get the path component, specifically the last part
    repo_path = Path(giturl)
    base_name = repo_path.name

    # Remove the .git from the end if it exists
    if base_name.endswith('.git'):
        base_name = base_name[:-4]

    # Replace any characters not allowed in directory names, if necessary
    safe_name = re.sub(r'[^\w\-_\. ]', '_', base_name)
    cloneDirectory = remoteLabsDirectory / safe_name
    try:
        cloneDirectory.mkdir(exist_ok=False)
        subprocess.run(["git", "clone", giturl, cloneDirectory], check=True)
        success(f"Cloned directory to here to {cloneDirectory}")
    except FileExistsError:
        alert(f"That git repo already has a directory in {cloneDirectory}. Rename that folder before continuing")
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

#TODO: Create new command that builds a new lab.
#TODO: Create a setup command that shifts files around
#TODO: mediamtx just doesn't work right now for some reason.
