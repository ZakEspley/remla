import socket
from pathlib import Path
import typer
import os

APP_NAME = "remla"
hostname = socket.gethostname()
packagesToCheck = ["nginx", "python3-pip", "i2c-tools", "pigpio"]




###### List of important paths (for now)
mediaMTX_1_6_0_arm64_linux_url = "https://github.com/bluenviron/mediamtx/releases/download/v1.6.0/mediamtx_v1.6.0_linux_arm64v8.tar.gz"
mediamtxVersion = "1.6.0"
mediamtxSettingsLocation = Path("/usr/local/etc")
mediamtxBinaryLocation = Path("/usr/local/bin")
baseDir = Path(__file__).parent
settingsDirectory = Path(typer.get_app_dir(APP_NAME))
logsDirectory = settingsDirectory / "logs"
homeDirectory = Path.home()
remoteLabsDirectory = homeDirectory / 'remla'
setupDirectory = baseDir / "setup"
websiteDirectory = settingsDirectory / 'website'
nginxTemplatePath = setupDirectory / "remla.conf"
nginxConfPath = Path("/etc/nginx/sites-available/remla.conf")
nginxConfLinkPath = Path("/etc/nginx/sites-enabled/remla.conf")
nginxAvailablePath = Path("/etc/nginx/sites-available")
nginxEnabledPath = Path("/etc/nginx/sites-enabled")
localhostConfLinkPath = nginxEnabledPath / "localhost.conf"
bootConfigPath = Path("/boot/firmware/config.txt")
nginxWebsitePath = Path("/var/www/remla")
pidFilePath = Path(f'/var/run/user/{str(os.environ.get("SUDO_UID")) if os.environ.get("SUDO_UID") is not None else str(os.getuid())}/remla.pid')
