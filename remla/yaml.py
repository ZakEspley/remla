import typer
from ruamel.yaml import YAML
from ruamel.yaml.nodes import ScalarNode
from pathlib import Path, PosixPath, PurePosixPath, PurePath
from typing import List, Any
from remla.labcontrol import Controllers
from collections import defaultdict


# Initialize the YAML parser
yaml = YAML(typ='safe')
# yaml.preserve_quotes = True  # Preserve quotes style
yaml.indent(mapping=2, sequence=4, offset=2)  # Set indentation, optional
yaml.default_flow_style = False
# yaml.allow_unicode = True

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


def createDevicesFromYml(deviceData:dict) -> dict[Any]:
    """
    Create and initialize devices from a YAML configuration file.

    This function reads a YAML file that defines devices and their properties,
    including dependencies on other devices. It ensures all devices are initialized
    in the correct order, even when some devices depend on others being created first.

    :param deviceDict: Dictionary of device names and properties read directly from the yaml file.
    :type deviceDict: dict
    :return: A list of initialized device objects.
    :rtype: List[Any]
    :raises ValueError: If there is a circular dependency detected among devices.
    """

    # Dictionary to hold name -> object mapping
    devices = {}

    # Set to track objects currently being initialized to detect circular dependencies
    inProgress = set()

    def resolveDependencies(deviceName):
        typer.echo(f"Resolving dependency for {deviceName}")
        """
        Recursively initialize a device and its dependencies.

        This internal function creates a device object by its name after resolving
        all necessary dependencies specified in the configuration. It supports
        recursive resolution to handle nested dependencies.

        :param deviceName: The name of the device to initialize.
        :type deviceName: str
        :return: An initialized device object.
        :rtype: Any
        :raises ValueError: If circular dependencies are detected.
        """
        # Check if device is already created and return it
        if deviceName in devices:
            return devices[deviceName]

        # Circular dependency check
        if deviceName in inProgress:
            raise ValueError(f"Circular dependency detected involving {deviceName}")

        # Mark this device as being in the process of initialization
        inProgress.add(deviceName)

        # Retrieve the class type and initialization arguments for this device
        deviceDetails = deviceData[deviceName]

        # cls = globals()[deviceDetails['type']]
        cls = getattr(Controllers, deviceDetails['type'])
        initArgs = {k: v for k, v in deviceDetails.items() if k not in ['type', 'name']}

        # Resolve dependencies for each initialization argument
        for arg, value in initArgs.items():
            if isinstance(value, str) and value in deviceData:
                initArgs[arg] = resolveDependencies(value)

        # Create the device instance and add to the devices dictionary
        device = cls(name=deviceName, **initArgs)
        devices[deviceName] = device

        # Remove device from inProgress set
        inProgress.remove(deviceName)

        return device

    # Initialize all devices by resolving their dependencies
    for name in deviceData.keys():
        if name not in devices:
            resolveDependencies(name)

    return devices
