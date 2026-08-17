import os
import pwd
import socket
from pathlib import Path

APP_NAME = "remla"
hostname = socket.gethostname()
packagesToCheck = ["nginx", "python3-pip", "i2c-tools", "pigpio"]

sudo_uid = os.environ.get("SUDO_UID")
callingUid = int(sudo_uid) if sudo_uid is not None else os.getuid()
homeDirectory = Path(pwd.getpwuid(callingUid).pw_dir)
if sudo_uid is not None:
    configDirectory = homeDirectory / ".config"
else:
    configDirectory = Path(os.environ.get("XDG_CONFIG_HOME", homeDirectory / ".config"))



###### List of important paths (for now)
mediamtxVersion = "latest available release"
mediamtxSettingsLocation = Path("/usr/local/etc")
mediamtxBinaryLocation = Path("/usr/local/bin")
baseDir = Path(__file__).parent
settingsDirectory = configDirectory / APP_NAME
logsDirectory = settingsDirectory / "logs"
remoteLabsDirectory = homeDirectory / 'remla'
setupDirectory = baseDir / "setup"
overlayDirectory = baseDir / "overlays"
remlaCameraMux4PortOverlayName = "remla-camera-mux-4port"
remlaCameraMux4PortOverlayPath = overlayDirectory / f"{remlaCameraMux4PortOverlayName}.dtbo"
remlaOverlayPaths = [
    remlaCameraMux4PortOverlayPath,
    overlayDirectory / "remla-camera-mux-4port-i2c-gpio.dtbo",
]
bootOverlayDirectory = Path("/boot/firmware/overlays")
websiteDirectory = settingsDirectory / 'website'
nginxTemplatePath = setupDirectory / "remla.conf"
nginxConfPath = Path("/etc/nginx/sites-available/remla.conf")
nginxConfLinkPath = Path("/etc/nginx/sites-enabled/remla.conf")
nginxAvailablePath = Path("/etc/nginx/sites-available")
nginxEnabledPath = Path("/etc/nginx/sites-enabled")
localhostConfLinkPath = nginxEnabledPath / "localhost.conf"
bootConfigPath = Path("/boot/firmware/config.txt")
nginxWebsitePath = Path("/var/www/remla")
pidFilePath = Path(f"/var/run/user/{callingUid}/remla.pid")
websiteStaticDirectory = websiteDirectory / "static"
websiteJSDirectory = websiteStaticDirectory / "js"
websiteCSSDirectory = websiteStaticDirectory / "css"
websiteImgsDirectory = websiteStaticDirectory / "imgs"

runMarker = settingsDirectory / "remla_camera_cycled" 
