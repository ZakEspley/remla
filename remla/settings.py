import socket
from ruamel.yaml import YAML
from pathlib import Path, PosixPath, PurePosixPath, PurePath
import typer


APP_NAME = "remla"
hostname = socket.gethostname()
packagesToCheck = ["nginx", "python3-pip", "i2c-tools", "pigpio", "python3-pigpio"]
# Initialize the YAML parser
yaml = YAML()
yaml.preserve_quotes = True  # Preserve quotes style
yaml.indent(mapping=2, sequence=4, offset=2)  # Set indentation, optional

# Used to convert pathLib paths too yml files and vice versa.
def path_representer(dumper, data):
    return dumper.represent_scalar('!path', str(data))

def path_constructor(loader, node):
    value = loader.construct_scalar(node)
    return Path(value)

# Add the custom representer for Path objects
for cls in [Path, PosixPath, PurePosixPath, PurePath]:
    yaml.representer.add_representer(cls, path_representer)
# Add the custom constructor for Path objects
yaml.constructor.add_constructor('!path', path_constructor)


###### List of important paths (for now)
mediaMTX_1_6_0_arm64_linux_url = "https://github.com/bluenviron/mediamtx/releases/download/v1.6.0/mediamtx_v1.6.0_linux_arm64v8.tar.gz"
mediamtxVersion = "1.6.0"
mediamtxSettingsLocation = Path("/usr/local/etc")
mediamtxBinaryLocation = Path("/usr/local/bin")
settingsDirectory = Path(typer.get_app_dir(APP_NAME))
logsDirectory = settingsDirectory / "logs"
homeDirectory = Path.home()
remoteLabsDirectory = homeDirectory / 'remla2'
setupDirectory = Path('setup')
websiteDirectory = settingsDirectory / 'website'
nginxTemplatePath = setupDirectory / "remla.conf"
nginxConfPath = Path("/etc/nginx/sites-available/remla.conf")
nginxConfLinkPath = Path("/etc/nginx/sites-enabled/remla.conf")
nginxAvailablePath = Path("/etc/nginx/sites-available")
nginxEnabledPath = Path("/etc/nginx/sites-enabled")
localhostConfLinkPath = nginxEnabledPath / "localhost.conf"
bootConfigPath = Path("/boot/firmware/config.txt")